"""
app.services.models — Pydantic-модели для Manifesto Publisher.

ManifestoCollection — коллекция фотографий с коротким кодом.
ManifestoUser — пользователь, перешедший по ссылке.
"""

from __future__ import annotations

from datetime import datetime, UTC

from pydantic import BaseModel, Field


class ManifestoCollection(BaseModel):
    """Коллекция фотографий манифеста."""

    short_code: str
    file_ids: list[str]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    views_count: int = 0


class ManifestoUser(BaseModel):
    """Пользователь, нажавший /start по ссылке манифеста."""

    user_id: int
    full_name: str
    username: str | None = None
    short_code: str          # какой манифест просматривал
    first_seen: datetime = Field(default_factory=lambda: datetime.now(UTC))
