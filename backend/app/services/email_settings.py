"""
E-mail (SMTP) settings saved by administrators, and the settings actually in use.

Generic SMTP for any provider (Gmail / Google Workspace, Microsoft 365, Yahoo, Zoho, cPanel webmail,
a company mail server...): host, port, security (starttls / ssl / none), optional user name and
password, sender address and name, optional Reply-To. There is no provider-specific code: whatever
the provider, only these values decide how mail is sent (services/email.py).

Which settings are used, decided at every send (no restart, no cache):
  1. settings saved by an administrator (the `settings` collection, _id "email_smtp"), even when
     switched off: then no e-mail is sent;
  2. otherwise the server environment (CG_SMTP_*), as before;
  3. otherwise e-mail is off.
Deleting the saved settings returns to 2.

The SMTP password is encrypted (core/secrets.py, AES-256-GCM, key CG_SECRETS_KEY) with the document
id as associated data. It is never returned, logged or audited; the API only says whether one is
saved. Changing where it is sent (host, port, security or user name) requires entering it again.

Outbound connections: only an administrator can set the host or send a test e-mail; viewing the
settings never connects anywhere; the connection is SMTP only (smtplib), with the configured timeout
and certificate checks. Private addresses are allowed on purpose: company mail servers are often
internal.
"""
import asyncio
import logging
from datetime import UTC, datetime
from email.utils import formataddr

from pydantic import SecretStr
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase

from app.core import secrets
from app.core.config import Settings
from app.core.errors import AppError
from app.db.transactions import run_in_transaction
from app.services import audit
from app.services import email as email_svc
from app.services.audit import AuditAction, actor_from_user
from app.services.auth import AuthContext, RequestMeta

log = logging.getLogger(__name__)

DOC_ID = "email_smtp"
FIELDS = ("enabled", "smtp_host", "smtp_port", "security", "username", "from_email", "from_name", "reply_to")
# Fields that decide where the saved password is sent: changing one needs the password again.
DESTINATION_FIELDS = ("smtp_host", "smtp_port", "security", "username")

KEY_MISSING = AppError(503, "secrets_key_missing",
                       "SMTP passwords cannot be saved: the server has no CG_SECRETS_KEY. Ask the administrator.")
NOT_SAVED = AppError(404, "email_settings_not_saved", "No e-mail settings are saved.")
BUSY = AppError(409, "email_test_running", "A test e-mail is already being sent. Wait for it to finish.")

_testing = asyncio.Lock()


