import asyncio
import os

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from handlers.start import router as start_router
from handlers.chapter import router as chapter_router
from handlers.manage import router as manage_router
from handlers.chapters import router as chapters_router

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


async def main():
    bot = Bot(token=TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(start_router)
    dp.include_router(chapter_router)
    dp.include_router(manage_router)
    dp.include_router(chapters_router)

    await bot.set_my_commands([
        BotCommand(command="start",  description="Главное меню / новая история"),
        BotCommand(command="next",   description="Следующая глава"),
        BotCommand(command="list",   description="Мои истории"),
        BotCommand(command="regen",  description="Перегенерировать последнюю главу"),
        BotCommand(command="load",     description="Переключить историю: /load 2"),
        BotCommand(command="chapters", description="Читать главы истории"),
    ])

    print("Bot running...")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"], drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
