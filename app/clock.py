import time


def now() -> int:
    """Current Unix time in whole seconds, the unit stored in the database."""
    return int(time.time())
