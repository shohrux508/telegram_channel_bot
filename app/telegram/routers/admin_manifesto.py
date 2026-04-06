"""
app.telegram.routers.admin_manifesto — Админский FSM для создания манифестов.

Команды:
    /manifesto — начать загрузку фотографий
    /users    — показать список пользователей

FSM:
    WaitingForPhotos → фото по одному → [Нет, получить ссылку] → ссылка
"""

from __future__ import annotations

from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from loguru import logger
from typing import Any

from app.config import settings
from app.container import Container


router = Router()


# ── Фильтр: только администратор ─────────────────────────────────────────


def _is_admin(event: types.Message | CallbackQuery) -> bool:
    """Проверяет, что событие от администратора."""
    user = event.from_user
    return user is not None and user.id == settings.MANIFESTO_ADMIN_ID


# ── FSM States ───────────────────────────────────────────────────────────


class ManifestoFSM(StatesGroup):
    waiting_for_media = State()
    waiting_for_price = State()


# ── Клавиатуры ───────────────────────────────────────────────────────────


def _finish_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Сгенерировать ссылку (Free)", callback_data="manifesto_free")],
        [InlineKeyboardButton(text="💰 Сделать платным", callback_data="manifesto_paid")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="manifesto_cancel")]
    ])


# ── /manifesto — начать загрузку ─────────────────────────────────────────


@router.message(Command("manifesto"), _is_admin)
async def cmd_manifesto(message: types.Message, state: FSMContext):
    """Запуск FSM — ожидание фотографий от администратора."""
    await state.clear()
    await state.update_data(media=[], status_message_id=None)
    await state.set_state(ManifestoFSM.waiting_for_media)

    await message.answer(
        "📸 Отправьте медиа для манифеста (фото, видео, файлы).\n"
        "Можете отправлять по одному — я буду считать.\n"
        "Когда закончите, выберите действие на клавиатуре ниже.",
    )
    logger.info("Админ {} начал создание манифеста", message.from_user.id)


# ── Приём медиа ──────────────────────────────────────────────────────────

@router.message(ManifestoFSM.waiting_for_media, F.photo | F.document | F.video, _is_admin)
async def handle_media(message: types.Message, state: FSMContext):
    """Приём каждого медиа-файла."""
    media_item = {}
    if message.photo:
        media_item = {"type": "photo", "content": message.photo[-1].file_id}
    elif message.document:
        media_item = {"type": "document", "content": message.document.file_id}
    elif message.video:
        media_item = {"type": "video", "content": message.video.file_id}
    else:
        return

    data = await state.get_data()
    media_list: list[dict] = data.get("media", [])
    media_list.append(media_item)
    status_message_id: int | None = data.get("status_message_id")

    await state.update_data(media=media_list)

    count = len(media_list)
    text = f"✅ Принято файлов: {count}. Ещё есть?"

    # Пытаемся отредактировать предыдущее статусное сообщение
    if status_message_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=status_message_id,
                text=text,
                reply_markup=_finish_keyboard(),
            )
            return
        except Exception:
            pass  # Не удалось — отправим новое

    # Отправляем новое статусное сообщение
    status_msg = await message.answer(text, reply_markup=_finish_keyboard())
    await state.update_data(status_message_id=status_msg.message_id)


# ── Callbacks: Управление публикацией ────────────────────────────────────

