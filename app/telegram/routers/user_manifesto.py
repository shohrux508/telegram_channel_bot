"""
app.telegram.routers.user_manifesto — Получение манифеста по deep link.

Обрабатывает /start {short_code} — отправляет MediaGroup с фотографиями.
Поддерживает разбиение на группы по 10 фото (лимит Telegram).
"""

from __future__ import annotations

from aiogram import Router, types
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import InputMediaPhoto
from loguru import logger

from app.container import Container


router = Router()


# ── /start с deep_link — получение манифеста ─────────────────────────────


@router.message(CommandStart(deep_link=True))
async def cmd_start_deeplink(
    message: types.Message,
    command: CommandObject,
    container: Container,
):
    """Обработка /start {short_code} — отправить коллекцию фотографий."""
    short_code = command.args
    if not short_code:
        return  # Пропустить — обработает другой роутер

    user = message.from_user
    user_id = user.id if user else 0
    full_name = user.full_name if user else "Unknown"
    username = user.username if user else None

    manifesto_svc = container.manifesto

    # Получить коллекцию
    collection = await manifesto_svc.get_collection(short_code)

    if collection is None:
        await message.answer("❌ Манифест не найден. Проверьте ссылку.")
        logger.warning(
            "Манифест не найден: code={}, user_id={}",
            short_code,
            user_id,
        )
        return

    # Логируем просмотр (сохраняет пользователя + инкремент)
    views = await manifesto_svc.log_view(
        short_code=short_code,
        user_id=user_id,
        full_name=full_name,
        username=username,
    )

    file_ids = collection.file_ids

    # Telegram ограничение: максимум 10 фото в MediaGroup
    # Разбиваем на чанки по 10
    chunks = [file_ids[i:i + 10] for i in range(0, len(file_ids), 10)]

    for chunk in chunks:
        media_group = [InputMediaPhoto(media=fid) for fid in chunk]
        await message.answer_media_group(media=media_group)

    logger.info(
        "Манифест отправлен: code={}, user='{}' ({}), photos={}, views={}",
        short_code,
        full_name,
        user_id,
        len(file_ids),
        views,
    )
