"""
The SQL Server tables, for building queries with SQLAlchemy Core (no ORM).

The schema itself is the reviewed SQL in app/db/sql (0001, 0002, ...), applied by Alembic; these
definitions mirror it and never create anything. tests/test_mssql_foundation.py compares them with the
migrated database, so the two cannot drift apart unnoticed.
"""
from sqlalchemy import CHAR, Boolean, Column, Computed, Date, Integer, MetaData, String, Table, Unicode, UnicodeText
from sqlalchemy.dialects.mssql import TINYINT, UNIQUEIDENTIFIER, VARBINARY

from app.repositories.types import UtcDateTime

BIN2 = "Latin1_General_100_BIN2"
metadata = MetaData(schema="dbo")


def _id(name: str = "id", *, nullable: bool = False, primary_key: bool = False) -> Column:
    return Column(name, UNIQUEIDENTIFIER(as_uuid=True), nullable=nullable, primary_key=primary_key)


def _ref(name: str, *, nullable: bool = True) -> Column:
    return _id(name, nullable=nullable)


def _at(name: str, *, nullable: bool = True) -> Column:
    return Column(name, UtcDateTime(), nullable=nullable)


def _hash(name: str, length: int = 64, *, nullable: bool = False, primary_key: bool = False) -> Column:
    return Column(name, CHAR(length, collation=BIN2), nullable=nullable, primary_key=primary_key)


def _sealed(prefix: str, ct_length: int) -> list[Column]:
    """A secret sealed by core/secrets.encrypt: {"v", "kid", "nonce", "ct"}."""
    return [Column(f"{prefix}_version", TINYINT()), Column(f"{prefix}_kid", String(32)),
            Column(f"{prefix}_nonce", VARBINARY(12)), Column(f"{prefix}_ct", VARBINARY(ct_length))]


# ------------------------------------------------------------------------------------------ accounts
users = Table(
    "users", metadata,
    _id(primary_key=True),
    Column("username", Unicode(32), nullable=False),
    Column("display_name", Unicode(80)),
    Column("password_hash", Unicode(255), nullable=False),
    Column("role", String(10), nullable=False),
    Column("is_active", Boolean(), nullable=False),
    Column("must_change_password", Boolean(), nullable=False),
    Column("failed_login_count", Integer(), nullable=False),
    _at("locked_until"), _at("last_login_at"), _at("password_changed_at"),
    _at("created_at", nullable=False), _at("updated_at", nullable=False),
    _ref("created_by"),
)

sessions = Table(
    "sessions", metadata,
    _id(primary_key=True),
    _hash("token_hash"), _hash("csrf_token_hash"),
    _ref("user_id", nullable=False), _ref("gate_id"),
    _at("created_at", nullable=False), _at("last_seen_at", nullable=False), _at("expires_at", nullable=False),
    _at("revoked_at"),
    Column("revoked_reason", String(32)),
    Column("ip", String(45)),
    Column("user_agent", Unicode(256)),
)

rate_limits = Table(
    "rate_limits", metadata,
    Column("window_key", String(200, collation=BIN2), primary_key=True),
    Column("count", Integer(), nullable=False),
    _at("expires_at", nullable=False),
)

# ------------------------------------------------------------------------------------------ directory
gates = Table(
    "gates", metadata,
    _id(primary_key=True),
    Column("name", Unicode(60), nullable=False),
    Column("location", Unicode(120)),
    Column("is_active", Boolean(), nullable=False),
    _at("created_at", nullable=False), _at("updated_at", nullable=False),
    _ref("created_by"),
)

departments = Table(
    "departments", metadata,
    _id(primary_key=True),
    Column("name", Unicode(60), nullable=False),
    Column("notification_email", Unicode(254)),
    Column("is_active", Boolean(), nullable=False),
    _at("created_at", nullable=False), _at("updated_at", nullable=False),
    _ref("created_by"),
)

hosts = Table(
    "hosts", metadata,
    _id(primary_key=True),
    Column("name", Unicode(100), nullable=False),          # a person's name (normalize_name), as visitors
    Column("name_search", Unicode(100, collation=BIN2), nullable=False),     # exact search key (0004)
    Column("email", Unicode(254)),
    Column("phone", String(16)),
    _ref("department_id"), _ref("linked_user_id"),
    Column("is_active", Boolean(), nullable=False),
    _at("created_at", nullable=False), _at("updated_at", nullable=False),
    _ref("created_by"),
)

