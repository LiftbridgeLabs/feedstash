"""Domain errors raised by repositories and services. The web layer maps them to HTTP status codes."""


class ReaderError(Exception):
    """Base class. Messages are meant to be shown to users."""


class InvalidInput(ReaderError):
    pass


class NotFound(ReaderError):
    pass


class Conflict(ReaderError):
    pass


class StorageFull(ReaderError):
    """The server has reached its STORAGE_LIMIT_GB."""
