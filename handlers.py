from aiogram import Router, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from passenger_handlers import router as passenger_router
from driver_handlers import router as driver_router
from dotenv import load_dotenv
from database import get_db_connection
import os
from aiogram.fsm.context import FSMContext
from driver_handlers import DriverReg
from passenger_handlers import PassengerReg
from aiogram.fsm.state import State, StatesGroup
from messages import WELCOME, HELP_TEXT

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ Ошибка: BOT_TOKEN не найден! Проверь файл .env")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

router = Router()
router.include_router(passenger_router)
router.include_router(driver_router)

class AdminStates(StatesGroup):
    ban_user = State()
    update_status = State()

@router.message(Command("admin"))
async def admin_panel(message: Message, bot: Bot):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет доступа к админ-панели.")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Список водителей", callback_data="list_drivers")],
        [InlineKeyboardButton(text="📜 Список пассажиров", callback_data="list_passengers")],
        [InlineKeyboardButton(text="🚫 Заблокировать пользователя", callback_data="ban_user")],
        [InlineKeyboardButton(text="🔄 Обновить статус водителя", callback_data="update_driver_status")]
    ])
    await message.answer("🔧 Панель администратора:", reply_markup=keyboard)

@router.callback_query(lambda c: c.data == "reg_passenger")
async def handle_passenger_role(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await state.update_data(role="passenger")
    await state.set_state(PassengerReg.name)
    await bot.send_message(callback.from_user.id, "👤 Введите ваше имя:")
    await callback.answer()

@router.callback_query(lambda c: c.data == "reg_driver")
async def handle_driver_role(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await state.update_data(role="driver")
    await state.set_state(DriverReg.name)
    await bot.send_message(callback.from_user.id, "🚗 Введите ваше имя:")
    await callback.answer()

@router.message(Command("start"))
async def start_command(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧑‍💼 Я пассажир", callback_data="reg_passenger")],
        [InlineKeyboardButton(text="🚗 Я водитель", callback_data="reg_driver")]
    ])
    await message.answer(WELCOME, reply_markup=keyboard)

@router.message(Command("help"))
async def help_command(message: Message):
    await message.answer(HELP_TEXT)


@router.callback_query(lambda c: c.data == "list_drivers")
async def list_drivers(callback: CallbackQuery):
    conn = await get_db_connection()
    cursor = await conn.execute("SELECT user_id, name, phone, car_info, route, available FROM users WHERE role='driver'")
    drivers = await cursor.fetchall()
    await conn.close()
    if not drivers:
        await callback.answer("❌ Водителей нет в базе данных.", show_alert=True)
        return
    driver_list = "\n\n".join([f"👤 {driver[1]} ({'✅ Работает' if driver[5] else '❌ Не работает'})\n🚗 {driver[3]}\n🛣 Маршрут: {driver[4]}\n📞 {driver[2]}" for driver in drivers])
    await callback.message.answer(f"📜 **Список водителей:**\n\n{driver_list}")
    await callback.answer()


@router.callback_query(lambda c: c.data == "list_passengers")
async def list_passengers(callback: CallbackQuery):
    conn = await get_db_connection()
    cursor = await conn.execute("SELECT user_id, name, phone, route FROM users WHERE role='passenger'")
    passengers = await cursor.fetchall()
    await conn.close()
    if not passengers:
        await callback.answer("❌ Пассажиров нет в базе данных.", show_alert=True)
        return
    passenger_list = "\n\n".join([f"👤 {passenger[1]}\n🛣 Маршрут: {passenger[3]}\n📞 {passenger[2]}" for passenger in passengers])
    await callback.message.answer(f"📜 **Список пассажиров:**\n\n{passenger_list}")
    await callback.answer()


@router.callback_query(lambda c: c.data == "ban_user")
async def ask_user_id_for_ban(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ID пользователя, которого нужно заблокировать:")
    await state.set_state(AdminStates.ban_user)
    await callback.answer()


@router.message(AdminStates.ban_user)
async def ban_user(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите корректный числовой ID.")
        return
    conn = await get_db_connection()
    cursor = await conn.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    if not await cursor.fetchone():
        await message.answer("❌ Пользователь с таким ID не найден.")
        await conn.close()
        return
    await conn.execute("UPDATE users SET banned=1 WHERE user_id=?", (user_id,))
    await conn.commit()
    await conn.close()
    await message.answer(f"✅ Пользователь {user_id} заблокирован.")
    await state.clear()


@router.callback_query(lambda c: c.data == "update_driver_status")
async def ask_driver_id(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ID водителя, чтобы изменить его статус (работает/не работает):")
    await state.set_state(AdminStates.update_status)
    await callback.answer()


@router.message(AdminStates.update_status)
async def update_driver_status(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите корректный числовой ID.")
        return
    conn = await get_db_connection()
    cursor = await conn.execute("SELECT available FROM users WHERE user_id=? AND role='driver'", (user_id,))
    row = await cursor.fetchone()
    if not row:
        await message.answer("❌ Водитель с таким ID не найден.")
        await conn.close()
        return
    new_status = 0 if row[0] == 1 else 1
    await conn.execute("UPDATE users SET available=? WHERE user_id=?", (new_status, user_id))
    await conn.commit()
    await conn.close()
    status_text = "✅ Теперь водитель работает." if new_status == 1 else "🚫 Водитель отключён."
    await message.answer(f"Пользователь {user_id}: {status_text}")
    await state.clear()
