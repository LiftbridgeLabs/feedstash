import pytest

from app.errors import InvalidInput
from app.passwords import check_new_password, hash_password, verify_password


def test_hashes_verify_and_are_salted():
    first, second = hash_password("correct horse"), hash_password("correct horse")
    assert first != second and first.startswith("scrypt$")
    assert verify_password("correct horse", first) and verify_password("correct horse", second)
    assert not verify_password("wrong horse", first)


@pytest.mark.parametrize("stored", [None, "", "plain", "scrypt$x$8$1$AAAA$BBBB", "scrypt$3$8$1$AAAA$BBBB", "md5$1$2$3$4$5"])
def test_malformed_hashes_never_verify(stored):
    assert not verify_password("anything", stored)


def test_new_passwords_need_a_sensible_length():
    assert check_new_password("12345678") == "12345678"
    with pytest.raises(InvalidInput):
        check_new_password("1234567")
    with pytest.raises(InvalidInput):
        check_new_password("x" * 1025)


def test_new_hashes_use_p3_and_old_ones_still_verify_but_need_redoing():
    from app import passwords

    new = hash_password("correct horse")
    assert new.split("$")[1:4] == ["32768", "8", "3"]
    assert not passwords.needs_rehash(new)
    old_settings = passwords._P
    passwords._P = 1
    try:
        old = hash_password("correct horse")
    finally:
        passwords._P = old_settings
    assert old.split("$")[3] == "1"
    assert verify_password("correct horse", old)
    assert passwords.needs_rehash(old)
    assert passwords.needs_rehash("") and passwords.needs_rehash("md5$1$2$3$4$5")
