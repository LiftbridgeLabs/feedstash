"""Request and response shapes of the JSON API."""

from dataclasses import asdict, is_dataclass
from typing import Literal, TypeVar

from pydantic import BaseModel, Field

from app.clock import iso
from app.db.models import ApiToken, MailAccount, PagePreview, ScopeKind, SmartList, StashItem, StashRule, User


# ------------------------------------------------------------------ responses


class OkOut(BaseModel):
    ok: bool = True


class ReleaseSectionOut(BaseModel):
    title: str
    items: list[str]


class ReleaseNotesOut(BaseModel):
    version: str
    url: str
    sections: list[ReleaseSectionOut]


class LogSettingsIn(BaseModel):
    level: Literal["info", "debug"]
    requests: Literal["all", "changes", "errors", "none"]
    keep_files: int = Field(ge=1, le=20)
    max_mb: int = Field(ge=1, le=100)


class LogSettingsOut(LogSettingsIn):
    directory: str  # where the files are, inside the container


class LogLinesOut(BaseModel):
    lines: list[str]  # the newest last


class SignInProviderIn(BaseModel):
    kind: Literal["google", "oidc"]
    name: str = Field(default="", max_length=60)  # the button: "Sign in with <name>"; Google is always "Google"
    issuer: str = Field(default="", max_length=500)  # OIDC only
    client_id: str = Field(min_length=1, max_length=500)
    client_secret: str = Field(min_length=1, max_length=2000)
    scopes: str = Field(default="openid email profile", max_length=300)
    icon: str = Field(default="key", max_length=500)  # key, shield, lock, none, or an image's address
    color: str = Field(default="", max_length=7)  # #rrggbb, or empty for the theme's


class SignInProviderPatch(BaseModel):
    name: str | None = Field(default=None, max_length=60)
    issuer: str | None = Field(default=None, max_length=500)
    client_id: str | None = Field(default=None, min_length=1, max_length=500)
    client_secret: str | None = Field(default=None, max_length=2000)  # empty or left out keeps the saved one
    scopes: str | None = Field(default=None, max_length=300)
    icon: str | None = Field(default=None, max_length=500)
    color: str | None = Field(default=None, max_length=7)
    enabled: bool | None = None


class SignInSwitchIn(BaseModel):
    enabled: bool


class SignInProviderOut(BaseModel):
    id: int | None  # None for the ones set in the server's settings, which can only be turned off or on here
    key: str  # in its sign-in address, /auth/login/<key>
    kind: str
    name: str
    issuer: str
    client_id: str
    scopes: str
    icon: str
    color: str
    enabled: bool
    from_server_settings: bool
    secret_unreadable: bool = False  # saved with a different SECRET_KEY: the secret has to be entered again
    callback_urls: list[str]  # the redirect URIs to enter at the provider, one per address in BASE_URL


class SignInOut(BaseModel):
    sso_enabled: bool  # the switch for every Google and OIDC button at once
    providers: list[SignInProviderOut]
    callback_urls: list[str]  # for a provider added here, before it's saved
    allowed_emails: list[str]  # the allowed list kept here
    allowed_domains: list[str]
    server_allowed_emails: list[str]  # ALLOWED_EMAILS / ALLOWED_DOMAINS from the server's settings, read-only
    server_allowed_domains: list[str]
    password_login: bool


class AllowedListIn(BaseModel):
    emails: list[str] = Field(default_factory=list, max_length=500)
    domains: list[str] = Field(default_factory=list, max_length=200)


class UpdatesOut(BaseModel):
    current: str
    latest: str | None  # set only when it's newer than the running release
    latest_url: str | None
    releases_url: str
    unseen: list[ReleaseNotesOut]  # releases up to the running one whose notes this admin hasn't seen, newest first


class UserOut(BaseModel):
    id: int
    email: str
    name: str | None
    picture: str | None
    is_admin: bool
    has_password: bool
    read_retention_days: int
    sections: Literal["both", "feeds", "stash"] = "both"  # which halves of the app this person uses


class AccountPrefsIn(BaseModel):
    read_retention_days: int | None = Field(default=None, ge=0, le=3650)  # 0: only the server's own cleanup
    sections: Literal["both", "feeds", "stash"] | None = None


