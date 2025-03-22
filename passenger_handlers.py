import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, KeyboardButton, ReplyKeyboardMarkup
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from database import get_db_connection
from aiogram.filters import Command
from messages import SUCCESS_PASSENGER
import asyncio

router = Router()

class PassengerReg(StatesGroup):
    name = State()
    phone = State()
    route = State()

@router.message(PassengerReg.name)
async def passenger_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2 or not name.isalpha():
        await message.answer("❌ Имя должно быть длиннее 1 буквы и содержать только буквы. Попробуйте снова.")
        return
    await state.update_data(name=name)
    await state.set_state(PassengerReg.phone)
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="☎️ Отправить номер", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("☎️ Укажите ваш номер телефона:", reply_markup=keyboard)

@router.message(F.contact, PassengerReg.phone)
async def passenger_phone(message: Message, state: FSMContext):
    if not message.contact:
        await message.answer("❌ Пожалуйста, отправьте ваш контакт через кнопку 'Отправить номер'.")
        return
    phone = message.contact.phone_number
    '''if not phone.startswith("+") or len(phone) < 10:
        await message.answer("❌ Номер телефона должен начинаться с '+' и быть корректной длины. Попробуйте снова.")
        return'''

    data = await state.get_data()
    name = data.get("name")
    user_id = message.from_user.id

    conn = await get_db_connection()
    await conn.execute(
        "INSERT INTO users (user_id, role, name, phone) VALUES (?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET name=?, phone=?",
        (user_id, "passenger", name, phone, name, phone)
    )
    await conn.commit()
    await conn.close()

    await state.update_data(phone=phone)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛫 Ташкент ➡️ Нукус 🛬", callback_data="passenger_route_tashkent_nukus")],
        [InlineKeyboardButton(text="🛫 Нукус ➡️ Ташкент 🛬", callback_data="passenger_route_nukus_tashkent")]
    ])
    await state.set_state(PassengerReg.route)
    await message.answer("🚖 Выберите маршрут:", reply_markup=keyboard)

@router.callback_query(lambda c: c.data.startswith("passenger_route_"))
async def confirm_passenger_route(callback: CallbackQuery):
    user_id = callback.from_user.id
    new_route = "🛫 Ташкент ➡️ Нукус 🛬" if callback.data == "passenger_route_tashkent_nukus" else "🛫 Нукус ➡️ Ташкент 🛬"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_route_{new_route}")],
        [InlineKeyboardButton(text="❌ Изменить маршрут", callback_data="change_passenger_route")]
    ])
    await callback.message.edit_text(f"Вы выбрали маршрут: \n{new_route}.\n\n❗️ Подтвердите выбор:", reply_markup=keyboard)
    await callback.answer()

@router.callback_query(lambda c: c.data == "change_passenger_route")
async def change_passenger_route(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛫 Ташкент ➡️ Нукус 🛬", callback_data="passenger_route_tashkent_nukus")],
        [InlineKeyboardButton(text="🛫 Нукус ➡️ Ташкент 🛬", callback_data="passenger_route_nukus_tashkent")]
    ])
    await callback.message.edit_text("Выберите новый маршрут:", reply_markup=keyboard)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("confirm_route_"))
async def choose_passenger_route(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    new_route = callback.data.replace("confirm_route_", "")
    conn = await get_db_connection()
    try:
        await conn.execute("UPDATE users SET route=? WHERE user_id=?", (new_route, user_id))
        await conn.commit()
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏ Изменить маршрут", callback_data="change_passenger_route")],
            [InlineKeyboardButton(text="🔄 Найти водителей", callback_data="find_drivers")]
        ])
        await callback.message.edit_text(
            f"✅ Ваш маршрут сохранён: \n{new_route}.\n\nВыберите действие:",
            reply_markup=keyboard
        )
        success_message = await callback.message.bot.send_message(user_id, SUCCESS_PASSENGER)
        await asyncio.sleep(5)
        await callback.message.bot.delete_message(chat_id=user_id, message_id=success_message.message_id)
    except Exception as e:
        print(f"Ошибка изменения маршрута пассажира {user_id}: {e}")
    finally:
        await conn.close()
    await state.clear()
    await callback.answer()

