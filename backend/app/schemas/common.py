"""Shared request/response building blocks."""
import re
from typing import Annotated

from bson import ObjectId
from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class StrictModel(BaseModel):
    """Request bodies: unknown fields are rejected (no mass assignment)."""
    model_config = ConfigDict(extra="forbid")


def _object_id(value: str) -> str:
    if not ObjectId.is_valid(value):
        raise ValueError("Not a valid id.")
    return value


def _email(value: str) -> str:
    value = value.strip()
    if len(value) > 254 or not _EMAIL.match(value):
        raise ValueError("Not a valid email address.")
    return value.lower()


IdStr = Annotated[str, AfterValidator(_object_id)]
Email = Annotated[str, AfterValidator(_email)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
OptionalLongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None
