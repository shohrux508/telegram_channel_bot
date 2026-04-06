"""
app.telegram.routers.user_manifesto — Получение манифеста по deep link.
Обрабатывает бесплатные, платные манифесты и выдачу контента.
"""

from __future__ import annotations
from typing import Any

from aiogram import Router, types, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import InputMediaPhoto, InputMediaDocument, InputMediaVideo
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types import LabeledPrice
from loguru import logger

from app.container import Container

router = Router()

def get_donate_keyboard(short_code: str) -> InlineKeyboardMarkup:
    """Клавиатура для генерации инвойса доната."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🌟 50 XTR", callback_data=f"ask_donate:50:{short_code}"),
            InlineKeyboardButton(text="🌟 100 XTR", callback_data=f"ask_donate:100:{short_code}")
        ],
        [InlineKeyboardButton(text="🌟 500 XTR", callback_data=f"ask_donate:500:{short_code}")]
    ])

@router.message(CommandStart(deep_link=True))
async def cmd_start_deeplink(
    message: types.Message,
    command: CommandObject,
    container: Container,
):
    short_code = command.args
    if not short_code:
        return
        
    user_id = message.from_user.id
    manifesto_svc = container.manifesto

    collection = await manifesto_svc.get_collection(short_code)
    if collection is None:
        await message.answer("❌ Манифест не найден.")
        return

    # Логируем просмотр
    await manifesto_svc.log_view(
        short_code=short_code,
        user_id=user_id,
        full_name=message.from_user.full_name,
        username=message.from_user.username,
    )

    is_paid = collection.is_paid
    has_access = False
    
    if is_paid:
        has_access = await manifesto_svc.check_access(user_id, short_code)
        
    # Сценарий Б: Paywall
    if is_paid and not has_access:
        # Lazy Paywall (Preview)
        preview_img = None
        for item in collection.media:
            if item.type == "photo":
                preview_img = item.content
                break
                
        prices = [LabeledPrice(label=f"Доступ к манифесту", amount=collection.price)]
        
        if preview_img:
            # Отправляем инвойс с фото-превью (photo_url в send_invoice требует http url, 
            # поэтому мы можем просто отправить фото сначала, а затем инвойс)
            # Но красивее сделать один инвойс. Попробуем без картинки внутри инвойса, 
            # а просто отправить превью обычным сообщением.
            await message.answer_photo(
                photo=preview_img,
                caption="🔒 Этот контент платный. Для доступа необходимо его приобрести."
            )
            
        await message.answer_invoice(
            title="Доступ к манифесту",
            description=f"Откройте полный доступ за {collection.price} Telegram Звезд",
            payload=f"buy:{short_code}",
            provider_token="", # Stars не требуют provider_token
            currency="XTR",
            prices=prices
        )
        return

    # Сценарий А (или куплено): Выдача
    await send_manifesto_content(message, collection, container)
    
async def send_manifesto_content(message: types.Message, collection: Any, container: Container):
    """Сборка и отправка контента."""
    media_objects = collection.media
    if not media_objects:
        await message.answer("Манифест пуст.")
        return
        
    media_group = []
    
    for item in media_objects:
        if item.type == "photo":
            media_group.append(InputMediaPhoto(media=item.content))
        elif item.type == "document":
            media_group.append(InputMediaDocument(media=item.content))
        elif item.type == "video":
            media_group.append(InputMediaVideo(media=item.content))
            
    # Разбиваем на чанки по 10
    chunks = [media_group[i:i + 10] for i in range(0, len(media_group), 10)]
    for chunk in chunks:
        await message.answer_media_group(media=chunk)
        
    # Предложить донат для бесплатного
    if not collection.is_paid:
        await message.answer(
            "🌟 Если вам понравилось, вы можете поддержать автора:",
            reply_markup=get_donate_keyboard(collection.short_code)
        )

# Обработка кнопок доната
@router.callback_query(F.data.startswith("ask_donate:"))
async def donate_callback(callback: types.CallbackQuery):
    _, amount_str, short_code = callback.data.split(":")
    amount = int(amount_str)
    
    prices = [LabeledPrice(label="Пожертвование", amount=amount)]
    
    await callback.message.answer_invoice(
        title="Пожертвование",
        description=f"Спасибо за вашу поддержку ({amount} XTR)!",
        payload=f"donate:{short_code}:{amount}",
        provider_token="",
        currency="XTR",
        prices=prices
    )
    await callback.answer()