class AccountOut(BaseModel):
    id: int
    email: str
    name: str | None
    is_admin: bool
    has_password: bool
    sign_in: str  # how the account first signed in: password, google, oidc or dev
    created_at: int

    @classmethod
    def from_user(cls, user: User) -> "AccountOut":
        provider = user.sub.split(":", 1)[0] if ":" in user.sub else "dev"
        return cls(
            id=user.id, email=user.email, name=user.name, is_admin=user.is_admin, has_password=user.has_password,
            sign_in="password" if provider == "local" else provider, created_at=user.created_at,
        )


class FolderOut(BaseModel):
    id: int
    name: str
    position: int


class FeedOut(BaseModel):
    id: int
    folder_id: int | None
    title: str
    position: int
    url: str
    site_url: str | None
    last_fetched_at: int | None
    last_error: str | None
    unread: int
    auto_stash: bool = False  # new articles go straight to the stash
    full_text: bool = False  # new articles get their full page fetched


class TreeOut(BaseModel):
    folders: list[FolderOut]
    feeds: list[FeedOut]
    starred_count: int
    refresh_interval_minutes: int
    version: str  # the server's release, e.g. "0.1.4", or "dev"
    page_capture: bool  # whether saved links get previews and readable copies


class ArticleSummaryOut(BaseModel):
    id: int
    feed_id: int
    title: str
    url: str | None
    author: str | None
    summary: str | None
    image: str | None
    published_at: int
    read: bool
    starred: bool
    feed_title: str
    site_url: str | None


class ArticleOut(ArticleSummaryOut):
    content: str | None
    full_content: str | None = None  # the article's own page, extracted, once fetched (see /full-text)


class FullTextOut(BaseModel):
    """An article's full text: status is ready (with content) or failed (with an error written for the reader)."""

    status: Literal["ready", "failed"]
    content: str | None
    error: str | None


class ArticlePageOut(BaseModel):
    articles: list[ArticleSummaryOut]
    next_cursor: str | None
    max_id: int


class CountOut(BaseModel):
    count: int


class ArticleIdsOut(BaseModel):
    """Ids only: what a syncing client diffs against its own copy before asking for anything."""

    ids: list[int]
    max_id: int  # the newest id in this scope, to pass back as since_id next time


class UpdatedOut(BaseModel):
    updated: int


class StarredOut(BaseModel):
    starred: bool


class MarkedOut(BaseModel):
    marked: int
    batch: int


class RestoredOut(BaseModel):
    restored: int


class FolderOrderOut(BaseModel):
    ids: list[int]


class FeedOrderOut(BaseModel):
    folder_id: int | None
    ids: list[int]


class RefreshOut(BaseModel):
    feeds: int
    new: int


class ImportOut(BaseModel):
    added: int
    skipped: int
    folders_created: int


Out = TypeVar("Out", bound=BaseModel)


def to_schema(schema: type[Out], value) -> Out:
    """Builds a response model from a repository dataclass (nested dataclasses included)."""
    return schema.model_validate(asdict(value) if is_dataclass(value) else value)


# ------------------------------------------------------------------ requests


class PasswordLoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)


class AccountFields(BaseModel):
    email: str = Field(max_length=320)
    name: str | None = Field(default=None, max_length=100)
    password: str = Field(max_length=1024)


class SetupIn(AccountFields):
    setup_token: str | None = Field(default=None, max_length=1024)  # needed only when setting up from outside


class NewAccountIn(AccountFields):
    is_admin: bool = False


class AccountUpdateIn(BaseModel):
    password: str | None = Field(default=None, max_length=1024)
    is_admin: bool | None = None


class PasswordChangeIn(BaseModel):
    current_password: str = Field(default="", max_length=1024)
    new_password: str = Field(max_length=1024)


class ImportedLinkIn(BaseModel):
    url: str = Field(max_length=8000)
    title: str | None = Field(default=None, max_length=5000)
    saved_at: int | None = None  # Unix seconds
    tags: list[str] = Field(default_factory=list, max_length=20)
    reviewed: bool = False
    archived: bool = False


class ImportLinksIn(BaseModel):
    links: list[ImportedLinkIn] = Field(max_length=2000)


class ImportLinksOut(BaseModel):
    added: int
    already_saved: int
    invalid: int


class MarkArticlesIn(BaseModel):
    ids: list[int] = Field(max_length=2000)
    read: bool = True


class StarArticlesIn(BaseModel):
    ids: list[int] = Field(max_length=2000)
    starred: bool = True


class ArticleIdsIn(BaseModel):
    ids: list[int] = Field(max_length=1000)  # one bulk fetch; clients page through in chunks this size


