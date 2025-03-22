import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import Update
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from dotenv import load_dotenv
from handlers import router
from database import setup_database


load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_NAME = os.getenv("CHANNEL_NAME")

if not TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден! Проверь файл .env")

# Middleware для тайм-аута FSM
class TimeoutMiddleware(BaseMiddleware):
    def __init__(self):
        super().__init__()
        self.active_states = {}  # Храним время последнего действия для каждого пользователя

    async def __call__(self, handler, event, data):
        state: FSMContext = data.get("state")
        chat_id = event.from_user.id if event.from_user else event.chat.id

        # Если пользователь что-то делает, обновляем время последнего действия
        self.active_states[chat_id] = asyncio.get_event_loop().time()

        # Проверяем, есть ли активное состояние
        current_state = await state.get_state()
        if current_state:
            # Запускаем задачу для проверки тайм-аута
            asyncio.create_task(self.check_timeout(chat_id, state, event.bot))

        return await handler(event, data)

    async def check_timeout(self, chat_id: int, state: FSMContext, bot: Bot):
        # Ждем 10 минут (600 секунд)
        await asyncio.sleep(600)

        # Проверяем, прошло ли 10 минут с последнего действия
        last_action_time = self.active_states.get(chat_id, 0)
        current_time = asyncio.get_event_loop().time()
        if current_time - last_action_time >= 600:  # Если прошло 10 минут
            current_state = await state.get_state()
            if current_state:  # Если состояние всё ещё активно
                await state.clear()  # Очищаем состояние
                try:
                    await bot.send_message(chat_id, "⏳ Время ожидания истекло. Начните заново с /start.")
                except Exception as e:
                    logging.error(f"Ошибка при отправке сообщения о тайм-ауте пользователю {chat_id}: {e}")
                finally:
                    self.active_states.pop(chat_id, None)  # Удаляем из активных

async def main():
    logging.basicConfig(level=logging.INFO)  # Настройка логирования
    # Ждем завершения настройки базы данных
    await setup_database()
    logging.info("Инициализация базы данных завершена")

    session = AiohttpSession(timeout=60)
    global bot
    bot = Bot(token=TOKEN, session=session)
    storage = MemoryStorage()  # Хранилище для FSM
    dp = Dispatcher(storage=storage)

    # Подключаем middleware для тайм-аута
    dp.message.middleware(TimeoutMiddleware())
    dp.callback_query.middleware(TimeoutMiddleware())

    dp.include_router(router)  # handlers.py

    # Регистрируем обработчик ошибок с помощью декоратора
    @dp.errors()
    async def on_error(update: Update, exception: Exception):
        logging.error(f"Ошибка: {exception}")
        if update.message:  # Проверяем, есть ли сообщение
            await bot.send_message(update.message.chat.id, "⚠️ Произошла ошибка. Попробуйте позже.")

    logging.info("✅ Бот запущен!")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    asyncio.run(main())