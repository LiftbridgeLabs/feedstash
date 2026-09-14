def collapse_whitespace(value: str | None) -> str:
    """Trims and squeezes runs of whitespace to single spaces."""
    return " ".join((value or "").split())
