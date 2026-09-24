"""Admin commands, meant to be run inside the container:

    docker exec -it feedstash python -m app.cli create-account --email you@example.com --admin
    docker exec -it feedstash python -m app.cli set-password --email you@example.com
    docker exec feedstash python -m app.cli list-accounts
    docker exec feedstash python -m app.cli backup /data/backups/feedstash.db
"""

import argparse
import getpass
import os
import sqlite3
import sys
from pathlib import Path

from app.db import Database
from app.db.repositories import users as users_repo
from app.errors import ReaderError
from app.services import accounts
from app.settings import Settings


def _drop_root() -> None:
    """`docker exec` runs as root; anything it writes next to the database must stay usable by the app's user."""
    if hasattr(os, "geteuid") and os.geteuid() == 0 and os.environ.get("PUID"):
        os.setgroups([])
        os.setgid(int(os.environ.get("PGID") or os.environ["PUID"]))
        os.setuid(int(os.environ["PUID"]))


def _read_password(args: argparse.Namespace) -> str:
    if args.password_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    password = getpass.getpass("New password: ")
    if password != getpass.getpass("Repeat it: "):
        raise ReaderError("The passwords didn't match")
    return password


def _backup(source: Path, destination: Path) -> None:
    """Copies the database with SQLite's backup API, which is safe while the server is writing to it.

    `docker exec` runs this as root, so the copy (and any folder made for it) is handed to whoever owns the data
    folder; otherwise the server and the NAS user (PUID) couldn't read or clean up their own backups."""
    if destination.exists():
        raise ReaderError(f"{destination} already exists")
    made = [parent for parent in reversed(destination.parents) if not parent.exists()]
    destination.parent.mkdir(parents=True, exist_ok=True)
    src, dst = sqlite3.connect(source), sqlite3.connect(destination)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        owner = source.resolve().parent.stat()
        for path in [*made, destination]:
            os.chown(path, owner.st_uid, owner.st_gid)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="FeedStash admin commands")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-account", help="create an account that signs in with a password")
    create.add_argument("--email", required=True)
    create.add_argument("--name")
    create.add_argument("--admin", action="store_true", help="let the account manage other accounts")
    create.add_argument("--password-stdin", action="store_true", help="read the password from standard input")
    reset = commands.add_parser("set-password", help="set or reset an account's password")
    reset.add_argument("--email", required=True)
    reset.add_argument("--password-stdin", action="store_true", help="read the password from standard input")
    commands.add_parser("list-accounts", help="list everyone who can sign in")
    backup = commands.add_parser("backup", help="copy the database to a new file, safely, while the server runs")
    backup.add_argument("destination", type=Path)
    args = parser.parse_args(argv)

    _drop_root()
    settings = Settings()
    db = Database(settings.database_path)
    db.initialize()
    try:
        if args.command == "create-account":
            user = accounts.create_account(
                db, email=args.email, name=args.name, password=_read_password(args), is_admin=args.admin
            )
            print(f"Created {user.email}{' (admin)' if user.is_admin else ''}.")
        elif args.command == "set-password":
            with db.transaction() as conn:
                user = users_repo.find_by_email(conn, args.email)
            if user is None:
                raise ReaderError(f"No account with the email {args.email}")
            accounts.reset_password(db, user.id, _read_password(args))
            print(f"Set a new password for {user.email}.")
        elif args.command == "list-accounts":
            with db.transaction() as conn:
                for user in users_repo.list_all(conn):
                    how = "password" if user.has_password else user.sub.split(":", 1)[0]
                    print(f"{user.email:40} {how:10} {'admin' if user.is_admin else ''}")
        elif args.command == "backup":
            _backup(settings.database_path, args.destination)
            print(f"Backed up the database to {args.destination}. Uploaded images are in {settings.uploads_dir}.")
    except ReaderError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
