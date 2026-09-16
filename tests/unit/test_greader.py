from app import greader


def test_item_ids_in_every_form_clients_send():
    long_form = greader.item_id(42)
    assert long_form == "tag:google.com,2005:reader/item/000000000000002a"
    assert greader.parse_item_id(long_form) == 42
    assert greader.parse_item_id("42") == 42
    assert greader.parse_item_id("000000000000002a") == 42
    assert greader.parse_item_id("0000000000000010") == 16  # sixteen characters is hex, even when all digits
    assert greader.parse_item_id("nonsense") is None
    assert greader.parse_item_id("") is None


def test_streams_name_the_part_of_feedstash_they_mean():
    assert greader.normalize_stream("user/12345/label/Tech") == "user/-/label/Tech"
    assert greader.parse_stream("user/-/state/com.google/reading-list") == ("reading-list", None)
    assert greader.parse_stream("user/99/state/com.google/starred") == ("starred", None)
    assert greader.parse_stream("user/-/state/com.google/read") == ("read", None)
    assert greader.parse_stream("user/-/label/Deep Reads") == ("label", "Deep Reads")
    assert greader.parse_stream("feed/7") == ("feed", "7")
    assert greader.parse_stream("something/else") == ("unknown", None)
    assert greader.label_name("user/-/label/Tech") == "Tech"
    assert greader.label_name(greader.STARRED) is None
    assert greader.label_name(None) is None


def test_the_credential_in_the_authorization_header():
    assert greader.auth_token("GoogleLogin auth=abc123") == "abc123"
    assert greader.auth_token("googlelogin AUTH=abc123") == "abc123"
    assert greader.auth_token("Bearer abc123") == "abc123"
    assert greader.auth_token("GoogleLogin sid=abc123") is None
    assert greader.auth_token("Basic abc123") is None
    assert greader.auth_token("") is None
