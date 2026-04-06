"""
tests.test_manifesto_service — Тесты для ManifestoService.

Используем мок CacheService для изоляции от Redis.
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from app.services.manifesto_service import ManifestoService
from app.services.models import ManifestoCollection, ManifestoUser


# ── Фикстуры ────────────────────────────────────────────────────────────


@pytest.fixture
def mock_cache():
    """Мок CacheService с хранилищем в памяти."""
    cache = AsyncMock()

    # Внутреннее хранилище для имитации Redis
    _store: dict[str, str] = {}
    _hashes: dict[str, dict[str, str]] = {}
    _counters: dict[str, int] = {}

    async def _get_val(key: str):
        return _store.get(key)

    async def _set_val(key: str, value: str, *, ttl=None):
        _store[key] = value

    async def _get_json(key: str):
        val = _store.get(key)
        if val is None:
            return None
        return json.loads(val)

    async def _set_json(key: str, data, *, ttl=None):
        _store[key] = json.dumps(data, ensure_ascii=False, default=str)

    async def _exists(key: str):
        return key in _store

    async def _increment(key: str, amount: int = 1):
        _counters[key] = _counters.get(key, 0) + amount
        _store[key] = str(_counters[key])
        return _counters[key]

    async def _hset(key: str, field: str, value: str):
        if key not in _hashes:
            _hashes[key] = {}
        _hashes[key][field] = value

    async def _hgetall(key: str):
        return _hashes.get(key, {})

    async def _delete(key: str):
        return _store.pop(key, None) is not None

    cache.get_val = AsyncMock(side_effect=_get_val)
    cache.set_val = AsyncMock(side_effect=_set_val)
    cache.get_json = AsyncMock(side_effect=_get_json)
    cache.set_json = AsyncMock(side_effect=_set_json)
    cache.exists = AsyncMock(side_effect=_exists)
    cache.increment = AsyncMock(side_effect=_increment)
    cache.hset = AsyncMock(side_effect=_hset)
    cache.hgetall = AsyncMock(side_effect=_hgetall)
    cache.delete = AsyncMock(side_effect=_delete)

    # Expose internal stores for assertions
    cache._store = _store
    cache._hashes = _hashes
    cache._counters = _counters

    return cache


@pytest_asyncio.fixture
async def service(mock_cache):
    """ManifestoService с мок-кэшем."""
    return ManifestoService(cache=mock_cache)


# ── Тесты: создание коллекции ────────────────────────────────────────────


class TestCreateCollection:
    @pytest.mark.asyncio
    async def test_creates_collection_with_code(self, service: ManifestoService):
        """Создание коллекции возвращает short_code."""
        media = [{"type": "photo", "content": "photo_1"}]
        code = await service.create_collection(media)

        assert code is not None
        assert len(code) > 0

    @pytest.mark.asyncio
    async def test_collection_stored_in_cache(self, service: ManifestoService, mock_cache):
        """Коллекция сохраняется в кэш."""
        media = [{"type": "photo", "content": "photo_1"}]
        code = await service.create_collection(media)

        # Проверяем, что set_json был вызван
        key = f"manifesto:{code}"
        assert key in mock_cache._store

        # Проверяем содержимое
        stored = json.loads(mock_cache._store[key])
        assert stored["short_code"] == code
        assert stored["media"] == media

    @pytest.mark.asyncio
    async def test_collection_added_to_index(self, service: ManifestoService, mock_cache):
        """Коллекция добавляется в индекс."""
        code = await service.create_collection([{"type": "photo", "content": "photo_1"}])

        index = mock_cache._hashes.get("manifesto:index", {})
        assert code in index

    @pytest.mark.asyncio
    async def test_unique_codes(self, service: ManifestoService):
        """Каждый вызов генерирует уникальный код."""
        codes = set()
        for _ in range(5):
            code = await service.create_collection([{"type": "photo", "content": "photo"}])
            codes.add(code)

        assert len(codes) == 5


# ── Тесты: получение коллекции ───────────────────────────────────────────


class TestGetCollection:
    @pytest.mark.asyncio
    async def test_get_existing_collection(self, service: ManifestoService):
        """Получение существующей коллекции."""
        media = [{"type": "photo", "content": "photo_1"}]
        code = await service.create_collection(media)

        result = await service.get_collection(code)
        assert result is not None
        assert result.short_code == code
        assert len(result.media) == 1
        assert result.media[0].content == "photo_1"

    @pytest.mark.asyncio
    async def test_get_nonexistent_collection(self, service: ManifestoService):
        """Получение несуществующей коллекции."""
        result = await service.get_collection("nonexistent_code")
        assert result is None


# ── Тесты: просмотры ────────────────────────────────────────────────────


class TestLogView:
    @pytest.mark.asyncio
    async def test_increments_view_count(self, service: ManifestoService):
        """log_view инкрементирует счётчик."""
        code = await service.create_collection([{"type": "photo", "content": "photo"}])

        views = await service.log_view(code, user_id=123, full_name="Test User")
        assert views == 1

        views = await service.log_view(code, user_id=456, full_name="Another User")
        assert views == 2

    @pytest.mark.asyncio
    async def test_saves_user_on_view(self, service: ManifestoService, mock_cache):
        """log_view сохраняет информацию о пользователе."""
        code = await service.create_collection([{"type": "photo", "content": "photo"}])

        await service.log_view(
            code,
            user_id=123,
            full_name="John Doe",
            username="johndoe",
        )

        users_hash = mock_cache._hashes.get("manifesto:users", {})
        assert "123" in users_hash

        user_data = json.loads(users_hash["123"])
        assert user_data["full_name"] == "John Doe"
        assert user_data["username"] == "johndoe"


# ── Тесты: пользователи ─────────────────────────────────────────────────


class TestUsers:
    @pytest.mark.asyncio
    async def test_get_all_users(self, service: ManifestoService):
        """Получение списка всех пользователей."""
        code = await service.create_collection([{"type": "photo", "content": "photo"}])

        await service.log_view(code, user_id=1, full_name="User 1")
        await service.log_view(code, user_id=2, full_name="User 2")

        users = await service.get_all_users()
        assert len(users) == 2

        names = {u.full_name for u in users}
        assert "User 1" in names
        assert "User 2" in names

    @pytest.mark.asyncio
    async def test_empty_users(self, service: ManifestoService):
        """Пустой список пользователей."""
        users = await service.get_all_users()
        assert users == []


# ── Тесты: list_all ─────────────────────────────────────────────────────


class TestListAll:
    @pytest.mark.asyncio
    async def test_list_all_with_data(self, service: ManifestoService):
        """list_all возвращает все манифесты."""
        await service.create_collection([{"type": "photo", "content": "p1"}])
        await service.create_collection([])

        result = await service.list_all()
        assert len(result) == 2

        # Проверяем структуру
        row = result[0]
        assert "Code" in row
        assert "Type" in row
        assert "Price (XTR)" in row
        assert "Items" in row
        assert "Views" in row
        assert "Revenue (XTR)" in row

    @pytest.mark.asyncio
    async def test_list_all_empty(self, service: ManifestoService):
        """list_all при отсутствии данных."""
        result = await service.list_all()
        assert result == []
