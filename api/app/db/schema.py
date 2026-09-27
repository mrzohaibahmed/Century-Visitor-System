"""
Declarative schema for the NEW database (century_gate_vms): collections,
$jsonSchema validators and indexes, as approved in the architecture audit.

Validators check the essentials (required fields, types, enums) as a last line
of defence; full validation happens in the API's Pydantic models. Each index
names the query or constraint it exists for.

Not created yet (later phases): notifications (Phase 6) and the photo store
(Phase 4, pending the storage decision).

Bump SCHEMA_VERSION whenever this file changes; /health/ready reports a
database that has not been migrated to it.
"""
from dataclasses import dataclass, field

from pymongo import ASCENDING, DESCENDING, IndexModel

SCHEMA_VERSION = 1

# Case-insensitive uniqueness (e.g. "Admin" and "admin" are the same user).
# Queries must pass the same collation to use these indexes.
CASE_INSENSITIVE = {"locale": "en", "strength": 2}

ROLES = ["ADMIN", "GUARD"]
VISIT_STATUSES = ["SCHEDULED", "EXPECTED", "CHECKED_IN", "CHECKED_OUT", "CANCELLED", "EXPIRED", "NO_SHOW"]
IDENTITY_TYPES = ["CNIC", "PASSPORT", "OTHER"]
AUDIT_RESULTS = ["SUCCESS", "FAILURE", "DENIED"]

DATE = {"bsonType": "date"}
OPTIONAL_DATE = {"bsonType": ["date", "null"]}
OBJECT_ID = {"bsonType": "objectId"}
OPTIONAL_OBJECT_ID = {"bsonType": ["objectId", "null"]}
TEXT = {"bsonType": "string", "minLength": 1}
OPTIONAL_TEXT = {"bsonType": ["string", "null"]}
BOOL = {"bsonType": "bool"}
SHA256_HEX = {"bsonType": "string", "pattern": "^[0-9a-f]{64}$"}


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
            "visit_number": {"bsonType": "string", "pattern": "^V-[0-9]{4}-[0-9]{6,}$"},
            "visitor_id": OBJECT_ID,
            "host_id": OPTIONAL_OBJECT_ID,
            "department_id": OPTIONAL_OBJECT_ID,
            "gate_id": OPTIONAL_OBJECT_ID,
            "checkout_gate_id": OPTIONAL_OBJECT_ID,
            "status": {"enum": VISIT_STATUSES},
            "check_in_at": DATE,
            "check_out_at": OPTIONAL_DATE,
            "checked_in_by": OBJECT_ID,
            "checked_out_by": OPTIONAL_OBJECT_ID,
            "snapshot": {"bsonType": "object", "required": ["visitor_name"], "properties": {
                "visitor_name": TEXT}},
            "pass": {"bsonType": ["object", "null"], "properties": {"token_hash": SHA256_HEX}},
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
        ],
    ),
    CollectionSpec(
        "watchlist",
        _schema(["identifier", "identity", "reason", "is_active", "created_by", "created_at"], {
            "identifier": TEXT,                   # "<TYPE>:<normalised number>"
            "identity": {"bsonType": "object", "required": ["type", "number"], "properties": {
                "type": {"enum": IDENTITY_TYPES}, "number": TEXT}},
            "reason": TEXT,
            "is_active": BOOL,
            "expires_at": OPTIONAL_DATE,
            "created_by": OBJECT_ID, "created_at": DATE,
        }),
        [
            # Screening lookup; one active ban per identity (inactive history kept).
            IndexModel([("identifier", ASCENDING)], name="active_identifier_unique", unique=True,
                       partialFilterExpression={"is_active": True}),
        ],
    ),
    CollectionSpec(
        "hosts",
        _schema(["name", "name_search", "is_active", "created_at", "updated_at"], {
            "name": TEXT, "name_search": TEXT,
            "email": OPTIONAL_TEXT, "phone": OPTIONAL_TEXT,
            "department_id": OPTIONAL_OBJECT_ID,
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
    CollectionSpec("settings"),        # heterogeneous small documents: "org" settings, "schema" version
    CollectionSpec("counters", _schema(["seq"], {"seq": {"bsonType": ["int", "long"], "minimum": 0}})),
    CollectionSpec(
        "rate_limits",
        _schema(["count", "expires_at"], {"count": {"bsonType": ["int", "long"]}, "expires_at": DATE}),
        [IndexModel([("expires_at", ASCENDING)], name="expiry_ttl", expireAfterSeconds=0)],
    ),
]

COLLECTION_NAMES = [spec.name for spec in COLLECTIONS]
