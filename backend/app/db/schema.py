"""
Declarative schema for the NEW database (century_gate_vms): collections,
$jsonSchema validators and indexes, as approved in the architecture audit.

Validators check the essentials (required fields, types, enums) as a last line
of defence; full validation happens in the API's Pydantic models. Each index
names the query or constraint it exists for.

Notifications (Phase 6A): host- and department-arrival notifications; the collection is also the queue
of emails still to send (see services/notifications.py).

Photos (Phase 4): the image files live in a private folder on the API server
(CG_PHOTO_DIR, random file names); the `photos` collection holds their metadata.

Bump SCHEMA_VERSION whenever this file changes; /health/ready reports a
database that has not been migrated to it.
"""
from dataclasses import dataclass, field

from pymongo import ASCENDING, DESCENDING, IndexModel

SCHEMA_VERSION = 6   # v6 (Reports): entry_denials (refused entries, for reporting)
# v5 (Reports): visit indexes for the guard and gate filters; department e-mail type
# v4 (Phase 6A): notifications; hosts.linked_user_id
# v3 (Phase 4): photos, pass lifecycle, watchlist management
# v2 (Phase 3): visit history filter indexes; reason/check-out enums

# Case-insensitive uniqueness (e.g. "Admin" and "admin" are the same user).
# Queries must pass the same collation to use these indexes.
CASE_INSENSITIVE = {"locale": "en", "strength": 2}

ROLES = ["ADMIN", "GUARD"]
VISIT_STATUSES = ["SCHEDULED", "EXPECTED", "CHECKED_IN", "CHECKED_OUT", "CANCELLED", "EXPIRED", "NO_SHOW"]
IDENTITY_TYPES = ["CNIC", "PASSPORT", "OTHER"]
AUDIT_RESULTS = ["SUCCESS", "FAILURE", "DENIED"]
VISIT_REASONS = ["OFFICIAL_MEETING", "INTERVIEW", "DELIVERY", "MAINTENANCE", "CONTRACTOR_WORK", "PERSONAL", "OTHER"]
CHECKOUT_METHODS = ["MANUAL", "VISIT_NUMBER", "ID_NUMBER", "QR", "AUTO"]

DATE = {"bsonType": "date"}
OPTIONAL_DATE = {"bsonType": ["date", "null"]}
OBJECT_ID = {"bsonType": "objectId"}
OPTIONAL_OBJECT_ID = {"bsonType": ["objectId", "null"]}
TEXT = {"bsonType": "string", "minLength": 1}
OPTIONAL_TEXT = {"bsonType": ["string", "null"]}
BOOL = {"bsonType": "bool"}
SHA256_HEX = {"bsonType": "string", "pattern": "^[0-9a-f]{64}$"}
PHOTO_TYPES = ["image/jpeg"]           # every upload is re-encoded to JPEG
NOTIFICATION_TYPES = [
    "HOST_VISITOR_ARRIVAL", "DEPARTMENT_VISITOR_ARRIVAL",
    "HOST_VISITOR_OVERSTAY", "DEPARTMENT_VISITOR_OVERSTAY",
]
DENIAL_REASONS = ["WATCHLIST"]
# check_in: refused by POST /visits; lookup: BLOCKED at the check-in lookup; audit_backfill: rebuilt from a
# WATCHLIST_MATCH audit entry (python -m app.cli backfill-entry-denials).
DENIAL_SOURCES = ["check_in", "lookup", "audit_backfill"]
# NONE: nobody to e-mail (host without address) or e-mail switched off (no SMTP server configured).
EMAIL_STATES = ["NONE", "PENDING", "SENDING", "SENT", "FAILED"]


def _schema(required: list[str], properties: dict) -> dict:
    return {"$jsonSchema": {"bsonType": "object", "required": required, "properties": properties}}


@dataclass(frozen=True)
class CollectionSpec:
    name: str
    validator: dict | None = None
    indexes: list[IndexModel] = field(default_factory=list)