# ------------------------------------------------------------------------------------------ visitors
visitors = Table(
    "visitors", metadata,
    _id(primary_key=True),
    Column("full_name", Unicode(100), nullable=False),
    Column("name_search", Unicode(100, collation=BIN2), nullable=False),     # exact search key (0004)
    Column("identity_type", String(10)),
    Column("identity_number", Unicode(60)),
    Column("phone", String(16)),
    _ref("current_photo_id"),
    _at("created_at", nullable=False), _at("updated_at", nullable=False),
    _ref("created_by"),
)

photos = Table(
    "photos", metadata,
    _id(primary_key=True),
    _hash("storage_key", 32),
    _ref("visitor_id", nullable=False), _ref("visit_id"),
    Column("content_type", String(20), nullable=False),
    Column("size_bytes", Integer(), nullable=False),
    Column("width", Integer(), nullable=False),
    Column("height", Integer(), nullable=False),
    _hash("sha256"),
    _ref("captured_by", nullable=False),
    _at("captured_at", nullable=False),
    _ref("gate_id"),
)

# ------------------------------------------------------------------------------------------ visits
visits = Table(
    "visits", metadata,
    _id(primary_key=True),
    Column("visit_number", String(20, collation=BIN2), nullable=False),
    _ref("visitor_id", nullable=False), _ref("host_id"),
    Column("host_unlisted", Boolean(), nullable=False),
    _ref("department_id"), _ref("gate_id"), _ref("checkout_gate_id"),
    Column("reason_code", String(20), nullable=False),
    Column("reason_note", Unicode(200)),
    Column("vehicle_registration", String(15)),
    Column("status", String(12), nullable=False),
    _at("check_in_at", nullable=False), _at("check_out_at"),
    _ref("checked_in_by", nullable=False), _ref("checked_out_by"),
    Column("checkout_method", String(12)),
    _ref("photo_id"),
    Column("snap_visitor_name", Unicode(100), nullable=False),
    Column("snap_host_name", Unicode(100)),
    Column("snap_department_name", Unicode(60)),
    Column("snap_gate_name", Unicode(60)),
    Column("snap_checked_in_by_name", Unicode(80)),
    Column("snap_checked_out_by_name", Unicode(80)),
    Column("snap_checkout_gate_name", Unicode(60)),
    _hash("pass_token_hash", nullable=True),
    _at("pass_issued_at"), _at("pass_expires_at"),
    _ref("pass_issued_by"),
    _at("pass_revoked_at"),
    _ref("pass_revoked_by"),
    *_sealed("pass_qr", 256),
    _at("created_at", nullable=False), _at("updated_at", nullable=False),
)

visit_belongings = Table(                                  # primary key (visit_id, position)
    "visit_belongings", metadata,
    _id("visit_id", primary_key=True),
    Column("position", TINYINT(), primary_key=True, autoincrement=False),
    Column("description", Unicode(40), nullable=False),
)

visit_personal_material = Table(
    "visit_personal_material", metadata,
    _id("visit_id", primary_key=True),
    Column("contact_name", Unicode(80), nullable=False),
    Column("material_date", Date()),
    Column("remarks", Unicode(500), nullable=False),
    Column("authorised_by", Unicode(80), nullable=False),
    Column("issued_by", Unicode(80), nullable=False),
    Column("gate_officer", Unicode(80), nullable=False),
)

visit_material_items = Table(                              # primary key (visit_id, position)
    "visit_material_items", metadata,
    _id("visit_id", primary_key=True),
    Column("position", TINYINT(), primary_key=True, autoincrement=False),
    Column("description", Unicode(40), nullable=False),
    Column("qty_in", String(4)),
    Column("qty_out", String(4)),
)

visit_replaced_passes = Table(
    "visit_replaced_passes", metadata,
    _hash("token_hash", primary_key=True),
    _ref("visit_id", nullable=False),
    _at("replaced_at", nullable=False),
)

visit_number_counters = Table(
    "visit_number_counters", metadata,
    Column("day", Date(), primary_key=True),
    Column("seq", Integer(), nullable=False),
)

