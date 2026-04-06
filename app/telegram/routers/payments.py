"""
app.telegram.routers.payments — Обработка платежей (Telegram Stars).

Обрабатывает:
- PreCheckoutQuery (всегда отвечаем Да)
- SuccessfulPayment (записываем факт покупки или доната, выдаем контент)
"""

from __future__ import annotations

from aiogram import Router, types, F
from loguru import logger

from app.container import Container

router = Router()

@router.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: types.PreCheckoutQuery):
    """Подтверждение готовности принять платеж. Для цифровых товаров (Stars) мы всегда готовы."""
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def process_successful_payment(message: types.Message, container: Container):
    """Обработка успешного платежа."""
    payment = message.successful_payment
    if not payment:
        return
        
    payload = payment.invoice_payload
    amount = payment.total_amount
    user_id = message.from_user.id
    
    logger.info("Успешный платеж: user_id={}, payload={}, amount={}", user_id, payload, amount)
    
    manifesto_svc = container.manifesto
    
    parts = payload.split(":", 2)
    action = parts[0]
    short_code = parts[1]
    
    if action == "buy":
        # 1. Записать право доступа
        await manifesto_svc.grant_access(user_id=user_id, short_code=short_code, amount=amount)
        
        # 2. Сообщить об успешной покупке
        await message.answer("🎉 Оплата прошла успешно! Открываю доступ...")
        
        # 3. Отправить контент
        from app.telegram.routers.user_manifesto import send_manifesto_content
        
        collection = await manifesto_svc.get_collection(short_code)
        if collection:
            await send_manifesto_content(message, collection, container)
            
    elif action == "donate":
        # Записать донат
        # amount from Telegram payload is in stars
        await manifesto_svc.add_donation(user_id=user_id, short_code=short_code, amount=amount)
        await message.answer("🌟 Спасибо за поддержку! Ваша звезда сияет ярче всех.")

    else:
        logger.warning("Неизвестное действие в payload: {}", action)
