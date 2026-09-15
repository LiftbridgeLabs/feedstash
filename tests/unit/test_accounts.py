import pytest

from app.db import Database
from app.db.repositories import items, users
from app.errors import Conflict, InvalidInput, NotFound
from app.images import ImageStore
from app.services import accounts
from support.images import PNG

PASSWORD = "correct horse"


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "feedstash.db")
    database.initialize()
    return database


def test_the_first_user_is_an_admin_and_new_sign_ins_can_link_by_email(conn):
    ann = users.upsert(conn, sub="google:1", email="Ann@Example.com", name="Ann", picture=None)
    bob = users.upsert(conn, sub="google:2", email="bob@example.com", name=None, picture=None)
    assert users.get(conn, ann).is_admin and not users.get(conn, bob).is_admin
    assert users.get(conn, ann).email == "ann@example.com"
    assert users.upsert(conn, sub="oidc:ann", email="ann@example.com", name=None, picture=None, link_by_email=True) == ann
    assert users.get(conn, ann).name == "Ann"  # a missing name doesn't wipe the one we had


def test_setup_works_once_and_passwords_are_checked(db):
    owner = accounts.setup_first_account(db, email=" Owner@Example.com ", name="Owner", password=PASSWORD)
    assert (owner.email, owner.is_admin, owner.has_password) == ("owner@example.com", True, True)
    with pytest.raises(Conflict):
        accounts.setup_first_account(db, email="other@example.com", name=None, password=PASSWORD)
    assert accounts.authenticate(db, "OWNER@example.com", PASSWORD).id == owner.id
    assert accounts.authenticate(db, "owner@example.com", "wrong horse") is None
    assert accounts.authenticate(db, "nobody@example.com", PASSWORD) is None


def test_admin_changes_keep_an_admin_and_removing_an_account_removes_its_images(db, tmp_path):
    owner = accounts.setup_first_account(db, email="owner@example.com", name=None, password=PASSWORD)
    kid = accounts.create_account(db, email="kid@example.com", name="Kid", password="kid password", is_admin=False)
    with pytest.raises(Conflict):
        accounts.create_account(db, email="KID@example.com", name=None, password="kid password", is_admin=False)
    with pytest.raises(InvalidInput):
        accounts.create_account(db, email="not-an-email", name=None, password="kid password", is_admin=False)
    with pytest.raises(InvalidInput):
        accounts.set_admin(db, owner.id, False)
    assert accounts.set_admin(db, kid.id, True).is_admin
    assert not accounts.set_admin(db, owner.id, False).is_admin  # fine now that someone else is an admin

    with pytest.raises(InvalidInput):
        accounts.change_own_password(db, kid, current_password="wrong", new_password="new kid password")
    accounts.change_own_password(db, kid, current_password="kid password", new_password="new kid password")
    assert accounts.authenticate(db, "kid@example.com", "new kid password")

    images = ImageStore(tmp_path / "uploads")
    image_name = images.save(PNG)
    with db.transaction() as conn:
        items.create(conn, kid.id, type="screenshot", title=None, content=None, url=None, image_name=image_name,
                     source="test", tags=[], now=1)
    with pytest.raises(InvalidInput):
        accounts.delete_account(db, images, acting_user_id=kid.id, user_id=kid.id)
    accounts.delete_account(db, images, acting_user_id=owner.id, user_id=kid.id)
    assert images.path(image_name) is None
    with pytest.raises(NotFound):
        accounts.delete_account(db, images, acting_user_id=owner.id, user_id=kid.id)


def test_accounts_that_sign_in_elsewhere_have_no_password_to_change(db):
    with db.transaction() as conn:
        user = users.get(conn, users.upsert(conn, sub="google:1", email="g@example.com", name=None, picture=None))
    with pytest.raises(InvalidInput, match="no password"):
        accounts.change_own_password(db, user, current_password="", new_password=PASSWORD)
