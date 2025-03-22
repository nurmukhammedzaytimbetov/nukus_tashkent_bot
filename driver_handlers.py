from aiogram import Router, F
from aiogram.types import Message, ContentType, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardMarkup, \
    InlineKeyboardButton, CallbackQuery
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from database import get_db_connection, set_driver_availability, save_user
import os
import logging
from dotenv import load_dotenv
from aiogram.filters import Command
from datetime import datetime, timedelta


load_dotenv()
ADMIN_ID = int(os.getenv("ADMIN_ID"))

router = Router()


class DriverReg(StatesGroup):
    name = State()
    phone = State()
    passport = State()
    car = State()
    payment = State()
    waiting_approval = State()
    route = State()
    price = State()


# Функции до driver_payment остаются без изменений
@router.message(DriverReg.name)
async def driver_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name or not name.isalpha():
        await message.answer("❌ Имя должно содержать только буквы. Попробуйте снова.")
        return
    await state.update_data(name=name)
    await state.set_state(DriverReg.phone)
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📞 Отправить номер", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("📞 Теперь отправьте ваш номер телефона:", reply_markup=keyboard)


@router.message(F.contact, DriverReg.phone)
async def driver_phone(message: Message, state: FSMContext):
    if not message.contact:
        await message.answer("❌ Пожалуйста, отправьте ваш контакт через кнопку 'Отправить номер'.")
        return
    phone = message.contact.phone_number
    await state.update_data(phone=phone)
    await state.set_state(DriverReg.passport)
    await message.answer("Теперь отправьте фото техпаспорта и водительских прав.")


@router.message(DriverReg.passport, F.content_type == ContentType.PHOTO)
async def driver_passport(message: Message, state: FSMContext):
    passport_photo = message.photo[-1].file_id
    await state.update_data(passport=passport_photo)
    await state.set_state(DriverReg.car)
    await message.answer("Укажите марку вашего автомобиля:")


@router.message(DriverReg.car)
async def driver_car(message: Message, state: FSMContext):
    car = message.text.strip()
    if len(car) < 2:
        await message.answer("❌ Введите корректную марку автомобиля.")
        return
    await state.update_data(car=car)
    await state.set_state(DriverReg.payment)
    await message.answer("Теперь отправьте чек оплаты.")


@router.message(DriverReg.payment, F.content_type == ContentType.PHOTO)
async def driver_payment(message: Message, state: FSMContext):
    payment_photo = message.photo[-1].file_id
    data = await state.get_data()
    success, error_message = await save_user(message.from_user.id, "driver", data["name"], data["phone"], data["car"], None)
    if not success:
        await message.answer(error_message)  # Выводим сообщение об ошибке
        await state.clear()
        return

    conn = await get_db_connection()
    await conn.execute("""
            UPDATE users SET passport=?, payment=?, available=?
            WHERE user_id=?
        """, (data["passport"], payment_photo, 0, message.from_user.id))
    await conn.commit()
    await conn.close()

    await state.set_state(DriverReg.waiting_approval)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{message.from_user.id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{message.from_user.id}")]
    ])

    # Рассчитываем время до 18:00
    now = datetime.now()
    today_18 = now.replace(hour=18, minute=0, second=0, microsecond=0)
    if now > today_18:
        # Если сейчас позже 18:00, следующий дедлайн — 18:00 завтра
        today_18 += timedelta(days=1)
    time_until_18 = today_18 - now
    hours_until_18 = time_until_18.seconds // 3600
    minutes_until_18 = (time_until_18.seconds % 3600) // 60

    # Формируем сообщение в зависимости от времени
    if now.hour < 18:
        admin_message = f"⏳ Админ начнёт работу после 18:00 (через {hours_until_18} ч {minutes_until_18} мин) и ответит в течение 24 часов."
    else:
        admin_message = "⏳ Админ работает после 18:00 и ответит в течение 24 часов."

    try:
        await message.bot.send_photo(
            ADMIN_ID,
            photo=data["passport"],
            caption=f"🔔 Новый водитель ожидает одобрения!\n\n"
                    f"👤 Имя: {data['name']}\n"
                    f"📞 Телефон: {data['phone']}\n"
                    f"🚗 Автомобиль: {data['car']}\n\n"
                    f"📄 Техпаспорт и права (выше)\n\n"
                    f"💰 Чек оплаты (ниже)",
            reply_markup=keyboard
        )
        await message.bot.send_photo(ADMIN_ID, photo=payment_photo)
        await message.answer(
            f"✅ Ваши данные отправлены администратору. Ожидайте одобрения.\n"
            f"{admin_message}\n"
            f"Если хотите отменить заявку, нажмите кнопку ниже.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отменить заявку", callback_data="cancel_driver_reg")]
            ])
        )
    except Exception as e:
        logging.error(f"Ошибка при отправке данных админу: {e}")
        await message.answer("⚠️ Ошибка при отправке данных администратору. Попробуйте позже.")
        await state.clear()


