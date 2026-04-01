import asyncio
import os

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from handlers.start import router as start_router
from handlers.chapter import router as chapter_router
from handlers.manage import router as manage_router

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


async def main():
    bot = Bot(token=TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(start_router)
    dp.include_router(chapter_router)
    dp.include_router(manage_router)

    print("Bot running...")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    asyncio.run(main())
