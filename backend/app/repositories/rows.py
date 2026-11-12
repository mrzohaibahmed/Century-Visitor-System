"""Rows <-> the dictionaries ("documents") the services work with: "_id" is the record ID."""
from sqlalchemy import Row, Table

from app.repositories import ids


def as_doc(row: Row | None) -> dict | None:
    """A row as a document: its `id` under "_id"."""
    if row is None:
        return None
    doc = dict(row._mapping)
    if "id" in doc:
        doc["_id"] = doc.pop("id")
    return doc


def new_row(table: Table, doc: dict, columns: dict | None = None) -> dict:
    """The row to insert for `doc`, with its ID written to doc["_id"]: a new one, or the one the document
    already has. `columns`: the document already flattened into columns
    (default: the document itself). A key that is not a column of the table is a mistake, so it is refused,
    not dropped."""
    doc["_id"] = doc.get("_id") or ids.new_id()
    flat = columns if columns is not None else doc
    row = {("id" if key == "_id" else key): value for key, value in flat.items()} | {"id": doc["_id"]}
    return checked(table, row)


def checked(table: Table, row: dict) -> dict:
    unknown = set(row) - set(table.c.keys())
    if unknown:
        raise ValueError(f"{table.name} has no column(s) {sorted(unknown)}")
    return row


def like_prefix(value: str) -> str:
    """A LIKE pattern for "starts with `value`" (%, _ and [ matched literally; escape character \\)."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace("[", "\\[") + "%"


def identity_columns(doc: dict) -> dict:
    """A document with its "identity": {"type", "number"} (or None) as identity_type / identity_number."""
    flat = {key: value for key, value in doc.items() if key != "identity"}
    if "identity" in doc:
        identity = doc["identity"] or {}
        flat |= {"identity_type": identity.get("type"), "identity_number": identity.get("number")}
    return flat


def with_identity(doc: dict) -> dict:
    """The reverse: identity_type / identity_number back into "identity" (None when not set)."""
    kind, number = doc.pop("identity_type", None), doc.pop("identity_number", None)
    doc["identity"] = {"type": kind, "number": number} if kind is not None else None
    return doc
