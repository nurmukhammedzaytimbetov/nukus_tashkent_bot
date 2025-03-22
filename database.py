import aiosqlite
import logging

async def get_db_connection():
    """Открывает соединение с базой данных"""
    return await aiosqlite.connect("database.db")

async def setup_database():
    conn = await get_db_connection()
    try:
        # Создаем таблицу
        await conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                role TEXT,
                name TEXT,
                phone TEXT,
                car_info TEXT,
                route TEXT DEFAULT NULL,
                available INTEGER DEFAULT 0,
                rides_count INTEGER DEFAULT 0,
                subscribed INTEGER DEFAULT 0,
                banned INTEGER DEFAULT 0,
                last_route_change TIMESTAMP DEFAULT NULL,
                subscription_end TIMESTAMP DEFAULT NULL,
                passport TEXT DEFAULT NULL,
                payment TEXT DEFAULT NULL,
                price INTEGER DEFAULT NULL,
                last_arrival_time TIMESTAMP DEFAULT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_users_route ON users(route);
        """)
        await conn.commit()
        logging.info("Таблица users успешно создана или уже существует")

        # Проверяем, что таблица действительно создана
        async with conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users';") as cursor:
            result = await cursor.fetchone()
            if result:
                logging.info("Таблица users подтверждена в базе данных")
            else:
                logging.error("Таблица users не найдена после создания")

        # Проверяем наличие колонок и добавляем их, если их нет
        async with conn.execute("PRAGMA table_info(users);") as cursor:
            columns = [row[1] for row in await cursor.fetchall()]
            logging.info(f"Существующие колонки в таблице users: {columns}")

        if "passport" not in columns:
            await conn.execute("ALTER TABLE users ADD COLUMN passport TEXT DEFAULT NULL;")
            logging.info("Добавлена колонка passport")
        if "payment" not in columns:
            await conn.execute("ALTER TABLE users ADD COLUMN payment TEXT DEFAULT NULL;")
            logging.info("Добавлена колонка payment")
        if "price" not in columns:
            await conn.execute("ALTER TABLE users ADD COLUMN price INTEGER DEFAULT NULL;")
            logging.info("Добавлена колонка price")
        if "last_arrival_time" not in columns:
            await conn.execute("ALTER TABLE users ADD COLUMN last_arrival_time TIMESTAMP DEFAULT NULL;")
            logging.info("Добавлена колонка last_arrival_time")

        await conn.commit()
        logging.info("Все необходимые колонки добавлены или уже существуют")

    except Exception as e:
        logging.error(f"Ошибка при создании/обновлении базы данных: {e}", exc_info=True)
    finally:
        await conn.close()

# Остальные функции остаются без изменений
async def save_user(user_id: int, role: str, name: str, phone: str, car_info: str = None, route: str = None):
    async with aiosqlite.connect("database.db") as conn:
        try:
            from datetime import datetime, timedelta
            subscription_end = (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
            await conn.execute("""
                INSERT INTO users (user_id, role, name, phone, car_info, route, available, rides_count, subscription_end)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET 
                    car_info=excluded.car_info,
                    subscription_end=excluded.subscription_end;
            """, (user_id, role, name, phone, car_info, route, 1 if role == "driver" else 0, 0, subscription_end))
            await conn.commit()
            return True, None  # Успех, сообщение об ошибке не нужно
        except Exception as e:
            logging.error(f"Ошибка сохранения пользователя {user_id}: {e}")
            return False, "⚠️ Ошибка при сохранении данных. Попробуйте позже."


async def set_driver_availability(user_id: int, available: bool):
    conn = await get_db_connection()
    try:
        await conn.execute("UPDATE users SET available=? WHERE user_id=?", (1 if available else 0, user_id))
        await conn.commit()
    finally:
        await conn.close()

async def fetch_user(user_id: int):
    async with aiosqlite.connect("database.db") as conn:
        try:
            async with conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        "user_id": row[0],
                        "role": row[1],
                        "name": row[2],
                        "phone": row[3],
                        "car_info": row[4],
                        "route": row[5],
                        "available": row[6],
                        "rides_count": row[7],
                        "subscribed": row[8],
                        "banned": row[9],
                        "last_route_change": row[10],
                        "subscription_end": row[11],
                        "passport": row[12],
                        "payment": row[13],
                        "price": row[14],
                        "last_arrival_time": row[15]
                    }
        except Exception as e:
            logging.error(f"Ошибка получения пользователя {user_id}: {e}")
    return None

async def get_all_drivers():
    conn = await get_db_connection()
    try:
        async with (conn.execute("SELECT user_id, name, phone, route, available FROM users WHERE role='driver'") as cursor):
            drivers = await cursor.fetchall()
            return drivers
    except Exception as e:
        logging.error(f"Ошибка при получении списка водителей: {e}")
    finally:
        await conn.close()
    return []