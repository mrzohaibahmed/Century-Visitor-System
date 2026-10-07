"""
E-mail to hosts and departments: the arrival messages and their delivery over SMTP.

Standard library only (smtplib / email). Blocking: call send() via asyncio.to_thread.
Generic SMTP for any provider: only host, port, security, user name and password decide how mail is
sent (services/email_settings.py picks them: the settings saved by an administrator, or the server
environment). The SMTP password is never logged, and never stored unencrypted.
Errors are reduced to a short, safe code ("SMTPConnectError", "SMTPRecipientsRefused 550",
"TimeoutError") plus an application-level `reason` (EMAIL_AUTHENTICATION_FAILED, ...): SMTP replies
can contain server details and are not kept.

Content: visitor name, arrival time, gate, department and reason. Never the ID number, phone,
visit/database ids, QR token or anything about the session.
"""
import html
import smtplib
import ssl
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from functools import cache
from pathlib import Path
from string import Template
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import SecretStr

from app.core.config import Settings

REASON_LABELS = {
    "OFFICIAL_MEETING": "Official meeting", "INTERVIEW": "Interview", "DELIVERY": "Delivery",
    "MAINTENANCE": "Maintenance", "CONTRACTOR_WORK": "Contractor work", "PERSONAL": "Personal", "OTHER": "Other",
}