@router.callback_query(lambda c: c.data.startswith("approve_"))
async def approve_driver(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split("_")[1])
    conn = await get_db_connection()
    await conn.execute("UPDATE users SET available=1 WHERE user_id=?", (user_id,))
    await conn.commit()
    await conn.close()
    try:
        await callback.message.bot.send_message(user_id, "✅ Ваша заявка одобрена! Укажите ваш маршрут:")
        await state.set_state(DriverReg.route)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛫 Ташкент ➡️ Нукус 🛬", callback_data="driver_route_tashkent_nukus")],
            [InlineKeyboardButton(text="🛫 Нукус ➡️ Ташкент 🛬", callback_data="driver_route_nukus_tashkent")]
        ])
        await callback.message.bot.send_message(user_id, "🚖 Выберите маршрут:", reply_markup=keyboard)
        await callback.message.bot.send_message(callback.from_user.id, "✅ Водитель одобрен!")
    except Exception as e:
        logging.error(f"Ошибка при одобрении водителя {user_id}: {e}")
        await callback.message.bot.send_message(callback.from_user.id, f"⚠️ Ошибка при одобрении водителя {user_id}")
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("driver_route_"))
async def choose_driver_route(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    new_route = "🛫 Ташкент ➡️ Нукус 🛬" if callback.data == "driver_route_tashkent_nukus" else "🛫 Нукус ➡️ Ташкент 🛬"
    conn = await get_db_connection()
    try:
        cursor = await conn.execute("SELECT route FROM users WHERE user_id=?", (user_id,))
        current_route = (await cursor.fetchone())[0]
        if current_route and current_route != new_route:
            arrival_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            await conn.execute(
                "UPDATE users SET route=?, last_arrival_time=? WHERE user_id=?",
                (new_route, arrival_time, user_id)
            )
        else:
            await conn.execute("UPDATE users SET route=? WHERE user_id=?", (new_route, user_id))
        await conn.commit()
    except Exception as e:
        logging.error(f"Ошибка изменения маршрута водителя {user_id}: {e}")
    finally:
        await conn.close()

    # Сразу запрашиваем сумму после выбора маршрута
    await state.set_state(DriverReg.price)
    await callback.message.edit_text(
        f"✅ Ваш маршрут сохранён: \n{new_route}.\n\n💵 Укажите сумму за поездку (введите число, например, 100000):")
    await state.update_data(route=new_route)  # Сохраняем маршрут в состоянии
    await callback.answer()


@router.message(DriverReg.price)
async def driver_price(message: Message, state: FSMContext):
    try:
        price = int(message.text.strip())
        if price <= 0:
            await message.answer("❌ Сумма должна быть положительным числом. Попробуйте снова.")
            return
    except ValueError:
        await message.answer("❌ Введите корректное число. Попробуйте снова.")
        return

    user_id = message.from_user.id
    data = await state.get_data()
    route = data.get("route")  # Получаем маршрут из состояния
    conn = await get_db_connection()
    try:
        await conn.execute("UPDATE users SET price=? WHERE user_id=?", (price, user_id))
        await conn.commit()
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏ Изменить маршрут и сумму", callback_data="change_driver_route")],
            [InlineKeyboardButton(text="🚫 Не работаю", callback_data="driver_busy")]
        ])
        await message.answer(
            f"✅ Ваш маршрут и сумма сохранены:\n"
            f"🛣 Маршрут: {route}\n"
            f"💵 Сумма: {price} сум\n\n"
            f"Выберите действие:",
            reply_markup=keyboard
        )
    except Exception as e:
        logging.error(f"Ошибка при сохранении суммы для водителя {user_id}: {e}")
        await message.answer("⚠️ Ошибка при сохранении суммы. Попробуйте позже.")
    finally:
        await conn.close()
    await state.clear()


@router.callback_query(lambda c: c.data == "change_driver_route")
async def change_driver_route(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛫 Ташкент ➡️ Нукус 🛬", callback_data="driver_route_tashkent_nukus")],
        [InlineKeyboardButton(text="🛫 Нукус ➡️ Ташкент 🛬", callback_data="driver_route_nukus_tashkent")]
    ])
    await callback.message.edit_text("🚖 Выберите новый маршрут:", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(lambda c: c.data == "driver_busy")
async def driver_set_busy(callback: CallbackQuery):
    user_id = callback.from_user.id
    await set_driver_availability(user_id, False)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Вернуться на работу", callback_data="driver_available")]
    ])
    await callback.message.edit_text(
        "🚫 Вы теперь **не работаете**. \n\nКогда будете готовы, нажмите \n'✅ Вернуться на работу'.",
        reply_markup=keyboard)
    await callback.answer()


@router.callback_query(lambda c: c.data == "driver_available")
async def driver_set_available(callback: CallbackQuery):
    user_id = callback.from_user.id
    await set_driver_availability(user_id, True)
    conn = await get_db_connection()
    try:
        cursor = await conn.execute("SELECT route, price FROM users WHERE user_id=?", (user_id,))
        row = await cursor.fetchone()
        current_route = row[0] if row else "Маршрут не установлен"
        current_price = row[1] if row[1] is not None else "Не указана"
    except Exception as e:
        logging.error(f"Ошибка получения данных водителя {user_id}: {e}")
        current_route = "Маршрут не установлен"
        current_price = "Не указана"
    finally:
        await conn.close()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏ Изменить маршрут и сумму", callback_data="change_driver_route")],
        [InlineKeyboardButton(text="🚫 Не работаю", callback_data="driver_busy")]
    ])
    await callback.message.edit_text(
        f"✅ Вы **вернулись на работу**.\n"
        f"🛣 Ваш маршрут: {current_route}\n"
        f"💵 Сумма: {current_price} сум\n\n"
        f"Выберите действие:",
        reply_markup=keyboard
    )
    await callback.answer()


@router.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext):
    await state.clear()
    conn = await get_db_connection()
    try:
        await conn.execute("DELETE FROM users WHERE user_id=?", (message.from_user.id,))
        await conn.commit()
    except Exception as e:
        logging.error(f"Ошибка при удалении данных пользователя {message.from_user.id}: {e}")
    finally:
        await conn.close()
    await message.answer("❌ Все действия отменены. Используйте /start, чтобы начать заново.")