class SmtpUnusable(Exception):
    """The saved settings cannot be used now; `reason` is a key of email.REASON_MESSAGES."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def password_status(doc: dict, settings: Settings) -> str:
    """NOT_SET, SAVED, or UNREADABLE (encrypted with another key, or no key on the server now)."""
    sealed = doc.get("password")
    if not sealed:
        return "NOT_SET"
    key = settings.secrets_key_bytes
    return "SAVED" if key and sealed.get("kid") == secrets.key_id(key) else "UNREADABLE"


async def saved(db: AsyncDatabase, session: AsyncClientSession | None = None) -> dict | None:
    return await db.settings.find_one({"_id": DOC_ID}, session=session)


async def active(db: AsyncDatabase, settings: Settings, session: AsyncClientSession | None = None) -> bool:
    """Whether e-mail is switched on (decides if a host e-mail is queued). Never contacts a server."""
    doc = await saved(db, session)
    return bool(doc["enabled"]) if doc is not None else settings.email_enabled


async def effective(db: AsyncDatabase, settings: Settings) -> email_svc.SmtpConfig | None:
    """The SMTP settings to send with now, with the password decrypted in memory only; None when
    e-mail is off. Raises SmtpUnusable when the saved password cannot be read."""
    doc = await saved(db)
    if doc is None:
        return email_svc.config_from_environment(settings)
    if not doc["enabled"]:
        return None
    password = None
    if doc.get("username"):
        key = settings.secrets_key_bytes
        try:
            if key is None:
                raise secrets.SecretUnreadable(other_key=True)
            password = SecretStr(secrets.decrypt(key, doc.get("password"), DOC_ID))
        except secrets.SecretUnreadable:
            raise SmtpUnusable("EMAIL_CREDENTIALS_UNREADABLE") from None
    sender = formataddr((doc["from_name"], doc["from_email"])) if doc.get("from_name") else doc["from_email"]
    return email_svc.SmtpConfig(host=doc["smtp_host"], port=doc["smtp_port"], security=doc["security"],
                                username=doc.get("username"), password=password, sender=sender,
                                reply_to=doc.get("reply_to"), timeout_seconds=settings.smtp_timeout_seconds,
                                source="database")


def source(doc: dict | None, settings: Settings) -> str:
    """Where the settings in use come from: database, environment or none."""
    if doc is not None:
        return "database"
    return "environment" if settings.email_enabled else "none"


# ---------------------------------------------------------------- administrators
async def save(db: AsyncDatabase, settings: Settings, ctx: AuthContext, meta: RequestMeta, data: dict,
               password: SecretStr | None) -> dict:
    """Creates or replaces the saved settings. `password` None keeps the saved one."""
    current = await saved(db)
    values = {k: data.get(k) for k in FIELDS}
    new_password = password.get_secret_value() if password is not None else None

    if settings.environment == "production" and values["username"] and values["security"] == "none":
        raise AppError(422, "invalid_email_settings",
                       "Security 'none' would send the SMTP password unencrypted: use STARTTLS or SSL/TLS.")
    if not values["username"]:
        if new_password is not None:
            raise AppError(422, "invalid_email_settings", "Enter the user name that goes with the password.")
    elif new_password is None:
        if current is None or not current.get("password"):
            raise AppError(422, "email_password_required", "Enter the SMTP password.")
        if any(values[k] != current.get(k) for k in DESTINATION_FIELDS):
            raise AppError(422, "email_password_required",
                           "Enter the SMTP password again when changing the host, port, security or user name.")

    fields = dict(values)
    unset: dict = {}
    if new_password is not None:
        key = settings.secrets_key_bytes
        if key is None:
            raise KEY_MISSING
        fields["password"] = secrets.encrypt(key, new_password, DOC_ID)
    elif not values["username"] and current is not None and current.get("password"):
        unset["password"] = ""                            # no login any more: the password goes too
    changed = {k for k in values if current is None or current.get(k) != values[k]}
    if current is not None and not changed and new_password is None and not unset:
        return current                                    # nothing to save
    now = datetime.now(UTC)

    async def work(s: AsyncClientSession):
        update = {"$set": {**fields, "updated_at": now, "updated_by": ctx.user["_id"]},
                  "$setOnInsert": {"created_at": now}}
        if unset:
            update["$unset"] = unset
        await db.settings.update_one({"_id": DOC_ID}, update, upsert=True, session=s)
        diff: dict = {k: {"from": current.get(k) if current else None, "to": values[k]} for k in sorted(changed)}
        if new_password is not None:
            diff["password"] = "changed"  # noqa: S105 - the fact only, never the value
        elif unset:
            diff["password"] = "removed"  # noqa: S105 - the fact only, never the value
        await audit.record(db, AuditAction.EMAIL_SETTINGS_UPDATED, actor=actor_from_user(ctx.user), ip=meta.ip,
                           resource_type="settings", resource_id=DOC_ID, changes=diff or None,
                           metadata={"created": current is None}, session=s)

    await run_in_transaction(db, work)
    return await saved(db)


async def remove(db: AsyncDatabase, ctx: AuthContext, meta: RequestMeta) -> None:
    """Deletes the saved settings, password included: the server environment applies again."""
    async def work(s: AsyncClientSession):
        if (await db.settings.delete_one({"_id": DOC_ID}, session=s)).deleted_count == 0:
            raise NOT_SAVED
        await audit.record(db, AuditAction.EMAIL_SETTINGS_REMOVED, actor=actor_from_user(ctx.user), ip=meta.ip,
                           resource_type="settings", resource_id=DOC_ID, session=s)

    await run_in_transaction(db, work)


async def send_test(db: AsyncDatabase, settings: Settings, ctx: AuthContext, meta: RequestMeta,
                    to: str) -> tuple[bool, str | None, str]:
    """Sends one test e-mail with the settings in use. Returns (sent, reason, source).
    One test at a time. The recipient's address is not logged or audited (only its domain)."""
    if _testing.locked():
        raise BUSY
    async with _testing:
        doc = await saved(db)
        where = source(doc, settings)
        try:
            config = await effective(db, settings)
        except SmtpUnusable as e:
            return await _tested(db, ctx, meta, to, False, e.reason, where)
        if config is None:
            return await _tested(db, ctx, meta, to, False, "EMAIL_NOT_CONFIGURED", where)
        try:
            message = email_svc.verification_message(settings, config, to)
            await asyncio.wait_for(asyncio.to_thread(email_svc.send, config, message),
                                   timeout=config.timeout_seconds + 10)
        except email_svc.EmailError as e:
            log.warning("Test e-mail failed (%s, %s)", e.reason, e.code)      # codes only
            return await _tested(db, ctx, meta, to, False, e.reason, where)
        except TimeoutError:
            return await _tested(db, ctx, meta, to, False, "EMAIL_CONNECTION_TIMEOUT", where)
        except Exception as e:                                # never a 500 with a traceback: type only
            log.error("Test e-mail: unexpected %s", type(e).__name__)
            return await _tested(db, ctx, meta, to, False, "EMAIL_SEND_FAILED", where)
        return await _tested(db, ctx, meta, to, True, None, where)


async def _tested(db: AsyncDatabase, ctx: AuthContext, meta: RequestMeta, to: str, sent: bool, reason: str | None,
                  where: str) -> tuple[bool, str | None, str]:
    await audit.record(db, AuditAction.EMAIL_TEST_SENT, result="SUCCESS" if sent else "FAILURE",
                       actor=actor_from_user(ctx.user), ip=meta.ip, resource_type="settings", resource_id=DOC_ID,
                       metadata={"reason": reason, "source": where, "recipient_domain": to.rpartition("@")[2]})
    return sent, reason, where
