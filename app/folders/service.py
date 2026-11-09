"""The rules around a folder write, and the guards that keep its link secret.

Every folder route that writes goes through `FolderService` (#153): creations spend the creation
limits, every other write spends the write limit. Writes stay in `app/folders/store.py`.

Environment: `KYD_FOLDERS_SECRET` (at least 32 bytes) keys the address hash and the note
confirmations; changing it voids unused confirmations and restarts the per-address counts.
Without it, notes answer 503 while saves and status changes are still counted, keyed per process.
"""

import hashlib
import hmac
import ipaddress
import logging
import os
import re
import secrets
from collections.abc import Awaitable, Callable, Generator, Mapping
from contextlib import contextmanager
from typing import cast

from pydantic import TypeAdapter, ValidationError
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.folders import pii
from app.folders.store import (
    CaseId,
    FolderId,
    FolderName,
    FolderStore,
    NoteText,
    RateRule,
    StoreConfigError,
    VisitorWrite,
)
from app.tools.matches import MatchReference
from etl.boundaries import Chamber

SECRET_ENV = "KYD_FOLDERS_SECRET"
MIN_SECRET_BYTES = 32
_PROCESS_RATE_KEY = secrets.token_bytes(MIN_SECRET_BYTES)
# A full note, every character four UTF-8 bytes percent-encoded, plus its form fields.
MAX_BODY_BYTES = 16 * 1024
CREATE_PER_IP = RateRule(scope="create:ip:", limit=10, window_seconds=60 * 60)
CREATE_GLOBAL = RateRule(scope="create:global", limit=200, window_seconds=60 * 60)
WRITE_PER_IP = RateRule(scope="write:ip:", limit=60, window_seconds=60)
PRIVATE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex",
}
UNKNOWN_CLIENT = "unknown"
FOLDER_ROUTE = re.compile(r"^/(?:f/|folders/?$)")
# `%s` in a format string is not a link, and redacting it would break the formatting.
FOLDER_LINK = re.compile(r"/f/(?!%[a-z(])[^/\s?#\"'<>]+")
BARE_FOLDER_ID = re.compile(r"\b[0-9a-f]{32}\b")
LOGGERS = ("", "uvicorn", "uvicorn.access", "uvicorn.error")

NOTE_TEXTS: TypeAdapter[str] = TypeAdapter(NoteText)
Network = ipaddress.IPv4Network | ipaddress.IPv6Network
Address = ipaddress.IPv4Address | ipaddress.IPv6Address


class NoteRefusedError(Exception):
    """The text is blank, longer than 1,000 characters, or holds control characters."""


class PiiBlockedError(Exception):
    """The text holds a personal detail. No confirmation lifts this."""

    def __init__(self, kinds: tuple[pii.Kind, ...]) -> None:
        super().__init__(f"Personal details are not kept here: {', '.join(kinds)}")
        self.kinds = kinds


class ConfirmationRequiredError(Exception):
    """No confirmation came with this exact text."""


def load_secret() -> bytes:
    secret = os.environ.get(SECRET_ENV, "").encode()
    if not secret:
        raise StoreConfigError(f"{SECRET_ENV} is not set")
    if len(secret) < MIN_SECRET_BYTES:
        raise StoreConfigError(f"{SECRET_ENV} must be at least {MIN_SECRET_BYTES} bytes")
    return secret


def rate_secret() -> bytes:
    """The key for the per-address counts: `KYD_FOLDERS_SECRET`, else this process's own key.

    Saves and status changes worked before they were throttled, with or without the secret, so
    a missing secret must not stop them. The fallback key is random and never stored: the counts
    restart with the process, and nothing that outlives it links a hash to an address. Note
    confirmations still need the real secret (`load_secret`).
    """
    try:
        return load_secret()
    except StoreConfigError:
        return _PROCESS_RATE_KEY


def _screen(text: str) -> None:
    try:
        NOTE_TEXTS.validate_python(text)
    except ValidationError:
        raise NoteRefusedError from None
    kinds = pii.find(text)
    if kinds:
        raise PiiBlockedError(kinds)


