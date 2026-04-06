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
    waiting_for_photos = State()


# ── Клавиатуры ───────────────────────────────────────────────────────────


def _finish_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🔗 Нет, получить ссылку",
            callback_data="finish_manifesto",
        )]
    ])


# ── /manifesto — начать загрузку ─────────────────────────────────────────


@router.message(Command("manifesto"), _is_admin)
async def cmd_manifesto(message: types.Message, state: FSMContext):
    """Запуск FSM — ожидание фотографий от администратора."""
    await state.clear()
    await state.update_data(file_ids=[], status_message_id=None)
    await state.set_state(ManifestoFSM.waiting_for_photos)

    await message.answer(
        "📸 Отправьте фото для манифеста.\n"
        "Можете отправлять по одному — я буду считать.\n"
        "Когда закончите, нажмите кнопку ниже.",
    )
    logger.info("Админ {} начал создание манифеста", message.from_user.id)


# ── Приём фото ───────────────────────────────────────────────────────────


@router.message(ManifestoFSM.waiting_for_photos, F.photo, _is_admin)
async def handle_photo(message: types.Message, state: FSMContext):
    """Приём каждого фото — извлекаем лучшее качество."""
    # Лучшее качество — последний элемент
    file_id = message.photo[-1].file_id

    data = await state.get_data()
    file_ids: list[str] = data.get("file_ids", [])
    file_ids.append(file_id)
    status_message_id: int | None = data.get("status_message_id")

    await state.update_data(file_ids=file_ids)

    count = len(file_ids)
    text = f"✅ Принято фото: {count}. Ещё есть?"

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


# ── Callback: завершить и получить ссылку ────────────────────────────────


@router.callback_query(
    ManifestoFSM.waiting_for_photos,
    F.data == "finish_manifesto",
    _is_admin,
)
async def finish_manifesto(callback: CallbackQuery, state: FSMContext, container: Container):
    """Завершение загрузки — создать коллекцию и выдать ссылку."""
    data = await state.get_data()
    file_ids: list[str] = data.get("file_ids", [])

    if not file_ids:
        await callback.answer("⚠️ Вы не загрузили ни одного фото!", show_alert=True)
        return

    # Создать коллекцию через сервис
    manifesto_svc = container.manifesto
    short_code = await manifesto_svc.create_collection(file_ids)

    # Получить username бота для ссылки
    bot_info = await callback.bot.get_me()
    bot_username = bot_info.username

    link = f"https://t.me/{bot_username}?start={short_code}"

    await callback.message.edit_text(
        f"🎉 Манифест создан!\n\n"
        f"📊 Фотографий: {len(file_ids)}\n"
        f"🔗 Ссылка: {hcode(link)}\n\n"
        f"Отправьте эту ссылку друзьям!",
        parse_mode="HTML",
    )


    await state.clear()
    await callback.answer("Готово!")

    logger.info(
        "Манифест создан: code={}, photos={}, link={}",
        short_code,
        len(file_ids),
        link,
    )


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