class StarIn(BaseModel):
    starred: bool


class MarkScopeIn(BaseModel):
    scope: ScopeKind
    id: int | None = None
    older_than_hours: float | None = Field(default=None, gt=0, le=24 * 365 * 100, allow_inf_nan=False)
    max_id: int | None = None


class UndoMarkIn(BaseModel):
    scope: ScopeKind
    id: int | None = None
    batch: int


class FolderIn(BaseModel):
    name: str


class ReorderIn(BaseModel):
    ids: list[int] = Field(max_length=5000)


class FeedReorderIn(ReorderIn):
    folder_id: int | None = None


class FollowIn(BaseModel):
    url: str
    folder_id: int | None = None
    folder_name: str | None = None
    title: str | None = None


class FeedUpdateIn(BaseModel):
    """Only fields present in the request are changed; `"folder_id": null` means Uncategorized."""

    title: str | None = None
    folder_id: int | None = None
    url: str | None = Field(default=None, max_length=4000)  # the feed's new address; fetched before it's accepted
    auto_stash: bool | None = None  # send new articles straight to the stash
    full_text: bool | None = None  # fetch each new article's full page


class RefreshIn(BaseModel):
    scope: ScopeKind = "all"
    id: int | None = None


# ------------------------------------------------------------------ stash and API tokens
# Field names are camelCase: the browser extension, email worker and phone apps in clients/ decode these shapes.


class LinkOut(BaseModel):
    id: int
    url: str
    label: str | None


class PagePreviewOut(BaseModel):
    status: str  # pending | working | ready | failed | skipped
    title: str | None
    description: str | None
    image: str | None
    siteName: str | None
    hasCopy: bool  # a readable copy is saved (GET /api/items/{id}/page)
    fetchedAt: str | None
    error: str | None

    @classmethod
    def from_preview(cls, page: PagePreview) -> "PagePreviewOut":
        return cls(
            status=page.status, title=page.title, description=page.description, image=page.image_url,
            siteName=page.site_name, hasCopy=page.has_copy, fetchedAt=iso(page.fetched_at) if page.fetched_at else None,
            error=page.error,
        )


class PageCopyOut(BaseModel):
    url: str
    status: str
    title: str | None
    html: str | None
    fetchedAt: str | None
    error: str | None


class StashItemOut(BaseModel):
    id: int
    type: str
    title: str | None
    content: str | None
    url: str | None  # mirrors links[0], for clients that only know one url
    imagePath: str | None  # the first of `images`, for clients that only show one
    images: list[str] = []
    source: str
    reviewed: bool
    archived: bool
    createdAt: str
    updatedAt: str
    tags: list[str]
    links: list[LinkOut]
    preview: PagePreviewOut | None = None  # the web page behind `url`, once FeedStash has looked at it
    folderId: int | None = None  # the stash folder it's in
    feedId: int | None = None  # the feed it was saved from

    @classmethod
    def from_item(cls, item: StashItem) -> "StashItemOut":
        return cls(
            id=item.id, type=item.type, title=item.title, content=item.content, url=item.url,
            imagePath=f"/uploads/{item.image_name}" if item.image_name else None,
            images=[f"/uploads/{name}" for name in item.image_names], source=item.source,
            reviewed=item.reviewed, archived=item.archived, createdAt=iso(item.created_at),
            updatedAt=iso(item.updated_at), tags=item.tags,
            links=[LinkOut(id=link.id, url=link.url, label=link.label) for link in item.links],
            preview=PagePreviewOut.from_preview(item.page) if item.page else None,
            folderId=item.folder_id, feedId=item.feed_id,
        )


class StashFolderOut(BaseModel):
    id: int
    name: str
    position: int
    count: int  # items in it that aren't archived


class StashFolderIn(BaseModel):
    name: str = Field(max_length=1000)


class SmartListOut(BaseModel):
    id: int
    name: str
    position: int
    query: str | None
    type: str | None
    tag: str | None
    folderId: int | None

    @classmethod
    def from_list(cls, smart_list: SmartList) -> "SmartListOut":
        return cls(
            id=smart_list.id, name=smart_list.name, position=smart_list.position, query=smart_list.query,
            type=smart_list.type, tag=smart_list.tag, folderId=smart_list.folder_id,
        )


class SmartListIn(BaseModel):
    """On PATCH, only the fields sent are changed."""

    name: str | None = Field(default=None, max_length=1000)
    query: str | None = Field(default=None, max_length=500)  # the repository keeps no more than this
    type: str | None = None
    tag: str | None = Field(default=None, max_length=200)
    folderId: int | None = None


