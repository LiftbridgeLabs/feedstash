"""Credentials in a URL's query never reach the access log."""

import logging

from app.main import RedactCredentials


def access_line(path: str) -> str:
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("203.0.113.5:4000", "GET", path, "1.1", 200), None,
    )
    assert RedactCredentials().filter(record)
    return record.getMessage()


def test_a_token_in_the_query_is_hidden():
    line = access_line("/api/items?token=abc123secret&limit=5")
    assert "abc123secret" not in line
    assert "token=[hidden]&limit=5" in line


def test_reader_api_sign_in_passwords_are_hidden():
    line = access_line("/accounts/ClientLogin?Email=me@example.com&Passwd=tok-en_123")
    assert "tok-en_123" not in line
    assert "Email=me@example.com" in line


def test_ordinary_paths_are_untouched():
    assert "/api/articles?scope=all&limit=40" in access_line("/api/articles?scope=all&limit=40")
