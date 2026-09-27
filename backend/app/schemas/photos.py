"""Visitor photos: metadata only. The image is fetched separately (GET /photos/{id})."""
from datetime import datetime

from pydantic import BaseModel


class PhotoOut(BaseModel):
    id: str
    captured_at: datetime
    width: int
    height: int

    @classmethod
    def from_doc(cls, d: dict) -> "PhotoOut":
        return cls(id=str(d["_id"]), captured_at=d["captured_at"], width=d["width"], height=d["height"])
