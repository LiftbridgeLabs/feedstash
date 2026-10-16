"""FeedStash's own rotating log files and the settings that shape them."""

import logging

import pytest

from app.logs import LogFiles, LogSettings


@pytest.fixture
def log_files(tmp_path):
    files = LogFiles(tmp_path / "logs")
    yield files
    root = logging.getLogger()
    for handler in (files._file, files._console):  # leave other tests a clean root logger
        if handler is not None:
            root.removeHandler(handler)
            for name in ("uvicorn.access", "uvicorn.error"):
                logging.getLogger(name).removeHandler(handler)
            handler.close()


def test_lines_go_to_the_file_and_rotate_at_the_size_chosen(log_files):
    log_files.apply(LogSettings(max_mb=1, keep_files=2))
    log_files._file.maxBytes = 2000  # a megabyte is slow to fill in a test; the handler's own limit is what counts
    log = logging.getLogger("feedstash.test")
    for n in range(200):
        log.info("line %d with some padding to fill the file quickly", n)
    files = log_files.files()
    assert [p.name for p in files] == ["feedstash.log.2", "feedstash.log.1", "feedstash.log"]
    tail = log_files.tail(5)
    assert len(tail) == 5 and tail[-1].endswith("line 199 with some padding to fill the file quickly")
    everything = b"".join(log_files.stream()).decode()
    assert everything.index("line 150 ") < everything.index("line 199 ")  # oldest file first
    (log_files.directory / "feedstash.log.bak").write_text("not part of the log")
    assert "not part of the log" not in b"".join(log_files.stream()).decode()
    # Asking for more than the newest file holds reaches into the older ones, still in order.
    current = sum(1 for _ in log_files.path.open())
    longer = log_files.tail(current + 3)
    assert len(longer) == current + 3 and longer[-1].endswith("line 199 with some padding to fill the file quickly")


def test_debug_only_when_asked_and_the_console_only_gets_warnings(log_files):
    log_files.apply(LogSettings(level="info"))
    log = logging.getLogger("feedstash.test")
    log.debug("hidden detail")
    log.info("normal line")
    assert log_files._console.level == logging.WARNING
    log_files.apply(LogSettings(level="debug"))
    log.debug("visible detail")
    text = b"".join(log_files.stream()).decode()
    assert "hidden detail" not in text and "normal line" in text and "visible detail" in text


def test_saved_settings_fall_back_to_the_default_when_unreadable():
    default = LogSettings(requests="errors")
    assert LogSettings.from_strings({}, default) == default
    assert LogSettings.from_strings({"logs.max_mb": "25", "logs.level": "debug"}, default).max_mb == 25
    assert LogSettings.from_strings({"logs.max_mb": "lots"}, default) == default
    assert LogSettings.from_strings({"logs.level": "shouting"}, default) == default