# ------------------------------------------------------------------------------------------ watchlist
watchlist = Table(
    "watchlist", metadata,
    _id(primary_key=True),
    Column("identifier", Unicode(72), nullable=False),
    # Computed by SQL Server (never written): the identifier without spaces, / and -.
    Column("identifier_compact", Unicode(72),
           Computed("CAST(REPLACE(REPLACE(REPLACE(identifier, N' ', N''), N'/', N''), N'-', N'') AS NVARCHAR(72))",
                    persisted=True)),
    Column("identity_type", String(10), nullable=False),
    Column("identity_number", Unicode(60), nullable=False),
    Column("name", Unicode(100)),
    Column("name_search", Unicode(100, collation=BIN2)),                    # exact search key (0004)
    Column("reason", Unicode(500), nullable=False),
    Column("is_active", Boolean(), nullable=False),
    _at("expires_at"),
    _ref("created_by", nullable=False),
    Column("created_by_name", Unicode(80)),
    _at("created_at", nullable=False),
    _ref("updated_by"), _at("updated_at"),
    _ref("disabled_by"),
    Column("disabled_by_name", Unicode(80)),
    _at("disabled_at"),
    Column("disabled_reason", Unicode(200)),
)

# ------------------------------------------------------------------------------------ audit, notifications, denials
audit_logs = Table(
    "audit_logs", metadata,
    _id(primary_key=True),
    _at("timestamp", nullable=False),
    Column("action", String(40), nullable=False),
    Column("result", String(10), nullable=False),
    _ref("actor_user_id"),
    Column("actor_username", Unicode(64)),
    Column("actor_role", String(10)),
    Column("resource_type", String(30)),
    Column("resource_id", String(64)),
    Column("ip", String(45)),
    Column("request_id", String(64)),
    Column("changes", UnicodeText()),
    Column("metadata", UnicodeText()),
)

notifications = Table(
    "notifications", metadata,
    _id(primary_key=True),
    Column("event_key", String(80, collation=BIN2), nullable=False),
    Column("type", String(30), nullable=False),
    _ref("recipient_user_id"), _ref("visit_id"), _ref("visitor_id"), _ref("host_id"),
    Column("data", UnicodeText(), nullable=False),
    _at("created_at", nullable=False), _at("read_at"),
    Column("email_status", String(8), nullable=False),
    Column("email_to", Unicode(254)),
    Column("email_attempts", Integer(), nullable=False),
    _at("email_next_attempt_at"), _at("email_last_attempt_at"), _at("email_lease_until"), _at("email_sent_at"),
    Column("email_reason", String(40)),
    Column("email_error", String(80)),
)

entry_denials = Table(
    "entry_denials", metadata,
    _id(primary_key=True),
    _at("at", nullable=False),
    Column("reason", String(20), nullable=False),
    Column("source", String(20), nullable=False),
    _ref("source_audit_id", nullable=False),
    _ref("visitor_id"),
    Column("visitor_name", Unicode(100)),
    Column("identifier_masked", Unicode(72)),
    _ref("watchlist_id"), _ref("gate_id"),
    Column("gate_name", Unicode(60)),
    _ref("operator_id"),
    Column("operator_username", Unicode(64)),
    Column("operator_name", Unicode(80)),
    Column("reason_code", String(20)),
)

# ------------------------------------------------------------------------------------------ settings
email_settings = Table(
    "email_settings", metadata,
    Column("id", TINYINT(), primary_key=True, autoincrement=False),
    Column("enabled", Boolean(), nullable=False),
    Column("smtp_host", Unicode(253)),
    Column("smtp_port", Integer()),
    Column("security", String(10)),
    Column("username", Unicode(254)),
    Column("from_email", Unicode(254)),
    Column("from_name", Unicode(80)),
    Column("reply_to", Unicode(254)),
    *_sealed("password", 512),
    _at("created_at", nullable=False), _at("updated_at", nullable=False),
    _ref("updated_by"),
)

gate_cameras = Table(
    "gate_cameras", metadata,
    _id("gate_id", primary_key=True),
    Column("enabled", Boolean(), nullable=False),
    Column("host", Unicode(253), nullable=False),
    Column("protocol", String(5), nullable=False),
    Column("port", Integer()),
    Column("channel", Integer(), nullable=False),
    Column("username", Unicode(64), nullable=False),
    Column("timeout_seconds", Integer(), nullable=False),
    *_sealed("password", 512),
    _at("last_test_at"),
    Column("last_test_ok", Boolean()),
    Column("last_test_code", String(40)),
    Column("last_test_message", Unicode(400)),
    Column("last_test_model", Unicode(100)),
    Column("last_test_firmware", Unicode(100)),
    Column("last_test_device_name", Unicode(100)),
    _at("created_at", nullable=False), _at("updated_at", nullable=False),
    _ref("updated_by"),
)