@cache
def _template(name: str) -> Template:
    return Template((Path(__file__).parent / "templates" / name).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class SmtpConfig:
    """How to send mail, from any SMTP provider. `password` never shows in repr."""

    host: str
    port: int
    security: Literal["starttls", "ssl", "none"]
    username: str | None
    password: SecretStr | None = field(repr=False)
    sender: str                         # the From header, e.g. "Century Gate VMS <vms@example.com>"
    reply_to: str | None
    timeout_seconds: int
    source: Literal["database", "environment"]


def config_from_environment(settings: Settings) -> SmtpConfig | None:
    """The CG_SMTP_* settings (used when no administrator settings are saved), or None when unset."""
    if not settings.smtp_host:
        return None
    return SmtpConfig(host=settings.smtp_host, port=settings.smtp_port, security=settings.smtp_security,
                      username=settings.smtp_username or None, password=settings.smtp_password,
                      sender=settings.smtp_from or "", reply_to=None,
                      timeout_seconds=settings.smtp_timeout_seconds, source="environment")


# Application-level reasons: safe to show to an administrator (never an SMTP reply or a secret).
REASON_MESSAGES = {
    "EMAIL_NOT_CONFIGURED": "E-mail is not set up, or it is switched off.",
    "EMAIL_CREDENTIALS_UNREADABLE": "The saved SMTP password cannot be read (the server key has changed). "
                                    "Enter the password again.",
    "EMAIL_CONNECTION_FAILED": "The mail server cannot be reached. Check the host name and the port.",
    "EMAIL_CONNECTION_TIMEOUT": "The mail server did not answer in time.",
    "EMAIL_AUTHENTICATION_FAILED": "The mail server refused the user name or password.",
    "EMAIL_TLS_FAILED": "The secure connection to the mail server failed. Check the security setting "
                        "(STARTTLS or SSL/TLS) and the port.",
    "EMAIL_INVALID_RESPONSE": "The mail server sent an unexpected answer. Check the host name and the port.",
    "EMAIL_RECIPIENT_REFUSED": "The mail server refused the recipient address.",
    "EMAIL_SEND_FAILED": "The mail server did not accept the message.",
}


class EmailError(Exception):
    """Delivery failed. `code` is safe to store and log (kept as before for the notification queue);
    `reason` is the application-level reason (a key of REASON_MESSAGES)."""

    def __init__(self, code: str, permanent: bool, reason: str = "EMAIL_SEND_FAILED"):
        super().__init__(code)
        self.code = code
        self.permanent = permanent
        self.reason = reason


def _local(moment: datetime, settings: Settings) -> str:
    return moment.astimezone(ZoneInfo(settings.timezone)).strftime("%d %b %Y, %H:%M")


def _headers(message: EmailMessage, config: SmtpConfig, to: str) -> EmailMessage:
    message["From"] = config.sender
    message["To"] = to
    if config.reply_to:
        message["Reply-To"] = config.reply_to
    message["Date"] = formatdate(localtime=True)
    domain = parseaddr(config.sender or "")[1].rpartition("@")[2] or None
    message["Message-ID"] = make_msgid(domain=domain)
    return message


def verification_message(settings: Settings, config: SmtpConfig, to: str) -> EmailMessage:
    """The administrator's test e-mail: proves that these SMTP settings deliver mail."""
    org = settings.organization_name
    message = EmailMessage()
    message["Subject"] = f"{org} visitor management: test e-mail"
    _headers(message, config, to)
    message.set_content(f"This is a test e-mail from the {org} visitor management system.\n\n"
                        "E-mail to hosts is working with these settings. No action is needed.")
    return message


def _arrival_message(settings: Settings, config: SmtpConfig, to: str, data: dict, *, greeting: str,
                     visiting: str, extra_rows: tuple = ()) -> EmailMessage:
    visitor = data.get("visitor_name") or "Your visitor"
    rows = [("Visitor", visitor), *extra_rows, ("Arrived", _local(data["check_in_at"], settings)),
            ("Gate", data.get("gate_name")), ("Department", data.get("department_name")),
            ("Reason", REASON_LABELS.get(data.get("reason_code") or "", None))]
    rows = [(label, value) for label, value in rows if value]
    org = settings.organization_name

    text = "\n".join([
        f"Dear {greeting},", "",
        f"{visitor} has arrived at the gate to visit {visiting}.", "",
        *[f"{label}: {value}" for label, value in rows], "",
        f"{org} visitor management. This message was sent automatically; please do not reply.",
    ])
    e = html.escape
    table = "".join(f'<tr><td style="padding:4px 16px 4px 0;color:#5b6573">{e(label)}</td>'
                    f'<td style="padding:4px 0;font-weight:600;color:#111827">{e(str(value))}</td></tr>'
                    for label, value in rows)
    body = _template("host_arrival.html").substitute(
        org_upper=e(org.upper()), org=e(org), greeting=e(greeting), visiting=e(visiting),
        visitor=e(visitor), rows=table)

    message = EmailMessage()
    message["Subject"] = f"Visitor arrived: {visitor}"
    _headers(message, config, to)
    message.set_content(text)
    message.add_alternative(body, subtype="html")
    return message


def host_arrival_message(settings: Settings, config: SmtpConfig, to: str, data: dict) -> EmailMessage:
    return _arrival_message(settings, config, to, data, greeting=data.get("host_name") or "colleague",
                            visiting="you")


def department_arrival_message(settings: Settings, config: SmtpConfig, to: str, data: dict) -> EmailMessage:
    """To the department's notification address: names the host being visited (listed or not)."""
    department = data.get("department_name")
    host = data.get("host_name")
    return _arrival_message(settings, config, to, data,
                            greeting=f"{department} team" if department else "colleagues",
                            visiting=host or "your department", extra_rows=(("Host", host),))


def _overstay_message(settings: Settings, config: SmtpConfig, to: str, data: dict, *, greeting: str,
                      extra_rows: tuple = ()) -> EmailMessage:
    visitor = data.get("visitor_name") or "A visitor"
    rows = [("Visitor", visitor), *extra_rows,
            ("Arrived", _local(data["check_in_at"], settings) if data.get("check_in_at") else None),
            ("Badge valid until", _local(data["expires_at"], settings) if data.get("expires_at") else None),
            ("Gate", data.get("gate_name")), ("Department", data.get("department_name")),
            ("Reason", REASON_LABELS.get(data.get("reason_code") or "", None))]
    rows = [(label, value) for label, value in rows if value]
    org = settings.organization_name

    text = "\n".join([
        f"Dear {greeting},", "",
        f"{visitor} is still on site after their badge expired (gate closing). Please arrange check-out.", "",
        *[f"{label}: {value}" for label, value in rows], "",
        f"{org} visitor management. This message was sent automatically; please do not reply.",
    ])
    e = html.escape
    table = "".join(f'<tr><td style="padding:4px 16px 4px 0;color:#5b6573">{e(label)}</td>'
                    f'<td style="padding:4px 0;font-weight:600;color:#111827">{e(str(value))}</td></tr>'
                    for label, value in rows)
    body = _template("visitor_overstay.html").substitute(
        org_upper=e(org.upper()), org=e(org), greeting=e(greeting), visitor=e(visitor), rows=table)

    message = EmailMessage()
    message["Subject"] = f"Visitor overstay: {visitor}"
    _headers(message, config, to)
    message.set_content(text)
    message.add_alternative(body, subtype="html")
    return message


def host_overstay_message(settings: Settings, config: SmtpConfig, to: str, data: dict) -> EmailMessage:
    return _overstay_message(settings, config, to, data, greeting=data.get("host_name") or "colleague")


def department_overstay_message(settings: Settings, config: SmtpConfig, to: str, data: dict) -> EmailMessage:
    department = data.get("department_name")
    host = data.get("host_name")
    return _overstay_message(settings, config, to, data,
                             greeting=f"{department} team" if department else "colleagues",
                             extra_rows=(("Host", host),))


def _safe_code(error: Exception) -> str:
    code = getattr(error, "smtp_code", None)
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        codes = [c for c, _ in error.recipients.values()]
        code = codes[0] if codes else None
    return f"{type(error).__name__} {code}" if code else type(error).__name__


def _is_permanent(error: Exception) -> bool:
    """Only a refused recipient/sender or a 5xx answer to the message is final. Connection problems,
    timeouts, 4xx answers and login failures (the configuration may be fixed meanwhile) are retried."""
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        return all(500 <= c < 600 for c, _ in error.recipients.values())
    if isinstance(error, (smtplib.SMTPSenderRefused, smtplib.SMTPDataError)):
        return 500 <= error.smtp_code < 600
    return False


def _timed_out(error: BaseException | None) -> bool:
    """smtplib reports a reply that never came as SMTPServerDisconnected("... timed out"), with the
    TimeoutError only as the exception's context: look along the chain."""
    seen = 0
    while error is not None and seen < 5:
        if isinstance(error, TimeoutError):
            return True
        error, seen = error.__cause__ or error.__context__, seen + 1
    return False


def _reason(error: Exception, phase: str) -> str:
    """The application-level reason for a failure in `phase` (connect, tls, login or send)."""
    if _timed_out(error):
        return "EMAIL_CONNECTION_TIMEOUT"
    if isinstance(error, ssl.SSLError) or (phase == "tls" and isinstance(error, smtplib.SMTPException)):
        return "EMAIL_TLS_FAILED"                    # incl. a certificate that is not trusted, or no STARTTLS
    if isinstance(error, smtplib.SMTPAuthenticationError) or phase == "login":
        return "EMAIL_AUTHENTICATION_FAILED"         # incl. a server that offers no login
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        return "EMAIL_RECIPIENT_REFUSED"
    if isinstance(error, (smtplib.SMTPConnectError, smtplib.SMTPHeloError)):
        return "EMAIL_INVALID_RESPONSE"
    if isinstance(error, OSError) or phase == "connect":
        return "EMAIL_CONNECTION_FAILED"             # refused, unreachable, unknown host, closed
    return "EMAIL_SEND_FAILED"


def send(config: SmtpConfig, message: EmailMessage) -> None:
    """Delivers one message with these SMTP settings (any provider).
    Raises EmailError(code, permanent, reason) on failure; never with a password or an SMTP reply."""
    context = ssl.create_default_context()          # certificate and host name are always checked
    timeout = config.timeout_seconds
    phase = "connect"
    try:
        if config.security == "ssl":                 # SSL/TLS from the first byte (usually port 465)
            server = smtplib.SMTP_SSL(config.host, config.port, timeout=timeout, context=context)
        else:
            server = smtplib.SMTP(config.host, config.port, timeout=timeout)
        with server:
            server.ehlo()
            if config.security == "starttls":        # plain connection upgraded to TLS (usually port 587)
                phase = "tls"
                server.starttls(context=context)
                server.ehlo()
            if config.username:
                phase = "login"
                server.login(config.username, config.password.get_secret_value() if config.password else "")
            phase = "send"
            server.send_message(message)
    except (smtplib.SMTPException, OSError) as error:        # OSError: refused, unreachable, TLS, timeout
        raise EmailError(_safe_code(error), _is_permanent(error), _reason(error, phase)) from None
    except UnicodeError:                                     # smtplib logs in with ASCII only (e.g. "é" in a password)
        raise EmailError("UnicodeEncodeError", False,
                         "EMAIL_AUTHENTICATION_FAILED" if phase == "login" else "EMAIL_SEND_FAILED") from None
