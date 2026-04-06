"""
app.services.models — Pydantic-модели для Manifesto Publisher.

ManifestoCollection — коллекция фотографий с коротким кодом.
ManifestoUser — пользователь, перешедший по ссылке.
"""

from __future__ import annotations

from datetime import datetime, UTC

from pydantic import BaseModel, Field


class ManifestoMedia(BaseModel):
    """Единица медиа-контента (фото, документ, видео)."""
    type: str     # 'photo', 'document', 'video'
    content: str  # file_id

class ManifestoCollection(BaseModel):
    """Коллекция контента манифеста."""
    short_code: str
    media: list[ManifestoMedia] = Field(default_factory=list)
    owner_id: int | None = None
    is_paid: bool = False
    price: int = 0
    total_earned: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    views_count: int = 0


class ManifestoUser(BaseModel):
    """Пользователь, нажавший /start по ссылке манифеста."""

    user_id: int
    full_name: str
    username: str | None = None
    short_code: str          # какой манифест просматривал
    first_seen: datetime = Field(default_factory=lambda: datetime.now(UTC))