class StashRuleOut(BaseModel):
    id: int
    field: str  # domain | url | title | text | feed | type
    value: str
    addTag: str | None
    folderId: int | None
    markReviewed: bool
    archive: bool

    @classmethod
    def from_rule(cls, rule: StashRule) -> "StashRuleOut":
        return cls(
            id=rule.id, field=rule.field, value=rule.value, addTag=rule.add_tag, folderId=rule.folder_id,
            markReviewed=rule.mark_reviewed, archive=rule.archive,
        )


class StashRuleIn(BaseModel):
    field: str
    value: str | int
    addTag: str | None = Field(default=None, max_length=200)
    folderId: int | None = None
    markReviewed: bool = False
    archive: bool = False


class ChangedOut(BaseModel):
    changed: int


class TagCountOut(BaseModel):
    name: str
    count: int


class TagRenameIn(BaseModel):
    name: str = Field(max_length=200)
    newName: str = Field(max_length=200)


class TagMergeIn(BaseModel):
    names: list[str] = Field(min_length=1, max_length=500)
    into: str = Field(max_length=200)


class TagMergeOut(BaseModel):
    name: str  # the tag they became
    items: int  # how many items carry the tag afterwards
    merged: int  # how many tags were folded into it


class TagRenameOut(BaseModel):
    name: str  # the tag's name now
    items: int  # how many items were changed
    merged: bool  # True when the new name was already a tag, so the two became one


class StashSummaryOut(BaseModel):
    inbox: int
    total: int
    archived: int
    by_type: dict[str, int]
    folders: list[StashFolderOut] = Field(default_factory=list)
    lists: list[SmartListOut] = Field(default_factory=list)  # smart lists


class StashArticleOut(BaseModel):
    item: StashItemOut
    created: bool


class MailOut(BaseModel):
    """The connected mailbox. The password is never sent back."""

    connected: bool
    host: str = ""
    port: int = 993
    username: str = ""
    folder: str = "INBOX"
    allowedSenders: list[str] = Field(default_factory=list)
    enabled: bool = True
    lastCheckedAt: str | None = None
    lastError: str | None = None
    savedCount: int = 0
    pollMinutes: int = 5

    @classmethod
    def from_account(cls, account: MailAccount | None, *, poll_minutes: int) -> "MailOut":
        if account is None:
            return cls(connected=False, pollMinutes=poll_minutes)
        return cls(
            connected=True, host=account.host, port=account.port, username=account.username, folder=account.folder,
            allowedSenders=account.allowed_senders, enabled=account.enabled,
            lastCheckedAt=iso(account.last_checked_at) if account.last_checked_at else None,
            lastError=account.last_error, savedCount=account.saved_count, pollMinutes=poll_minutes,
        )


class MailIn(BaseModel):
    host: str = Field(max_length=255)
    username: str = Field(max_length=320)
    password: str = Field(default="", max_length=1024)  # empty keeps the saved one
    port: int = Field(default=993, ge=1, le=65535)
    folder: str = Field(default="INBOX", max_length=255)
    allowedSenders: list[str] = Field(default_factory=list, max_length=50)
    enabled: bool = True


class MailTestOut(BaseModel):
    ok: bool
    error: str | None


class MailCheckOut(BaseModel):
    saved: int
    error: str | None


class TokenOut(BaseModel):
    id: int
    clientName: str
    tokenPreview: str
    createdAt: str
    lastUsedAt: str | None

    @classmethod
    def from_token(cls, token: ApiToken) -> "TokenOut":
        return cls(
            id=token.id, clientName=token.client_name, tokenPreview=f"...{token.hint}",
            createdAt=iso(token.created_at), lastUsedAt=iso(token.last_used_at) if token.last_used_at else None,
        )


class NewTokenIn(BaseModel):
    clientName: str


class NewTokenOut(BaseModel):
    id: int
    token: str
    clientName: str


class ConnectCodeIn(BaseModel):
    clientName: str = Field(default="Phone or iPad", max_length=100)


class ConnectCode(BaseModel):
    server: str  # the address the app will use
    url: str  # <server>/connect#server=…&token=…, what the QR code holds
    svg: str  # the QR code


class ConnectCodeOut(NewTokenOut):
    codes: list[ConnectCode]  # one per configured address, the one this browser uses first
