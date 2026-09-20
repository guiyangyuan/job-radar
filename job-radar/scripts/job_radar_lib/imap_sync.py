"""Read-only IMAP synchronization with minimized MIME extraction."""

from __future__ import annotations

import hashlib
import imaplib
import re
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email import policy
from email.header import decode_header
from email.parser import BytesHeaderParser, BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser
from typing import Callable, Mapping

from .email_models import validate_email_sync_state


MAX_MESSAGE_BYTES = 2 * 1024 * 1024
MAX_TEXT_CHARS = 100_000

IMAP_PROVIDER_PRESETS = {
    "qq": ("imap.qq.com", 993),
    "netease-163": ("imap.163.com", 993),
    "netease-126": ("imap.126.com", 993),
    "netease-yeah": ("imap.yeah.net", 993),
    "gmail": ("imap.gmail.com", 993),
    "tencent-enterprise": ("imap.exmail.qq.com", 993),
    "netease-enterprise": ("imap.qiye.163.com", 993),
    "aliyun-enterprise": ("imap.qiye.aliyun.com", 993),
}

AUTO_PROVIDER_BY_DOMAIN = {
    "qq.com": "qq",
    "163.com": "netease-163",
    "126.com": "netease-126",
    "yeah.net": "netease-yeah",
    "gmail.com": "gmail",
    "googlemail.com": "gmail",
}


class EmailSyncError(RuntimeError):
    """Safe, categorized email synchronization failure."""


