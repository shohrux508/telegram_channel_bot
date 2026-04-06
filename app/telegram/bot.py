from aiogram import Bot, Dispatcher
from app.config import settings
from app.container import Container
from app.telegram.routers import admin_manifesto, user_manifesto, example


async def start_telegram(container: Container):
    if not settings.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is required when RUN_TELEGRAM=true")

    bot = Bot(token=settings.BOT_TOKEN)
    dp = Dispatcher()

    # Pass the container into the Dispatcher to bypass globals
    dp["container"] = container

    # Include routers — порядок важен!
    # 0. Платежи (Stars)
    from app.telegram.routers import payments
    dp.include_router(payments.router)
    # 1. Админский роутер (перехватит /manifesto, /users)
    dp.include_router(admin_manifesto.router)
    # 2. User deep link (/start с аргументом)
    dp.include_router(user_manifesto.router)
    # 3. Обычный /start (без аргументов)
    dp.include_router(example.router)

    try:
        await dp.start_polling(bot, container=container)
    finally:
        await bot.session.close()
