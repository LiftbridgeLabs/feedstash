"""The authenticator-app codes, checked against RFC 6238's published examples (SHA-1, 6 of its 8 digits)."""

from urllib.parse import parse_qs, urlsplit

from app import totp

RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # base32 of "12345678901234567890"


def test_codes_match_the_rfc_examples():
    for timestamp, code in ((59, "287082"), (1111111109, "081804"), (1234567890, "005924"), (2000000000, "279037")):
        assert totp.code_at(RFC_SECRET, totp.step_of(timestamp)) == code


def test_a_code_counts_for_a_step_either_side_and_only_once():
    now = 1_800_000_000
    step = totp.step_of(now)
    assert totp.matching_step(RFC_SECRET, totp.code_at(RFC_SECRET, step), now=now) == step
    assert totp.matching_step(RFC_SECRET, totp.code_at(RFC_SECRET, step - 1), now=now) == step - 1
    assert totp.matching_step(RFC_SECRET, totp.code_at(RFC_SECRET, step + 1), now=now) == step + 1
    assert totp.matching_step(RFC_SECRET, totp.code_at(RFC_SECRET, step - 2), now=now) is None
    assert totp.matching_step(RFC_SECRET, totp.code_at(RFC_SECRET, step), now=now, after_step=step) is None
    spaced = totp.code_at(RFC_SECRET, step)
    assert totp.matching_step(RFC_SECRET, f"{spaced[:3]} {spaced[3:]}", now=now) == step  # as some apps show it
    assert totp.matching_step(RFC_SECRET, "12345", now=now) is None
    assert totp.matching_step(RFC_SECRET, "١٢٣٤٥٦", now=now) is None  # digits in another script: wrong, not an error


def test_new_secrets_are_random_and_the_link_names_the_account():
    secret = totp.new_secret()
    assert len(secret) == 32 and secret != totp.new_secret()
    uri = urlsplit(totp.setup_uri(secret, account="ann@example.com"))
    assert (uri.scheme, uri.netloc, uri.path) == ("otpauth", "totp", "/FeedStash:ann@example.com")
    assert parse_qs(uri.query)["secret"] == [secret] and parse_qs(uri.query)["issuer"] == ["FeedStash"]
