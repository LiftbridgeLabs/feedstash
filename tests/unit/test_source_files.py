"""Source files stay plain text. A raw control byte in one (sanitize.js once held a literal NUL in its URL check)
makes the file unsearchable, and any editor that strips it silently changes what the code does."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEXT = {".py", ".js", ".mjs", ".css", ".html", ".md", ".sh", ".toml", ".yml", ".yaml", ".json", ".txt", ".xml", ".svg"}
CONTROL = set(range(0, 9)) | {11, 12} | set(range(14, 32))


def tracked_text_files() -> list[Path]:
    try:
        names = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return [ROOT / name for name in names.splitlines() if Path(name).suffix in TEXT and (ROOT / name).is_file()]


def test_no_source_file_holds_raw_control_bytes():
    bad = []
    for path in tracked_text_files():
        data = path.read_bytes()
        at = next((i for i, byte in enumerate(data) if byte in CONTROL), None)
        if at is not None:
            bad.append(f"{path.relative_to(ROOT)} (byte {at})")
    assert not bad, "Write control characters as escapes (e.g. \\u0000) instead: " + ", ".join(bad)