COLLECTIONS: list[CollectionSpec] = [
    CollectionSpec(
        "users",
        _schema(["username", "password_hash", "role", "is_active", "created_at", "updated_at"], {
            "username": {"bsonType": "string", "minLength": 3, "maxLength": 32},
            "display_name": OPTIONAL_TEXT,
            "password_hash": TEXT,
            "role": {"enum": ROLES},
            "is_active": BOOL,
            "failed_login_count": {"bsonType": ["int", "long"], "minimum": 0},
            "locked_until": OPTIONAL_DATE,
            "last_login_at": OPTIONAL_DATE,
            "created_at": DATE, "updated_at": DATE,
        }),
        [
            # Login lookup; one account per username regardless of case.
            IndexModel([("username", ASCENDING)], name="username_unique", unique=True, collation=CASE_INSENSITIVE),
        ],
    ),
    CollectionSpec(
        "sessions",
        _schema(["token_hash", "user_id", "created_at", "last_seen_at", "expires_at"], {
            "token_hash": SHA256_HEX,             # the raw token only ever exists in the user's cookie
            "user_id": OBJECT_ID,
            "gate_id": OPTIONAL_OBJECT_ID,
            "created_at": DATE, "last_seen_at": DATE, "expires_at": DATE,
            "revoked_at": OPTIONAL_DATE,
        }),
        [
            IndexModel([("token_hash", ASCENDING)], name="token_hash_unique", unique=True),   # every request
            IndexModel([("user_id", ASCENDING)], name="by_user"),        # revoke all on disable/password reset
            IndexModel([("expires_at", ASCENDING)], name="expiry_ttl", expireAfterSeconds=0),  # auto cleanup
        ],
    ),
    CollectionSpec(
        "visitors",
        _schema(["full_name", "name_search", "created_at", "updated_at"], {
            "full_name": TEXT,
            "name_search": TEXT,                  # lower-case, collapsed spaces: prefix search
            "identity": {"bsonType": ["object", "null"], "required": ["type", "number"], "properties": {
                "type": {"enum": IDENTITY_TYPES}, "number": TEXT}},
            "phone": OPTIONAL_TEXT,
            "current_photo_id": OPTIONAL_OBJECT_ID,
            "created_at": DATE, "updated_at": DATE,
        }),
        [
            # Check-in lookup by identity; one person per identity document.
            IndexModel([("identity.type", ASCENDING), ("identity.number", ASCENDING)], name="identity_unique",
                       unique=True, partialFilterExpression={"identity.number": {"$type": "string"}}),
            IndexModel([("name_search", ASCENDING)], name="name_prefix"),      # search by name
            IndexModel([("phone", ASCENDING)], name="phone"),                  # search by phone (shared phones allowed)
        ],
    ),
    CollectionSpec(
        "visits",
        _schema(["visit_number", "visitor_id", "status", "check_in_at", "checked_in_by", "snapshot",
                 "created_at", "updated_at"], {
            # V-26-OCT-02-001, or the earlier V-26-0210-001 and V-2026-000123 (schemas/visits.py).
            "visit_number": {"bsonType": "string", "pattern": "^V-([0-9]{2}-[A-Z]{3}-[0-9]{2}-[0-9]{3,}"
                                                              "|[0-9]{2}-[0-9]{4}-[0-9]{3,}|[0-9]{4}-[0-9]{6,})$"},
            "visitor_id": OBJECT_ID,
            "host_id": OPTIONAL_OBJECT_ID,
            "department_id": OPTIONAL_OBJECT_ID,
            "gate_id": OPTIONAL_OBJECT_ID,
            "checkout_gate_id": OPTIONAL_OBJECT_ID,
            "status": {"enum": VISIT_STATUSES},
            "check_in_at": DATE,
            "check_out_at": OPTIONAL_DATE,
            "reason_code": {"enum": VISIT_REASONS},
            "checkout_method": {"enum": [*CHECKOUT_METHODS, None]},
            "host_unlisted": BOOL,
            "checked_in_by": OBJECT_ID,
            "checked_out_by": OPTIONAL_OBJECT_ID,
            "snapshot": {"bsonType": "object", "required": ["visitor_name"], "properties": {
                "visitor_name": TEXT}},
            "photo_id": OPTIONAL_OBJECT_ID,
            # The QR pass: only hashes of the random tokens are stored (the token is printed on the badge).
            "pass": {"bsonType": ["object", "null"], "required": ["token_hash", "issued_at", "expires_at"],
                     "properties": {
                         "token_hash": SHA256_HEX, "issued_at": DATE, "expires_at": DATE,
                         "issued_by": OBJECT_ID,
                         "revoked_at": OPTIONAL_DATE, "revoked_by": OPTIONAL_OBJECT_ID,
                         "revoked_token_hashes": {"bsonType": "array", "items": SHA256_HEX}}},
            "created_at": DATE, "updated_at": DATE,
        }),
        [
            IndexModel([("visit_number", ASCENDING)], name="visit_number_unique", unique=True),   # manual check-out
            # Business rule enforced by the database: at most one active visit per person,
            # even when two gates check the same person in at the same moment.
            IndexModel([("visitor_id", ASCENDING)], name="one_active_visit_per_visitor", unique=True,
                       partialFilterExpression={"status": "CHECKED_IN"}),
            IndexModel([("status", ASCENDING), ("check_in_at", DESCENDING)], name="status_check_in"),  # active list
            IndexModel([("check_in_at", DESCENDING)], name="check_in"),       # today / date range / trends / reports
            IndexModel([("visitor_id", ASCENDING), ("check_in_at", DESCENDING)], name="visitor_history"),
            IndexModel([("check_out_at", DESCENDING)], name="check_out",       # checked-out-today count
                       partialFilterExpression={"check_out_at": {"$type": "date"}}),
            IndexModel([("pass.token_hash", ASCENDING)], name="pass_token_unique", unique=True,  # QR check-out
                       partialFilterExpression={"pass.token_hash": {"$type": "string"}}),
            # v2: visit history filtered by host / department, newest first.
            IndexModel([("host_id", ASCENDING), ("check_in_at", DESCENDING)], name="host_history"),
            IndexModel([("department_id", ASCENDING), ("check_in_at", DESCENDING)], name="department_history"),
            # v3: a scanned pass that was replaced ("this badge is no longer valid").
            IndexModel([("pass.revoked_token_hashes", ASCENDING)], name="pass_revoked_tokens"),
            # v5 (Reports): the visit report's guard filter ("checked in OR out by", within the check-in
            # range) uses one index per $or branch; both bounded by check_in_at, so counts are index-only.
            IndexModel([("checked_in_by", ASCENDING), ("check_in_at", DESCENDING)], name="checked_in_by_history"),
            IndexModel([("checked_out_by", ASCENDING), ("check_in_at", DESCENDING)], name="checked_out_by_history"),
            # v5: gate filter (reports; also used by the visit history's gate filter, unindexed until now).
            IndexModel([("gate_id", ASCENDING), ("check_in_at", DESCENDING)], name="gate_history"),
        ],
    ),
    CollectionSpec(
        "watchlist",
        _schema(["identifier", "identity", "reason", "is_active", "created_by", "created_at"], {
            "identifier": TEXT,                   # "<TYPE>:<normalised number>"
            "identity": {"bsonType": "object", "required": ["type", "number"], "properties": {
                "type": {"enum": IDENTITY_TYPES}, "number": TEXT}},
            "name": OPTIONAL_TEXT, "name_search": OPTIONAL_TEXT,
            "reason": TEXT,
            "is_active": BOOL,                    # false = disabled (lifted); entries are never deleted
            "expires_at": OPTIONAL_DATE,
            "created_by": OBJECT_ID, "created_at": DATE,
            "updated_by": OPTIONAL_OBJECT_ID, "updated_at": OPTIONAL_DATE,
            "disabled_by": OPTIONAL_OBJECT_ID, "disabled_at": OPTIONAL_DATE, "disabled_reason": OPTIONAL_TEXT,
        }),
        [
            # Screening lookup; one active ban per identity (inactive history kept).
            IndexModel([("identifier", ASCENDING)], name="active_identifier_unique", unique=True,
                       partialFilterExpression={"is_active": True}),
            # v3: management screen: newest first; search by ID number (all statuses) or name.
            IndexModel([("created_at", DESCENDING), ("_id", DESCENDING)], name="newest_first"),
            IndexModel([("identifier", ASCENDING), ("created_at", DESCENDING)], name="identifier_history"),
            IndexModel([("name_search", ASCENDING)], name="name_prefix"),
        ],
    ),
    CollectionSpec(
        "photos",
        _schema(["storage_key", "visitor_id", "content_type", "size_bytes", "width", "height", "sha256",
                 "captured_by", "captured_at"], {
            "storage_key": {"bsonType": "string", "pattern": "^[0-9a-f]{32}$"},   # random file name, never exposed
            "visitor_id": OBJECT_ID,
            "visit_id": OPTIONAL_OBJECT_ID,
            "content_type": {"enum": PHOTO_TYPES},
            "size_bytes": {"bsonType": ["int", "long"], "minimum": 1},
            "width": {"bsonType": ["int", "long"], "minimum": 1},
            "height": {"bsonType": ["int", "long"], "minimum": 1},
            "sha256": SHA256_HEX,
            "captured_by": OBJECT_ID, "captured_at": DATE,
            "gate_id": OPTIONAL_OBJECT_ID,
        }),
        [
            IndexModel([("storage_key", ASCENDING)], name="storage_key_unique", unique=True),
            IndexModel([("visitor_id", ASCENDING), ("captured_at", DESCENDING)], name="visitor_photos"),
            IndexModel([("captured_at", ASCENDING)], name="captured_at"),       # retention clean-up (later phase)
        ],
    ),
    CollectionSpec(
        "hosts",
        _schema(["name", "name_search", "is_active", "created_at", "updated_at"], {
            "name": TEXT, "name_search": TEXT,
            "email": OPTIONAL_TEXT, "phone": OPTIONAL_TEXT,
            "department_id": OPTIONAL_OBJECT_ID,
            # v4: optional "Linked app account": an existing Admin/Guard user who gets this host's
            # in-app notifications. Hosts themselves never log in.
            "linked_user_id": OPTIONAL_OBJECT_ID,
            "is_active": BOOL,
            "created_at": DATE, "updated_at": DATE,
        }),
        [IndexModel([("is_active", ASCENDING), ("name_search", ASCENDING)], name="active_by_name")],  # host picker
    ),
    CollectionSpec(
        "departments",
        _schema(["name", "is_active", "created_at", "updated_at"], {
            "name": TEXT, "notification_email": OPTIONAL_TEXT, "is_active": BOOL,
            "created_at": DATE, "updated_at": DATE,
        }),
        [IndexModel([("name", ASCENDING)], name="name_unique", unique=True, collation=CASE_INSENSITIVE)],
    ),
    CollectionSpec(
        "gates",
        _schema(["name", "is_active", "created_at", "updated_at"], {
            "name": TEXT, "location": OPTIONAL_TEXT, "is_active": BOOL,
            "created_at": DATE, "updated_at": DATE,
        }),
        [IndexModel([("name", ASCENDING)], name="name_unique", unique=True, collation=CASE_INSENSITIVE)],
    ),
    CollectionSpec(
        "audit_logs",
        _schema(["timestamp", "action", "result", "actor", "resource"], {
            "timestamp": DATE,
            "action": TEXT,
            "result": {"enum": AUDIT_RESULTS},
            "actor": {"bsonType": "object", "properties": {"user_id": OPTIONAL_OBJECT_ID}},
            "resource": {"bsonType": "object", "properties": {"type": OPTIONAL_TEXT}},
        }),
        [
            IndexModel([("timestamp", DESCENDING)], name="timestamp"),                                   # audit list
            IndexModel([("actor.user_id", ASCENDING), ("timestamp", DESCENDING)], name="by_actor"),     # per user
            IndexModel([("resource.type", ASCENDING), ("resource.id", ASCENDING), ("timestamp", DESCENDING)],
                       name="by_resource"),                                              # record history
            IndexModel([("action", ASCENDING), ("timestamp", DESCENDING)], name="by_action"),           # event counts
        ],
    ),
    CollectionSpec(
        "notifications",
        _schema(["event_key", "type", "created_at", "data", "email"], {
            # One notification per event, enforced by a unique index:
            # "HOST_VISITOR_ARRIVAL:<visit id>", "DEPARTMENT_VISITOR_ARRIVAL:<visit id>",
            # "HOST_VISITOR_OVERSTAY:<visit id>", "DEPARTMENT_VISITOR_OVERSTAY:<visit id>".
            "event_key": TEXT,
            "type": {"enum": NOTIFICATION_TYPES},
            "recipient_user_id": OPTIONAL_OBJECT_ID,        # in-app recipient (host's linked app account)
            "visit_id": OPTIONAL_OBJECT_ID, "visitor_id": OPTIONAL_OBJECT_ID, "host_id": OPTIONAL_OBJECT_ID,
            "data": {"bsonType": "object"},                 # what the message shows (names, gate, time)
            "created_at": DATE,
            "read_at": OPTIONAL_DATE,
            "email": {"bsonType": "object", "required": ["status", "attempts"], "properties": {
                "status": {"enum": EMAIL_STATES},
                "to": OPTIONAL_TEXT,
                "attempts": {"bsonType": ["int", "long"], "minimum": 0},
                "next_attempt_at": OPTIONAL_DATE, "last_attempt_at": OPTIONAL_DATE,
                "lease_until": OPTIONAL_DATE, "sent_at": OPTIONAL_DATE,
                "reason": OPTIONAL_TEXT, "error": OPTIONAL_TEXT}},
        }),
        [
            IndexModel([("event_key", ASCENDING)], name="event_key_unique", unique=True),     # no duplicates
            IndexModel([("recipient_user_id", ASCENDING), ("created_at", DESCENDING)],        # the bell / list
                       name="recipient_newest"),
            IndexModel([("recipient_user_id", ASCENDING), ("read_at", ASCENDING)],            # unread count
                       name="recipient_unread"),
            IndexModel([("email.status", ASCENDING), ("email.next_attempt_at", ASCENDING)],   # e-mails due
                       name="email_due"),
        ],
    ),
    CollectionSpec(
        "entry_denials",
        # v6: one document per refused entry (reporting). Written after the audit entries, never instead of
        # them; append-only. ID numbers are stored masked only; no phone, photo, pass or request payload.
        _schema(["at", "reason", "source", "source_audit_id"], {
            "at": DATE,                                     # = the WATCHLIST_MATCH audit entry's timestamp
            "reason": {"enum": DENIAL_REASONS},
            "source": {"enum": DENIAL_SOURCES},
            "source_audit_id": OBJECT_ID,                   # the WATCHLIST_MATCH audit entry (dedup key)
            "visitor_id": OPTIONAL_OBJECT_ID, "visitor_name": OPTIONAL_TEXT,
            "identifier_masked": OPTIONAL_TEXT,
            "watchlist_id": OPTIONAL_OBJECT_ID,
            "gate_id": OPTIONAL_OBJECT_ID, "gate_name": OPTIONAL_TEXT,
            "operator_id": OPTIONAL_OBJECT_ID, "operator_username": OPTIONAL_TEXT, "operator_name": OPTIONAL_TEXT,
            "reason_code": {"enum": [*VISIT_REASONS, None]},
        }),
        [
            # Exactly one denial per WATCHLIST_MATCH: runtime writes and any number of backfill runs agree.
            IndexModel([("source_audit_id", ASCENDING)], name="source_audit_id_unique", unique=True),
            IndexModel([("at", DESCENDING), ("_id", DESCENDING)], name="newest_first"),    # counts, security report
        ],
    ),
    CollectionSpec("settings"),        # heterogeneous small documents: "org" settings, "schema" version
    CollectionSpec("counters", _schema(["seq"], {"seq": {"bsonType": ["int", "long"], "minimum": 0}})),
    CollectionSpec(
        "rate_limits",
        _schema(["count", "expires_at"], {"count": {"bsonType": ["int", "long"]}, "expires_at": DATE}),
        [IndexModel([("expires_at", ASCENDING)], name="expiry_ttl", expireAfterSeconds=0)],
    ),
]

COLLECTION_NAMES = [spec.name for spec in COLLECTIONS]
