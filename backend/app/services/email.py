"""
E-mail to hosts: the host-arrival message and its delivery over SMTP.

Standard library only (smtplib / email). Blocking: call send() via asyncio.to_thread.
The SMTP password comes from settings (server environment) and is never logged or stored.
Errors are reduced to a short, safe code ("SMTPConnectError", "SMTPRecipientsRefused 550",
"TimeoutError"): SMTP replies can contain server details and are not kept.

Content: visitor name, arrival time, gate, department and reason. Never the ID number, phone,
visit/database ids, QR token or anything about the session.
"""
import html
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from functools import cache
from pathlib import Path
from string import Template
from zoneinfo import ZoneInfo

from app.core.config import Settings

REASON_LABELS = {
    "OFFICIAL_MEETING": "Official meeting", "INTERVIEW": "Interview", "DELIVERY": "Delivery",
    "MAINTENANCE": "Maintenance", "CONTRACTOR_WORK": "Contractor work", "PERSONAL": "Personal", "OTHER": "Other",
}


@cache
def _template(name: str) -> Template:
    return Template((Path(__file__).parent / "templates" / name).read_text(encoding="utf-8"))


class EmailError(Exception):
    """Delivery failed. `code` is safe to store and log."""

    def __init__(self, code: str, permanent: bool):
        super().__init__(code)
        self.code = code
        self.permanent = permanent


def _local(moment: datetime, settings: Settings) -> str:
    return moment.astimezone(ZoneInfo(settings.timezone)).strftime("%d %b %Y, %H:%M")


def host_arrival_message(settings: Settings, to: str, data: dict) -> EmailMessage:
    visitor = data.get("visitor_name") or "Your visitor"
    rows = [("Visitor", visitor), ("Arrived", _local(data["check_in_at"], settings)),
            ("Gate", data.get("gate_name")), ("Department", data.get("department_name")),
            ("Reason", REASON_LABELS.get(data.get("reason_code") or "", None))]
    rows = [(label, value) for label, value in rows if value]
    org = settings.organization_name

    text = "\n".join([
        f"Dear {data.get('host_name') or 'colleague'},", "",
        f"{visitor} has arrived at the gate to visit you.", "",
        *[f"{label}: {value}" for label, value in rows], "",
        f"{org} visitor management. This message was sent automatically; please do not reply.",
    ])
    e = html.escape
    table = "".join(f'<tr><td style="padding:4px 16px 4px 0;color:#5b6573">{e(label)}</td>'
                    f'<td style="padding:4px 0;font-weight:600;color:#111827">{e(str(value))}</td></tr>'
                    for label, value in rows)
    body = _template("host_arrival.html").substitute(
        org_upper=e(org.upper()), org=e(org), host_name=e(data.get("host_name") or "colleague"),
        visitor=e(visitor), rows=table)

    message = EmailMessage()
    message["Subject"] = f"Visitor arrived: {visitor}"
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Date"] = formatdate(localtime=True)
    domain = parseaddr(settings.smtp_from or "")[1].rpartition("@")[2] or None
    message["Message-ID"] = make_msgid(domain=domain)
    message.set_content(text)
    message.add_alternative(body, subtype="html")
    return message


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


def send(settings: Settings, message: EmailMessage) -> None:
    """Delivers one message. Raises EmailError(code, permanent) on failure."""
    context = ssl.create_default_context()          # certificate and host name are always checked
    timeout = settings.smtp_timeout_seconds
    try:
        if settings.smtp_security == "ssl":
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=timeout, context=context)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=timeout)
        with server:
            server.ehlo()
            if settings.smtp_security == "starttls":
                server.starttls(context=context)
                server.ehlo()
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            server.send_message(message)
    except (smtplib.SMTPException, OSError) as error:        # OSError: refused, unreachable, TLS, timeout
        raise EmailError(_safe_code(error), _is_permanent(error)) from None