@router.callback_query(lambda c: c.data == "find_drivers")
async def find_drivers(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    logging.info(f"Пользователь {user_id} нажал 'Найти водителей'")

    conn = await get_db_connection()
    try:
        cursor = await conn.execute("SELECT route FROM users WHERE user_id=?", (user_id,))
        row = await cursor.fetchone()
        if not row or not row[0]:
            logging.warning(f"У пользователя {user_id} не установлен маршрут")
            await callback.answer("❌ У вас нет указанного маршрута! Выберите маршрут сначала.", show_alert=True)
            return
        passenger_route = row[0]
        logging.info(f"Маршрут пользователя {user_id}: {passenger_route}")

        cursor = await conn.execute(
            "SELECT user_id, name, phone, car_info, price, last_arrival_time, available FROM users WHERE role='driver' AND available=1 AND route=?",
            (passenger_route,)
        )
        drivers = await cursor.fetchall()
        logging.info(f"Найдено водителей: {len(drivers)}")

        data = await state.get_data()
        previous_message_id = data.get("last_driver_list_message_id")
        if previous_message_id:
            try:
                await callback.message.bot.delete_message(chat_id=user_id, message_id=previous_message_id)
                logging.info(f"Удалено предыдущее сообщение {previous_message_id}")
            except Exception as e:
                logging.error(f"Ошибка при удалении сообщения {previous_message_id}: {e}")

        if not drivers:
            new_message = await callback.message.answer(
                "❌ Нет доступных водителей на этом маршруте.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Вернуться в меню", callback_data="return_to_menu")]
                ])
            )
            logging.info("Водители не найдены")
        else:
            driver_list = "\n\n".join([
                f"🚗 {driver[3]}\n👤 {driver[1]}\n📞 [{driver[2]}](tel:{driver[2]})\n💵 {driver[4]} сум"
                + (f"\n🕒 Прибыл: {driver[5]}" if driver[5] else "")
                + f"\n{'✅ Работает' if driver[6] == 1 else '❌ Не работает'}"
                for driver in drivers
            ])
            buttons = []
            for driver in drivers:
                driver_id = driver[0]
                buttons.append([InlineKeyboardButton(text=f"✅ Договорился с {driver[1]}", callback_data=f"book_driver_{driver_id}")])
            buttons.append([InlineKeyboardButton(text="⬅️ Вернуться в меню", callback_data="return_to_menu")])
            new_message = await callback.message.answer(
                f"🚗 Доступные водители по маршруту \n{passenger_route}:\n\n{driver_list}\n\n"
                f"📲 **Свяжитесь с водителем по номеру телефона, чтобы договориться о поездке.**\n"
                f"После этого нажмите кнопку ниже, чтобы отметить, что вы договорились.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
            logging.info(f"Список водителей отправлен: {driver_list}")

        await state.update_data(last_driver_list_message_id=new_message.message_id)
        await state.clear()

    except Exception as e:
        logging.error(f"Ошибка в find_drivers для пользователя {user_id}: {e}")
        await callback.message.answer("⚠️ Произошла ошибка при поиске водителей. Попробуйте позже.")
    finally:
        await conn.close()

    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("book_driver_"))
async def book_driver(callback: CallbackQuery):
    user_id = callback.from_user.id
    driver_id = int(callback.data.split("_")[2])

    conn = await get_db_connection()
    try:
        cursor = await conn.execute("SELECT rides_count, name FROM users WHERE user_id=?", (driver_id,))
        row = await cursor.fetchone()
        if row:
            new_rides_count = row[0] + 1
            driver_name = row[1]
            await conn.execute("UPDATE users SET rides_count=? WHERE user_id=?", (new_rides_count, driver_id))
            await conn.commit()

        cursor = await conn.execute("SELECT name, phone FROM users WHERE user_id=?", (user_id,))
        passenger_row = await cursor.fetchone()
        passenger_name = passenger_row[0] if passenger_row else "Пассажир"
        passenger_phone = passenger_row[1] if passenger_row else "Не указан"

        try:
            await callback.message.bot.send_message(
                driver_id,
                f"🔔 Пассажир {passenger_name} договорился с вами о поездке!\n"
                f"📞 Свяжитесь с ним: [{passenger_phone}](tel:{passenger_phone})",
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
        except Exception as e:
            logging.error(f"Не удалось уведомить водителя {driver_id}: {e}")

        await callback.message.edit_text(
            f"✅ Вы отметили, что договорились с {driver_name}!\n\n"
            f"Если хотите найти других водителей, вернитесь в меню.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Вернуться в меню", callback_data="return_to_menu")]
            ])
        )
    except Exception as e:
        logging.error(f"Ошибка при бронировании водителя {driver_id} для пользователя {user_id}: {e}")
        await callback.message.answer("⚠️ Произошла ошибка. Попробуйте позже.")
    finally:
        await conn.close()

    await callback.answer()

@router.callback_query(lambda c: c.data == "return_to_menu")
async def return_to_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = await get_db_connection()
    try:
        cursor = await conn.execute("SELECT route FROM users WHERE user_id=?", (user_id,))
        row = await cursor.fetchone()
        current_route = row[0] if row and row[0] else "Маршрут не установлен"
    except Exception as e:
        logging.error(f"Ошибка получения данных пассажира {user_id}: {e}")
        current_route = "Маршрут не установлен"
    finally:
        await conn.close()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏ Изменить маршрут", callback_data="change_passenger_route")],
        [InlineKeyboardButton(text="🔄 Найти водителей", callback_data="find_drivers")]
    ])
    await callback.message.edit_text(
        f"🧑‍💼 Вы зарегистрированы как пассажир.\n"
        f"🛣 Ваш маршрут: {current_route}\n\n"
        f"Выберите действие:",
        reply_markup=keyboard
    )
    await callback.answer()

@router.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is not None:  # Если пользователь в процессе регистрации
        conn = await get_db_connection()
        try:
            await conn.execute("DELETE FROM users WHERE user_id=?", (message.from_user.id,))
            await conn.commit()
        except Exception as e:
            logging.error(f"Ошибка при удалении данных пользователя {message.from_user.id}: {e}")
        finally:
            await conn.close()
    await state.clear()
    await message.answer("❌ Все действия отменены. Используйте /start, чтобы начать заново.")

