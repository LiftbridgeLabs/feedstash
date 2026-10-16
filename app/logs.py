"""FeedStash's own log files: kept in the data folder (`logs/`), rotated by size, with the level and size an admin
sets under Settings → Logs. The console (what `docker logs` shows) gets only warnings, errors and the server's
start-up lines, so Docker's copy stays small however Docker is set up.
"""

import logging
from collections import deque
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LEVELS = ("info", "debug")
REQUESTS = ("all", "changes", "errors", "none")
FILE_NAME = "feedstash.log"


@dataclass(frozen=True, slots=True)
class LogSettings:
    level: str = "info"          # info, or debug for detail when tracking down a problem
    requests: str = "changes"    # which requests get a line (see QuietRequests)
    keep_files: int = 5          # the current file plus this many older ones
    max_mb: int = 10             # how big one file gets before a new one starts

    def checked(self) -> "LogSettings":
        if self.level not in LEVELS:
            raise ValueError(f"level must be one of: {', '.join(LEVELS)}")
        if self.requests not in REQUESTS:
            raise ValueError(f"requests must be one of: {', '.join(REQUESTS)}")
        if not 1 <= self.keep_files <= 20:
            raise ValueError("keep_files must be between 1 and 20")
        if not 1 <= self.max_mb <= 100:
            raise ValueError("max_mb must be between 1 and 100")
        return self

    def as_strings(self) -> dict[str, str]:
        return {f"logs.{key}": str(value) for key, value in asdict(self).items()}

    @classmethod
    def from_strings(cls, values: dict[str, str], default: "LogSettings") -> "LogSettings":
        try:
            return cls(
                level=values.get("logs.level", default.level),
                requests=values.get("logs.requests", default.requests),
                keep_files=int(values.get("logs.keep_files", default.keep_files)),
                max_mb=int(values.get("logs.max_mb", default.max_mb)),
            ).checked()
        except ValueError:
            return default


class QuietRequests(logging.Filter):
    """Keeps only the request lines LOG_REQUESTS asks for. `changes` (the default) keeps anything that isn't a plain
    read, plus failures: what someone looking at the log after a problem wants, without health checks and page loads
    piling up thousands of lines a day."""

    def __init__(self, level: str):
        super().__init__()
        self.level = level

    def filter(self, record: logging.LogRecord) -> bool:
        if self.level == "all":
            return True
        if self.level == "none":
            return False
        args = record.args if isinstance(record.args, tuple) else ()
        method = args[1] if len(args) > 1 else ""
        status = args[4] if len(args) > 4 and isinstance(args[4], int) else 0
        if status >= 400:
            return True
        return self.level == "changes" and method not in ("GET", "HEAD", "OPTIONS")


class LogFiles:
    """The rotating file and the quiet console. `apply` can be called again with new settings at any time."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self._file: RotatingFileHandler | None = None
        self._console: logging.Handler | None = None

    @property
    def path(self) -> Path:
        return self.directory / FILE_NAME

    def apply(self, settings: LogSettings) -> None:
        root = logging.getLogger()
        formatter = logging.Formatter(LOG_FORMAT)
        if self._file is None:
            self.directory.mkdir(parents=True, exist_ok=True)
            self._file = RotatingFileHandler(self.path, encoding="utf-8", delay=True)
            self._file.setFormatter(formatter)
            root.addHandler(self._file)
        self._file.maxBytes = settings.max_mb * 1024 * 1024
        self._file.backupCount = settings.keep_files
        self._file.setLevel(logging.DEBUG)
        root.setLevel(logging.DEBUG if settings.level == "debug" else logging.INFO)

        # The console: our own handler at WARNING, replacing any catch-all one basicConfig left.
        for handler in [h for h in root.handlers if h is not self._file and h is not self._console]:
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
                root.removeHandler(handler)
        if self._console is None:
            self._console = logging.StreamHandler()
            self._console.setFormatter(formatter)
            root.addHandler(self._console)
        self._console.setLevel(logging.WARNING)

        # uvicorn's loggers don't pass records up to the root: give them the file too. Request lines go only to the
        # file; uvicorn's own start-up and error lines still reach the console.
        for name in ("uvicorn.access", "uvicorn.error"):
            logger = logging.getLogger(name)
            if self._file not in logger.handlers:
                logger.addHandler(self._file)
        for handler in logging.getLogger("uvicorn.access").handlers:
            if handler is not self._file:
                handler.setLevel(logging.WARNING)
        access = logging.getLogger("uvicorn.access")
        for old in [f for f in access.filters if isinstance(f, QuietRequests)]:
            access.removeFilter(old)
        access.addFilter(QuietRequests(settings.requests))

    def files(self) -> list[Path]:
        """Oldest first: feedstash.log.N … feedstash.log.1, then feedstash.log. Only the numbered files rotation
        makes: anything else in the folder (a .bak someone left) is not part of the log."""
        older = [p for p in self.directory.glob(f"{FILE_NAME}.*") if p.suffix[1:].isdigit()]
        older.sort(key=lambda p: int(p.suffix[1:]), reverse=True)
        return [*older, *([self.path] if self.path.exists() else [])]

    def tail(self, lines: int = 300) -> list[str]:
        """The last `lines` lines, reading the newest file first and older ones only if it's short."""
        if self._file is not None:
            self._file.flush()
        collected: list[str] = []
        for path in reversed(self.files()):
            last: deque[str] = deque(maxlen=lines - len(collected))
            with path.open(encoding="utf-8", errors="replace") as handle:
                last.extend(line.rstrip("\n") for line in handle)
            collected = [*last, *collected]
            if len(collected) >= lines:
                break
        return collected

    def stream(self, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
        """The whole log, oldest first, a piece at a time (it can be a couple of gigabytes at the largest settings)."""
        if self._file is not None:
            self._file.flush()
        for path in self.files():
            with path.open("rb") as handle:
                while chunk := handle.read(chunk_size):
                    yield chunk
