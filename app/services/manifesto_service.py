"""
app.services.manifesto_service — Бизнес-логика Manifesto Publisher.

Управляет коллекциями фотографий: создание, получение, просмотры,
а также учёт пользователей, перешедших по deep link.

Все данные хранятся в Redis через CacheService.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

from app.config import settings
from app.services.models import ManifestoCollection, ManifestoUser

if TYPE_CHECKING:
    from libs.utils.cache import CacheService


class ManifestoService:
    """Сервис для работы с манифестами и пользователями."""

    # ── Redis key patterns ───────────────────────────────────────────────
    _KEY_COLLECTION = "manifesto:{code}"       # -> JSON ManifestoCollection
    _KEY_INDEX = "manifesto:index"             # -> Hash {code: created_at}
    _KEY_VIEWS = "manifesto:views:{code}"      # -> int (атомарный счётчик)
    _KEY_USERS = "manifesto:users"             # -> Hash {user_id: JSON ManifestoUser}
    _KEY_HOT_CACHE = "manifesto:hot:{code}"    # -> JSON media list (TTL 60s)
    _KEY_ACCESS = "manifesto:access:{code}"    # -> Set {user_id}

    def __init__(self, cache: CacheService) -> None:
        self._cache = cache
        logger.info("ManifestoService инициализирован")

    # ── Создание коллекции ───────────────────────────────────────────────

    async def create_collection(
        self,
        media: list[dict],
        owner_id: int | None = None,
        is_paid: bool = False,
        price: int = 0
    ) -> str:
        """Создать коллекцию контента.

        Returns:
            short_code — уникальный код для deep link.
        """
        short_code = await self._generate_unique_code()

        collection = ManifestoCollection(
            short_code=short_code,
            media=media,
            owner_id=owner_id,
            is_paid=is_paid,
            price=price
        )

        # Сохраняем коллекцию
        key = self._KEY_COLLECTION.format(code=short_code)
        await self._cache.set_json(key, collection.model_dump(mode="json"))

        # Добавляем в индекс
        await self._cache.hset(
            self._KEY_INDEX,
            short_code,
            collection.created_at.isoformat(),
        )

        logger.info(
            "Создан манифест: code={}, media_count={}, is_paid={}, price={}",
            short_code,
            len(media),
            is_paid,
            price
        )
        return short_code

    # ── Получение коллекции ──────────────────────────────────────────────

    async def get_collection(self, short_code: str) -> ManifestoCollection | None:
        """Получить коллекцию по short_code.

        Если манифест «горячий» (>10 просмотров), он кэшируется на 60с.
        """
        # Попробовать горячий кэш
        hot_key = self._KEY_HOT_CACHE.format(code=short_code)
        cached = await self._cache.get_json(hot_key)
        if cached is not None:
            logger.debug("Горячий кэш hit: {}", short_code)
            return ManifestoCollection(**cached)

        # Основное хранилище
        key = self._KEY_COLLECTION.format(code=short_code)
        data = await self._cache.get_json(key)
        if data is None:
            return None

        collection = ManifestoCollection(**data)

        # Если «горячий» — закэшировать на 60с
        views_key = self._KEY_VIEWS.format(code=short_code)
        views_raw = await self._cache.get_val(views_key)
        views = int(views_raw) if views_raw else 0
        if views > 10:
            await self._cache.set_json(hot_key, data, ttl=60)

        return collection

    # ── Логирование просмотра ────────────────────────────────────────────

    async def log_view(
        self,
        short_code: str,
        user_id: int,
        full_name: str,
        username: str | None = None,
    ) -> int:
        """Инкремент счётчика просмотров + сохранение информации о пользователе.

        Returns:
            Новое значение счётчика.
        """
        # Атомарный инкремент просмотров
        views_key = self._KEY_VIEWS.format(code=short_code)
        new_count = await self._cache.increment(views_key)

        # Обновить views_count в основной записи
        key = self._KEY_COLLECTION.format(code=short_code)
        data = await self._cache.get_json(key)
        if data:
            data["views_count"] = new_count
            await self._cache.set_json(key, data)

        # Сохранить пользователя
        await self.save_user(
            user_id=user_id,
            full_name=full_name,
            username=username,
            short_code=short_code,
        )

        logger.info(
            "Просмотр манифеста: code={}, user_id={}, name='{}', views={}",
            short_code,
            user_id,
            full_name,
            new_count,
        )
        return new_count

    # ── Монетизация и Доступ ─────────────────────────────────────────────

    async def check_access(self, user_id: int, short_code: str) -> bool:
        """Проверка, оплатил ли пользователь этот манифест."""
        # Для бесплатного контента проверка не требуется в вызывающем коде, 
        # но на всякий случай можно будет проверять sismember
        redis = await self._cache._get_redis()
        access_key = self._KEY_ACCESS.format(code=short_code)
        return await redis.sismember(access_key, str(user_id))

    async def grant_access(self, user_id: int, short_code: str, amount: int) -> None:
        """Регистрация покупки и выдача доступа."""
        redis = await self._cache._get_redis()
        
        # 1. Записать в набор получивших доступ
        access_key = self._KEY_ACCESS.format(code=short_code)
        await redis.sadd(access_key, str(user_id))

        # 2. Обновить total_earned
        key = self._KEY_COLLECTION.format(code=short_code)
        data = await self._cache.get_json(key)
        if data:
            data["total_earned"] = data.get("total_earned", 0) + amount
            await self._cache.set_json(key, data)

        logger.info("Пользователь {} купил доступ к {} за {} XTR", user_id, short_code, amount)

    async def add_donation(self, user_id: int, short_code: str, amount: int) -> None:
        """Добавление доната (без выдачи доступа, т.к. может быть бесплатный)."""
        key = self._KEY_COLLECTION.format(code=short_code)
        data = await self._cache.get_json(key)
        if data:
            data["total_earned"] = data.get("total_earned", 0) + amount
            await self._cache.set_json(key, data)
        
        logger.info("Пользователь {} задонатил {} XTR манифесту {}", user_id, amount, short_code)

    # ── Управление пользователями ────────────────────────────────────────

    async def save_user(
        self,
        user_id: int,
        full_name: str,
        username: str | None = None,
        short_code: str = "",
    ) -> None:
        """Сохранить информацию о пользователе."""
        user = ManifestoUser(
            user_id=user_id,
            full_name=full_name,
            username=username,
            short_code=short_code,
        )
        await self._cache.hset(
            self._KEY_USERS,
            str(user_id),
            user.model_dump_json(),
        )
        logger.debug("Пользователь сохранён: {} ({})", full_name, user_id)

    async def get_all_users(self) -> list[ManifestoUser]:
        """Получить список всех пользователей, нажавших /start."""
        raw = await self._cache.hgetall(self._KEY_USERS)
        users: list[ManifestoUser] = []
        for _, json_str in raw.items():
            try:
                import json
                users.append(ManifestoUser(**json.loads(json_str)))
            except Exception as e:
                logger.warning("Ошибка десериализации пользователя: {}", e)
        return users

    # ── Список всех манифестов ────────────────────────────────────────────

    async def list_all(self) -> list[dict]:
        """Получить все манифесты для отображения в таблице."""
        index = await self._cache.hgetall(self._KEY_INDEX)
        result: list[dict] = []

        for code, created_at in index.items():
            views_key = self._KEY_VIEWS.format(code=code)
            views_raw = await self._cache.get_val(views_key)
            views = int(views_raw) if views_raw else 0

            # Получить атрибуты коллекции
            key = self._KEY_COLLECTION.format(code=code)
            data = await self._cache.get_json(key)
            media_count = len(data.get("media", [])) if data else 0
            is_paid = data.get("is_paid", False) if data else False
            price = data.get("price", 0) if data else 0
            revenue = data.get("total_earned", 0) if data else 0

            m_type = "💰 Paid" if is_paid else "🆓 Free"

            result.append({
                "Code": code,
                "Type": m_type,
                "Price (XTR)": str(price) if is_paid else "-",
                "Items": str(media_count),
                "Views": str(views),
                "Revenue (XTR)": str(revenue),
            })

        return result

    # ── Приватные методы ─────────────────────────────────────────────────

    async def _generate_unique_code(self) -> str:
        """Генерация уникального short_code."""
        for _ in range(10):
            code = secrets.token_urlsafe(settings.MANIFESTO_CODE_LENGTH)[:settings.MANIFESTO_CODE_LENGTH]
            key = self._KEY_COLLECTION.format(code=code)
            if not await self._cache.exists(key):
                return code
        # Fallback: удлинённый код
        return secrets.token_urlsafe(16)[:16]