class FolderService:
    """Validation, confirmation and limits in front of the store, in that order."""

    def __init__(self, store: FolderStore, secret: bytes) -> None:
        self.store = store
        self._secret = secret

    def _for_address(self, rule: RateRule, ip: str) -> RateRule:
        digest = hmac.new(self._secret, ip.encode(), hashlib.sha256).hexdigest()
        return rule.model_copy(update={"scope": f"{rule.scope}{digest}"})

    def throttle_write(self, ip: str) -> None:
        self.store.spend_rate((self._for_address(WRITE_PER_IP, ip),))

    def _spend_create(self, ip: str) -> None:
        # The address rule comes first: one refused address never spends the shared budget.
        self.store.spend_rate((self._for_address(CREATE_PER_IP, ip), CREATE_GLOBAL))

    def create_folder(
        self, name: FolderName, case_id: CaseId, chamber: Chamber, district: int, ip: str
    ) -> str:
        self._spend_create(ip)
        return self.store.create_folder(name, case_id, chamber, district)

    def create_empty_folder(self, name: FolderName, ip: str) -> str:
        """The same creation limits as a folder that starts with a case."""
        self._spend_create(ip)
        return self.store.create_empty_folder(name)

    def create_match_folder(self, name: FolderName, reference: MatchReference, ip: str) -> str:
        """A new folder holding one validated match; the caller resolved the reference first."""
        folder_id = self.create_empty_folder(name, ip)
        self.store.save_match(folder_id, reference)
        return folder_id

    def confirmation(self, folder_id: FolderId, body: str) -> str:
        """What the office's confirm step sends back; blocked or invalid text never gets one."""
        _screen(body)
        return pii.confirmation_token(self._secret, folder_id, body)

    def _require_confirmed(self, folder_id: FolderId, body: str, given: str | None) -> None:
        _screen(body)
        if given is None or not pii.confirmation_matches(self._secret, folder_id, body, given):
            raise ConfirmationRequiredError

    @contextmanager
    def confirmed_write(
        self, folder_id: FolderId, body: str, confirmation: str | None, ip: str
    ) -> Generator[VisitorWrite]:
        """Confirm the original link and exact text before creating any private copy."""
        self._require_confirmed(folder_id, body, confirmation)
        self.throttle_write(ip)
        with self.store.visitor_write(folder_id) as write:
            yield write

    def add_note(
        self, folder_id: FolderId, card_id: int, body: str, confirmation: str | None, ip: str
    ) -> int:
        self._require_confirmed(folder_id, body, confirmation)
        self.throttle_write(ip)
        return self.store.add_note(folder_id, card_id, body, True)

    def edit_note(
        self, folder_id: FolderId, note_id: int, body: str, confirmation: str | None, ip: str
    ) -> None:
        self._require_confirmed(folder_id, body, confirmation)
        self.throttle_write(ip)
        self.store.edit_note(folder_id, note_id, body, True)

    def rotate_link(self, folder_id: FolderId, ip: str) -> str:
        self.throttle_write(ip)
        return self.store.rotate_link(folder_id)


def parse_trusted_proxies(text: str) -> tuple[Network, ...]:
    """Comma-separated networks; a bad entry raises, so a typo never trusts the wrong peer."""
    parts = (part.strip() for part in text.split(","))
    return tuple(ipaddress.ip_network(part, strict=False) for part in parts if part)


def _address(text: str) -> Address | None:
    try:
        address = ipaddress.ip_address(text.strip())
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def client_ip(scope: Scope, trusted: tuple[Network, ...]) -> str:
    """The address to count, walking `X-Forwarded-For` back only through trusted proxies.

    Hops are read from the right, the end our own proxies wrote; a client can only forge the
    left. An IPv6 client holds a whole /64, so that is what is counted.
    """
    client = cast(tuple[str, int] | None, scope.get("client"))
    current = _address(client[0]) if client else None
    if current is None:
        return UNKNOWN_CLIENT
    lines = Headers(scope=scope).getlist("x-forwarded-for")
    hops = [hop for line in lines for hop in line.split(",")]
    while hops and any(current in network for network in trusted):
        hop = _address(hops.pop())
        if hop is None:
            break
        current = hop
    if isinstance(current, ipaddress.IPv6Address):
        return str(ipaddress.ip_network(f"{current}/64", strict=False))
    return str(current)


async def _buffered(receive: Receive, limit: int) -> list[Message] | None:
    """The request's messages as sent, or None past `limit`; never holds more than that."""
    messages: list[Message] = []
    size = 0
    while True:
        message = await receive()
        messages.append(message)
        size += len(message.get("body", b""))
        if size > limit:
            return None
        if not message.get("more_body"):
            return messages


def _replay(messages: list[Message], receive: Receive) -> Callable[[], Awaitable[Message]]:
    pending = iter(messages)

    async def replayed() -> Message:
        return next(pending, None) or await receive()

    return replayed


class FolderHttpGuard:
    """ASGI wrapper for the folder routes: privacy headers on every answer and a body cap."""

    def __init__(self, app: ASGIApp, max_body_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not FOLDER_ROUTE.match(scope["path"]):
            await self.app(scope, receive, send)
            return

        async def private_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in PRIVATE_HEADERS.items():
                    headers[name] = value
            await send(message)

        messages = await _buffered(receive, self.max_body_bytes)
        if messages is None:
            refused = PlainTextResponse("Request body too large.", status_code=413)
            await refused(scope, receive, private_send)
            return
        await self.app(scope, _replay(messages, receive), private_send)


def redact(text: str) -> str:
    return BARE_FOLDER_ID.sub("[redacted]", FOLDER_LINK.sub("/f/[redacted]", text))


def _redacted_argument(value: object) -> object:
    """Numbers and clean values stay as they are: formats such as `%d` need them."""
    if value is None or isinstance(value, int | float):
        return value
    text = str(value)
    cleaned = redact(text)
    return value if cleaned == text else cleaned


class RedactFolderLinks(logging.Filter):
    """Takes folder links out of a record, keeping the argument shape Uvicorn's formatter reads."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        if isinstance(record.args, Mapping):
            record.args = {key: _redacted_argument(item) for key, item in record.args.items()}
        elif record.args:
            record.args = tuple(_redacted_argument(item) for item in record.args)
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        return True


_REDACTOR = RedactFolderLinks()


def install_log_redaction(names: tuple[str, ...] = LOGGERS) -> None:
    """Filter each logger and its handlers: a logger's own filter skips its children's records."""
    for name in names:
        logger = logging.getLogger(name)
        logger.addFilter(_REDACTOR)
        for handler in logger.handlers:
            handler.addFilter(_REDACTOR)