@dataclass(frozen=True)
class ImapConfig:
    provider: str
    host: str
    port: int
    username: str = field(repr=False)
    app_password: str = field(repr=False)
    folder: str = "INBOX"

    @property
    def mailbox_hash(self) -> str:
        digest = hashlib.sha256(self.username.strip().lower().encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "ImapConfig":
        username = env.get("JOB_RADAR_IMAP_USERNAME", "").strip()
        password = env.get("JOB_RADAR_IMAP_APP_PASSWORD", "")
        if not username:
            raise EmailSyncError("JOB_RADAR_IMAP_USERNAME is not set")
        if not password:
            raise EmailSyncError("JOB_RADAR_IMAP_APP_PASSWORD is not set")
        provider = (
            env.get("JOB_RADAR_IMAP_PROVIDER", "auto").strip().lower() or "auto"
        )
        if provider == "auto":
            domain = username.rsplit("@", 1)[-1].lower() if "@" in username else ""
            provider = AUTO_PROVIDER_BY_DOMAIN.get(domain, "")
            if not provider:
                raise EmailSyncError(
                    "cannot auto-detect the IMAP provider; set "
                    "JOB_RADAR_IMAP_PROVIDER=custom and configure the IMAP host"
                )

        if provider in IMAP_PROVIDER_PRESETS:
            host, port = IMAP_PROVIDER_PRESETS[provider]
        elif provider == "custom":
            host = env.get("JOB_RADAR_IMAP_HOST", "").strip()
            if not host:
                raise EmailSyncError("JOB_RADAR_IMAP_HOST is not set")
            raw_port = env.get("JOB_RADAR_IMAP_PORT", "993").strip()
            try:
                port = int(raw_port)
            except ValueError as exc:
                raise EmailSyncError("JOB_RADAR_IMAP_PORT must be an integer") from exc
            if not 1 <= port <= 65535:
                raise EmailSyncError("JOB_RADAR_IMAP_PORT must be from 1 to 65535")
        else:
            allowed = ", ".join(["auto", *IMAP_PROVIDER_PRESETS, "custom"])
            raise EmailSyncError(
                f"JOB_RADAR_IMAP_PROVIDER must be one of: {allowed}"
            )
        folder = env.get("JOB_RADAR_IMAP_FOLDER", "INBOX").strip() or "INBOX"
        return cls(provider, host, port, username, password, folder)


@dataclass(frozen=True)
class FetchedMessage:
    uid_validity: int
    uid: int
    message_id: str | None
    received_at: str
    sender_domain: str | None
    subject: str
    text: str
    has_attachments: bool

    def __repr__(self) -> str:
        return (
            "FetchedMessage("
            f"uid_validity={self.uid_validity!r}, uid={self.uid!r}, "
            f"received_at={self.received_at!r}, sender_domain={self.sender_domain!r}, "
            f"subject={self.subject!r}, has_attachments={self.has_attachments!r})"
        )


@dataclass(frozen=True)
class FetchIssue:
    uid_validity: int
    uid: int
    message_id: str | None
    received_at: str | None
    sender_domain: str | None
    subject: str
    error_category: str


@dataclass(frozen=True)
class SyncBatch:
    messages: list[FetchedMessage]
    issues: list[FetchIssue]
    state: dict


class _VisibleHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self.hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth and data.strip():
            self.parts.append(data.strip())

    def text(self) -> str:
        return " ".join(self.parts)


def _decode_header(value: str | None) -> str:
    pieces: list[str] = []
    for payload, charset in decode_header(value or ""):
        if isinstance(payload, bytes):
            pieces.append(payload.decode(charset or "utf-8", errors="replace"))
        else:
            pieces.append(payload)
    return re.sub(r"\s+", " ", "".join(pieces)).strip()


def _sender_domain(value: str | None) -> str | None:
    address = parseaddr(value or "")[1].strip().lower()
    if "@" not in address:
        return None
    domain = address.rsplit("@", 1)[1]
    return domain or None


def _received_at(value: str | None, fallback: datetime | None = None) -> str:
    try:
        parsed = parsedate_to_datetime(value or "")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.isoformat()
    except (TypeError, ValueError):
        return (fallback or datetime.now(timezone.utc)).isoformat()


def _decode_part(part) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        raw = part.get_payload()
        return raw if isinstance(raw, str) else ""
    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")


def parse_message(
    uid_validity: int,
    uid: int,
    raw: bytes,
    fallback_received_at: datetime | None = None,
) -> FetchedMessage:
    if len(raw) > MAX_MESSAGE_BYTES:
        raise ValueError("message_too_large")
    parsed = BytesParser(policy=policy.default).parsebytes(raw)
    plain: list[str] = []
    html: list[str] = []
    has_attachments = False
    for part in parsed.walk():
        if part.is_multipart():
            continue
        disposition = part.get_content_disposition()
        if disposition == "attachment" or part.get_filename():
            has_attachments = True
            continue
        content_type = part.get_content_type()
        if content_type == "text/plain":
            plain.append(_decode_part(part))
        elif content_type == "text/html":
            parser = _VisibleHTML()
            parser.feed(_decode_part(part))
            html.append(parser.text())
    text = "\n".join(plain if plain else html)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n+ *", "\n", text).strip()[:MAX_TEXT_CHARS]
    return FetchedMessage(
        uid_validity=uid_validity,
        uid=uid,
        message_id=_decode_header(parsed.get("Message-ID")) or None,
        received_at=_received_at(parsed.get("Date"), fallback_received_at),
        sender_domain=_sender_domain(parsed.get("From")),
        subject=_decode_header(parsed.get("Subject")),
        text=text,
        has_attachments=has_attachments,
    )


def _safe_issue(uid_validity: int, uid: int, raw: bytes, category: str) -> FetchIssue:
    try:
        headers = BytesHeaderParser(policy=policy.default).parsebytes(raw[:65_536])
        return FetchIssue(
            uid_validity=uid_validity,
            uid=uid,
            message_id=_decode_header(headers.get("Message-ID")) or None,
            received_at=_received_at(headers.get("Date")) if headers.get("Date") else None,
            sender_domain=_sender_domain(headers.get("From")),
            subject=_decode_header(headers.get("Subject")),
            error_category=category,
        )
    except Exception:
        return FetchIssue(uid_validity, uid, None, None, None, "", category)


def _open(config: ImapConfig, client_factory: Callable):
    try:
        context = ssl.create_default_context()
        client = client_factory(config.host, config.port, ssl_context=context)
        status, _data = client.login(config.username, config.app_password)
        if status != "OK":
            raise EmailSyncError("IMAP authentication failed")
        status, _data = client.select(config.folder, readonly=True)
        if status != "OK":
            raise EmailSyncError("IMAP folder selection failed")
        return client
    except EmailSyncError:
        raise
    except (imaplib.IMAP4.error, OSError, ssl.SSLError) as exc:
        raise EmailSyncError("IMAP connection or authentication failed") from exc


def _uid_validity(client) -> int:
    try:
        _name, values = client.response("UIDVALIDITY")
        return int(values[0])
    except (AttributeError, IndexError, TypeError, ValueError) as exc:
        raise EmailSyncError("IMAP UIDVALIDITY is unavailable") from exc


def _logout(client) -> None:
    try:
        client.logout()
    except Exception:
        pass


def test_connection(
    config: ImapConfig,
    client_factory: Callable = imaplib.IMAP4_SSL,
) -> dict:
    client = _open(config, client_factory)
    try:
        validity = _uid_validity(client)
        return {
            "connected": True,
            "provider": config.provider,
            "host": config.host,
            "folder": config.folder,
            "readonly": True,
            "uidValidity": validity,
        }
    finally:
        _logout(client)


def sync_messages(
    config: ImapConfig,
    state: dict,
    now: datetime,
    days: int = 60,
    client_factory: Callable = imaplib.IMAP4_SSL,
) -> SyncBatch:
    current = validate_email_sync_state(state)
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 3650:
        raise EmailSyncError("days must be an integer from 1 to 3650")
    client = _open(config, client_factory)
    try:
        validity = _uid_validity(client)
        if current.get("uidValidity") == validity and current.get("lastSeenUid") is not None:
            criterion = f"UID {current['lastSeenUid'] + 1}:*"
        else:
            criterion = f"SINCE {(now - timedelta(days=days)).strftime('%d-%b-%Y')}"
        status, values = client.uid("search", None, criterion)
        if status != "OK":
            raise EmailSyncError("IMAP search failed")
        raw_uids = values[0].split() if values and values[0] else []
        uids = [int(raw_uid) for raw_uid in raw_uids]
        messages: list[FetchedMessage] = []
        issues: list[FetchIssue] = []
        for uid in uids:
            status, parts = client.uid(
                "fetch", uid, "(BODY.PEEK[] FLAGS INTERNALDATE)"
            )
            if status != "OK":
                raise EmailSyncError("IMAP message fetch failed")
            raw = next(
                (
                    item[1]
                    for item in parts
                    if isinstance(item, tuple)
                    and len(item) >= 2
                    and isinstance(item[1], bytes)
                ),
                None,
            )
            if raw is None:
                raise EmailSyncError("IMAP message fetch returned no body")
            try:
                messages.append(parse_message(validity, uid, raw, now))
            except Exception as exc:
                category = (
                    "message_too_large"
                    if len(raw) > MAX_MESSAGE_BYTES or str(exc) == "message_too_large"
                    else "mime_parse_error"
                )
                issues.append(_safe_issue(validity, uid, raw, category))
        updated = dict(current)
        updated.update(
            {
                "provider": config.provider,
                "mailboxHash": config.mailbox_hash,
                "folder": config.folder,
                "initialWindowDays": days,
                "uidValidity": validity,
                "lastSeenUid": max(uids) if uids else current.get("lastSeenUid"),
                "lastSyncedAt": now.isoformat(),
            }
        )
        if current.get("uidValidity") != validity and not uids:
            updated["lastSeenUid"] = None
        return SyncBatch(messages, issues, validate_email_sync_state(updated))
    except EmailSyncError:
        raise
    except (imaplib.IMAP4.error, OSError, ValueError) as exc:
        raise EmailSyncError("IMAP synchronization failed") from exc
    finally:
        _logout(client)