@router.callback_query(ManifestoFSM.waiting_for_media, F.data == "manifesto_cancel", _is_admin)
async def cancel_manifesto(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Создание манифеста отменено.")
    await callback.answer()

@router.callback_query(ManifestoFSM.waiting_for_media, F.data == "manifesto_paid", _is_admin)
async def make_paid_manifesto(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    media_list: list[dict] = data.get("media", [])
    if not media_list:
        await callback.answer("⚠️ Вы не загрузили ни одного файла!", show_alert=True)
        return
    
    await state.set_state(ManifestoFSM.waiting_for_price)
    await callback.message.edit_text("💰 Отправьте стоимость в Telegram Звездах (XTR) числом:")
    await callback.answer()

@router.message(ManifestoFSM.waiting_for_price, _is_admin)
async def handle_price(message: types.Message, state: FSMContext, container: Container):
    if not message.text or not message.text.isdigit():
        await message.answer("⚠️ Пожалуйста, отправьте корректное целое число звезд (например, 50).")
        return
    
    price = int(message.text)
    if price < 1 or price > 10000:
        await message.answer("⚠️ Количество звезд должно быть от 1 до 10000.")
        return
    
    await _finalize_manifesto(message.chat.id, message.bot, state, container, is_paid=True, price=price)

@router.callback_query(ManifestoFSM.waiting_for_media, F.data == "manifesto_free", _is_admin)
async def finish_free_manifesto(callback: CallbackQuery, state: FSMContext, container: Container):
    data = await state.get_data()
    media_list: list[dict] = data.get("media", [])
    if not media_list:
        await callback.answer("⚠️ Вы не загрузили ни одного файла!", show_alert=True)
        return
    
    # Редактируем сообщение, чтобы убрать кнопки
    await callback.message.edit_reply_markup(reply_markup=None) 
    await callback.answer()
    await _finalize_manifesto(callback.message.chat.id, callback.bot, state, container, is_paid=False, price=0)

async def _finalize_manifesto(chat_id: int, bot: Any, state: FSMContext, container: Container, is_paid: bool, price: int):
    data = await state.get_data()
    media_list: list[dict] = data.get("media", [])
    
    manifesto_svc = container.manifesto
    short_code = await manifesto_svc.create_collection(
        media=media_list, 
        owner_id=settings.MANIFESTO_ADMIN_ID,
        is_paid=is_paid,
        price=price
    )
    
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={short_code}"
    
    type_str = f"Платный ({price} XTR)" if is_paid else "Бесплатный"
    
    await bot.send_message(
        chat_id=chat_id,
        text=f"🎉 Манифест создан!\n\n"
        f"📊 Контента: {len(media_list)}\n"
        f"💰 Тип: {type_str}\n"
        f"🔗 Ссылка: {hcode(link)}\n\n"
        f"Отправьте эту ссылку друзьям!",
        parse_mode="HTML"
    )
    
    await state.clear()
    logger.info("Манифест создан: code={}, media={}, price={}", short_code, len(media_list), price)

# ── /users — список пользователей ────────────────────────────────────────


import html
from aiogram.utils.markdown import hbold, hcode, hlink


@router.message(Command("users"), _is_admin)
async def cmd_users(message: types.Message, container: Container):
    """Показать список всех пользователей, нажавших /start."""
    manifesto_svc = container.manifesto
    users = await manifesto_svc.get_all_users()

    if not users:
        await message.answer("📋 Пользователей пока нет.")
        return

    # Формируем текстовый список
    lines = [f"👥 {hbold('Список пользователей:')}\n"]
    for i, user in enumerate(users, 1):
        username_part = f" (@{html.escape(user.username)})" if user.username else ""
        lines.append(
            f"{i}. {hbold(user.full_name)}{username_part}\n"
            f"   ID: {hcode(user.user_id)} | Манифест: {hcode(user.short_code)}"
        )


    # Telegram ограничение — 4096 символов
    text = "\n".join(lines)
    if len(text) > 4000:
        # Разбиваем на части
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0

        for line in lines:
            if current_len + len(line) + 1 > 4000:
                chunks.append("\n".join(current))
                current = [line]
                current_len = len(line)
            else:
                current.append(line)
                current_len += len(line) + 1

        if current:
            chunks.append("\n".join(current))

        for chunk in chunks:
            await message.answer(chunk, parse_mode="HTML")
    else:
        await message.answer(text, parse_mode="HTML")

