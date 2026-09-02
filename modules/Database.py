import sqlite3
import asyncio
from sqlite3 import Error
import time
from datetime import date, datetime, timedelta
from ast import literal_eval
import json
from contextlib import contextmanager

from modules.Logger import *
from modules.Utils import Utils


VOICE_MAX_REASONABLE_HOURS = 100000
VOICE_MAX_SESSION_MINUTES = 72 * 60
VOICE_MAX_SESSION_SECONDS = VOICE_MAX_SESSION_MINUTES * 60


class Database:

    def __init__(self, db_name=Utils.get_patch_db("main")):
        self.name = db_name
        # Увеличиваем таймаут для ожидания разблокировки
        self.conn = self.connect(db_name)
        self.cursor = self.conn.cursor()

        self.conn_log = self.connect(Utils.get_patch_db("log"))
        self.cursor_log = self.conn_log.cursor()
        
        # Создаём таблицы в обеих БД
        self.create_tables()

    def connect(self, db_name):
        try:
            # Увеличиваем таймаут до 30 секунд и включаем WAL режим
            conn = sqlite3.connect(
                db_name, 
                detect_types=sqlite3.PARSE_DECLTYPES|sqlite3.PARSE_COLNAMES, 
                timeout=30.0
            )
            # Включаем WAL режим для лучшей производительности
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=10000")
            return conn
        except Error as e:
            logger.error(f"Ошибка подключения к БД {db_name}: {e}")
            return None

    def execute_with_retry(self, func, max_retries=5, delay=0.5):
        """Выполняет функцию с повторными попытками при блокировке БД"""
        for attempt in range(max_retries):
            try:
                return func()
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    logger.warning(f"База данных заблокирована, попытка {attempt + 1}/{max_retries}...")
                    time.sleep(delay * (attempt + 1))
                    continue
                raise e
        return None

    def normalize_voice_time(self, hours, minutes, max_total_minutes=None):
        """Приводит часы/минуты онлайна к нормальному виду или отсекает невозможные значения."""
        try:
            hours = int(hours or 0)
            minutes = int(minutes or 0)
        except (TypeError, ValueError):
            return None

        if hours < 0 or minutes < 0:
            return None

        total_minutes = hours * 60 + minutes
        if max_total_minutes is not None and total_minutes > max_total_minutes:
            total_minutes = max_total_minutes

        normalized_hours = total_minutes // 60
        normalized_minutes = total_minutes % 60

        if normalized_hours > VOICE_MAX_REASONABLE_HOURS:
            return None

        return normalized_hours, normalized_minutes

    def normalize_voice_delta_minutes(self, value):
        """Защищает начисление онлайна от timestamp и секунд вместо минут."""
        try:
            value = int(value or 0)
        except (TypeError, ValueError):
            return 0

        if value <= 0:
            return 0

        if value > VOICE_MAX_SESSION_SECONDS:
            logger.warning(f"Игнорируется невозможный голосовой сеанс: {value}")
            return 0

        if value > VOICE_MAX_SESSION_MINUTES:
            value = value // 60

        return max(value, 0)

    def repair_voiceactivity_totals(self, max_total_minutes=None):
        """Чистит уже испорченные значения голосового онлайна и нормализует минуты."""
        try:
            self.cursor.execute("SELECT member_id, joined_at, left_at, total_hours, total_minutes FROM voiceactivity_all")
            rows = self.cursor.fetchall()
            fixed_count = 0

            for member_id, joined_at, left_at, hours, minutes in rows:
                normalized = self.normalize_voice_time(hours, minutes, max_total_minutes=max_total_minutes)

                if normalized is None:
                    self.cursor.execute(
                        "UPDATE voiceactivity_all SET joined_at = 0, left_at = 0, total_hours = 0, total_minutes = 0 WHERE member_id = ?",
                        (member_id,),
                    )
                    fixed_count += 1
                    continue

                normalized_hours, normalized_minutes = normalized
                if int(hours or 0) != normalized_hours or int(minutes or 0) != normalized_minutes:
                    self.cursor.execute(
                        "UPDATE voiceactivity_all SET total_hours = ?, total_minutes = ? WHERE member_id = ?",
                        (normalized_hours, normalized_minutes, member_id),
                    )
                    fixed_count += 1

            if fixed_count:
                self.conn.commit()
                logger.warning(f"Исправлены значения voiceactivity_all: {fixed_count}")

            return fixed_count
        except Exception as e:
            logger.error(f"Ошибка при исправлении voiceactivity_all: {e}")
            return 0

    def ensure_meta_table(self):
        self.cursor.execute(
            "CREATE TABLE IF NOT EXISTS bot_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self.conn.commit()

    def create_tables(self):

        # === СОЗДАНИЕ ТАБЛИЦ В ОСНОВНОЙ БАЗЕ ДАННЫХ ===
        try:
            self.cursor.execute("CREATE TABLE IF NOT EXISTS users \
                (member_id INTEGER NOT NULL, \
                marry INTEGER NOT NULL DEFAULT 0, \
                money INTEGER NOT NULL DEFAULT 100, \
                themes TEXT NOT NULL, \
                inst TEXT, \
                vk TEXT, \
                tg TEXT, \
                tiktok TEXT, \
                daily TEXT NOT NULL DEFAULT 0, \
                theme TEXT NOT NULL, \
                cases INTEGER NOT NULL DEFAULT 0)")

            self.cursor.execute("CREATE TABLE IF NOT EXISTS marrieges \
                (id INTEGER PRIMARY KEY AUTOINCREMENT, \
                partner_1 INTEGER NOT NULL, \
                partner_2 INTEGER NOT NULL, \
                balance INTEGER NOT NULL DEFAULT 0, \
                reg_marry TEXT, \
                loveRoom TEXT, \
                id_l TEXT, \
                themes TEXT NOT NULL, \
                theme TEXT NOT NULL)")

            self.cursor.execute("CREATE TABLE IF NOT EXISTS personal_roles \
                (role_id TEXT NOT NULL, \
                owner TEXT NOT NULL, \
                black_list TEXT NOT NULL, \
                time INTEGER NOT NULL)")
            
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    member_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            self.cursor.execute("CREATE TABLE IF NOT EXISTS voiceactivity_all \
                (member_id	INTEGER NOT NULL, \
                joined_at	VARCHAR(255), \
                left_at	VARCHAR(255), \
                total_hours INTEGER NOT NULL, \
                total_minutes INTEGER NOT NULL)")

            # Таблица магазина ролей
            self.cursor.execute("CREATE TABLE IF NOT EXISTS shop \
                (id INTEGER PRIMARY KEY AUTOINCREMENT, \
                owner INTEGER NOT NULL, \
                role INTEGER NOT NULL UNIQUE, \
                cost INTEGER NOT NULL DEFAULT 0, \
                count INTEGER NOT NULL DEFAULT 0, \
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")

            # Таблица аренды ролей
            self.cursor.execute("CREATE TABLE IF NOT EXISTS role_rentals \
                (id INTEGER PRIMARY KEY AUTOINCREMENT, \
                role_id INTEGER NOT NULL, \
                buyer_id INTEGER NOT NULL, \
                rental_date TIMESTAMP NOT NULL, \
                days_left INTEGER DEFAULT 30, \
                auto_renew INTEGER DEFAULT 1, \
                is_active INTEGER DEFAULT 1, \
                UNIQUE(role_id, buyer_id))")

            # Таблица инвентаря (купленные роли)
            self.cursor.execute("CREATE TABLE IF NOT EXISTS user_inventory \
                (id INTEGER PRIMARY KEY AUTOINCREMENT, \
                user_id INTEGER NOT NULL, \
                role_id INTEGER NOT NULL, \
                role_name TEXT NOT NULL, \
                purchase_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP, \
                days_left INTEGER DEFAULT 30, \
                is_active INTEGER DEFAULT 1, \
                UNIQUE(user_id, role_id))")

            # НОВАЯ ТАБЛИЦА: данные ролей (градиент, значок)
            self.cursor.execute("CREATE TABLE IF NOT EXISTS role_data \
                (role_id INTEGER PRIMARY KEY, \
                gradient TEXT, \
                icon_url TEXT, \
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")

            # ОБНОВЛЕННАЯ ТАБЛИЦА personal_rooms с новыми полями
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS personal_rooms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    channel_id INTEGER,
                    activity INTEGER DEFAULT 0,
                    total_time INTEGER DEFAULT 0,
                    is_hidden INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Проверяем и добавляем недостающие колонки в personal_rooms
            self.cursor.execute("PRAGMA table_info(personal_rooms)")
            personal_room_columns = {column[1] for column in self.cursor.fetchall()}
            personal_room_migrations = {
                "channel_id": "INTEGER",
                "activity": "INTEGER DEFAULT 0",
                "total_time": "INTEGER DEFAULT 0",
                "is_hidden": "INTEGER DEFAULT 0",
                "created_at": "TIMESTAMP",
            }
            for column_name, column_sql in personal_room_migrations.items():
                if column_name not in personal_room_columns:
                    self.cursor.execute(
                        f"ALTER TABLE personal_rooms ADD COLUMN {column_name} {column_sql}"
                    )
            
            # Конвертируем старые даты в правильный формат
            try:
                self.cursor.execute("""
                    UPDATE personal_rooms
                    SET created_at = datetime(CAST(created_at AS INTEGER), 'unixepoch')
                    WHERE created_at IS NOT NULL
                      AND CAST(created_at AS TEXT) NOT LIKE '%-%'
                      AND CAST(created_at AS INTEGER) > 1000000000
                """)
                self.cursor.execute("""
                    UPDATE personal_rooms
                    SET created_at = CURRENT_TIMESTAMP
                    WHERE created_at IS NULL
                """)
            except:
                pass
            
            # НОВАЯ ТАБЛИЦА: доступ к комнатам
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS room_access (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(room_id, user_id)
                )
            """)
            
            # НОВАЯ ТАБЛИЦА: видимость ролей для пользователей
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_role_visibility (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    hidden INTEGER DEFAULT 0,
                    UNIQUE(user_id, role_id)
                )
            """)

            self.conn.commit()
            self.ensure_meta_table()
            self.repair_voiceactivity_totals()
            logger.info("Таблицы в основной БД созданы или уже существуют")
            
        except Error as e:
            logger.error(f"Ошибка при создании таблиц в основной БД: {e}")
            return False

        # === СОЗДАНИЕ ТАБЛИЦ В ЛОГОВОЙ БАЗЕ ДАННЫХ ===
        try:
            # Таблица для истории браков
            self.cursor_log.execute("CREATE TABLE IF NOT EXISTS marries_history \
                (id INTEGER PRIMARY KEY AUTOINCREMENT, \
                partner_1 INTEGER NOT NULL, \
                partner_2 INTEGER NOT NULL, \
                type TEXT NOT NULL, \
                time INTEGER NOT NULL)")
            
            # Таблица для счётчика сообщений
            self.cursor_log.execute("CREATE TABLE IF NOT EXISTS messages \
                (member_id INTEGER NOT NULL PRIMARY KEY, \
                count INTEGER NOT NULL DEFAULT 0)")
            
            self.conn_log.commit()
            logger.info("Таблицы в логовой БД созданы или уже существуют")
            
        except Error as e:
            logger.error(f"Ошибка при создании таблиц в логовой БД: {e}")
            return False

        return True

    # GENERIC FUNCTIONS

    def execute_statement(self, statement, params=None):
        try:
            if params:
                self.cursor.execute(statement, params)
            else:
                self.cursor.execute(statement)
            self.conn.commit()
            return True
        except Error as e:
            logger.error(e)
            return False

    def get_value(self, member_id, table, attribute):

        if self.member_exists(member_id):

            statement = f"SELECT {attribute} FROM {table} WHERE member_id = {int(member_id)}"

            if self.execute_statement(statement):

                result = self.cursor.fetchall()
                return result[0][0]
            
            return 0
        
        return 0

    def member_exists(self, member_id):
        self.cursor.execute(f"SELECT member_id FROM users WHERE member_id={member_id}")
        return self.cursor.fetchone() is not None

    # Economy

    # Добавляем нового пользователя в основную базу
    def write_new_user(self, member):
        self.cursor.execute(f"SELECT member_id FROM users WHERE member_id={member.id}")

        if not member.bot:
            if self.cursor.fetchone() is None:
                self.cursor.execute(f"INSERT INTO users (member_id, marry, money, themes, inst, vk, tg, tiktok, daily, theme, cases) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", 
                                   (member.id, 0, 100, '[]', None, None, None, None, 0, 'theme_default', 0))
            else:
                pass
            self.conn.commit()

    # Получаем баланс
    def get_balance(self, member_id):
        self.cursor.execute('SELECT money FROM users WHERE member_id=?', (member_id,))
        result = self.cursor.fetchone()

        if result is not None:
            return result[0]
        else:
            return 0

    # Передача денег можно использовать get_balance
    def transfer_money(self, member_1, member_2, amount):
        for row in self.cursor.execute(f'SELECT money FROM users where member_id=?', (member_1.id,)):
            self.cursor.execute(f'UPDATE users SET money="{int(row[0]) - int(amount)}" where member_id=?', (member_1.id,))

            for row_1 in self.cursor.execute(f'SELECT money FROM users where member_id=?', (member_2.id,)):
                self.cursor.execute(f'UPDATE users SET money="{int(row_1[0]) + int(amount)}" where member_id=?', (member_2.id,))

        self.conn.commit()

    # Получаем нужную соц.сеть
    def get_social(self, member_id, type):
        for row in self.cursor.execute(f'SELECT {type} from users where member_id=?', (member_id,)):
            if str(row[0]).__len__() > 1:
                if row[0] == False or row[0] == None:
                    return " "
                else:
                    return row[0]
            else:
                return False

    # Устанавлием нужную соц.сеть
    def set_social(self, social, social_id, member_id):
        social_id = social_id.replace(' ', '')

        if social == "inst":
            self.cursor.execute(f'UPDATE users SET inst="{social_id}" where member_id=?', (member_id,))
        elif social == "vk":
            self.cursor.execute(f'UPDATE users SET vk="{social_id}" where member_id=?', (member_id,))
        elif social == "tg":
            self.cursor.execute(f'UPDATE users SET tg="{social_id}" where member_id=?', (member_id,))
        elif social == "tiktok":
            self.cursor.execute(f'UPDATE users SET tiktok="{social_id}" where member_id=?', (member_id,))
        
        self.conn.commit()

    # Получаем все темы пользователя
    def get_themes(self, member):
        self.cursor.execute('SELECT themes FROM users WHERE member_id=?', (member.id,))
        result = self.cursor.fetchone()

        if result is not None:
            return literal_eval(result[0])
        else:
            return 0
        
    # Выдаём тему
    def give_theme(self, member, theme):
        themes = self.get_themes(member)

        themes.append(theme)

        self.cursor.execute(f'UPDATE users SET themes=? where member_id=?', (json.dumps(themes), member.id,))

        self.conn.commit()
        
    # Получаем установленную тему у пользователя
    def get_active_theme(self, member):
        self.cursor.execute('SELECT theme FROM users WHERE member_id=?', (member.id,))
        result = self.cursor.fetchone()

        if result is not None:
            return result[0]
        else:
            return 0
        
    # Устанавливаем тему
    def set_active_theme(self, member, theme):
        self.cursor.execute(f'UPDATE users SET theme="{theme}" where member_id=?', (member.id,))

        self.conn.commit()

    # Получаем общий голосовой онлайн
    def get_total_online(self, member_id):
        for row in self.cursor.execute(f'SELECT total_hours, total_minutes FROM voiceactivity_all where member_id=?', (member_id,)):
            hours, minutes = self.normalize_voice_time(row[0], row[1]) or (0, 0)
            total_online = f"{hours} ч. {minutes} мин." if minutes else f"{hours} ч."
            return total_online

    # Получаем место пользователя в топе по голосовой активности
    def get_user_voice_rank(self, user_id):
        """Получение места пользователя в топе по голосовой активности"""
        self.cursor.execute("""
            SELECT COUNT(*) + 1 
            FROM voiceactivity_all 
            WHERE total_hours > (SELECT COALESCE(total_hours, 0) FROM voiceactivity_all WHERE member_id = ?)
               OR (total_hours = (SELECT COALESCE(total_hours, 0) FROM voiceactivity_all WHERE member_id = ?) 
                   AND total_minutes > (SELECT COALESCE(total_minutes, 0) FROM voiceactivity_all WHERE member_id = ?))
        """, (user_id, user_id, user_id))
        result = self.cursor.fetchone()
        
        if result and result[0] is not None:
            return result[0]
        
        # Если пользователь не найден в таблице, возвращаем 0
        return 0

    # Получаем последнюю дату получение ежедневной награды
    def get_daily_award(self, member_id):
        self.cursor.execute('SELECT daily FROM users WHERE member_id=?', (member_id,))
        result = self.cursor.fetchone()

        if result is not None:
            return result[0]
        else:
            return 0

    # Обновляем дату получения ежедневной награды
    def update_daily_award(self, member_id, newdate):
        statement = "UPDATE users SET daily = ? WHERE member_id = ?"
        if self.cursor.execute(statement, [newdate, member_id]):
            self.conn.commit()
            return True
        return False

    # Устанавливаем определенный баланс
    def set_money(self, member_id, money):
        statement = "UPDATE users SET money = ? WHERE member_id = ?"
        if self.cursor.execute(statement, (money, member_id)):
            self.conn.commit()
            return True
        return False

    # Выдача денег
    def give_money(self, member_id, money):
        statement = f"UPDATE users SET money = money + {int(money)} WHERE member_id = {int(member_id)}"
        if self.execute_statement(statement):
            self.conn.commit()
            return True
        return False

    # Списание денег
    def take_money(self, member_id, money):
        statement = f"UPDATE users SET money = money - {int(money)} WHERE member_id = {int(member_id)}"
        if self.execute_statement(statement):
            self.conn.commit()
            return True
        return False

    # Получить топ пользователей по голосовому онлайну
    def get_top_users_online(self, max_total_minutes=None):
        self.repair_voiceactivity_totals(max_total_minutes=max_total_minutes)
        self.cursor.execute(f'SELECT member_id, total_hours, total_minutes FROM voiceactivity_all ORDER BY total_hours DESC, total_minutes DESC LIMIT 30')
        row = self.cursor.fetchall()
        
        return row

    # Получить топ пользователей по балансу
    def get_top_users_balance(self):
        self.cursor.execute(f'SELECT member_id, money FROM users ORDER BY money DESC LIMIT 30')
        row = self.cursor.fetchall()
        
        return row
    
    # Получить топ пользователей по сообщениям
    def get_top_users_messages(self):
        self.cursor_log.execute(f'SELECT member_id, count FROM messages ORDER BY count DESC LIMIT 30')
        row = self.cursor_log.fetchall()

        return row

    # НОВЫЙ МЕТОД: Получить топ пар по времени в любовной комнате
    def get_top_love_online(self, limit=30):
        """Получает топ пар по времени в любовной комнате"""
        try:
            self.cursor.execute("""
                SELECT id, partner_1, partner_2, loveRoom 
                FROM marrieges 
                ORDER BY id DESC
            """)
            
            results = self.cursor.fetchall()
            
            couples_data = []
            for row in results:
                marriage_id = row[0]
                partner_1 = row[1]
                partner_2 = row[2]
                
                # Парсим JSON из loveRoom
                try:
                    loveRoom_data = json.loads(row[3]) if row[3] else {"total_hours": 0, "total_minutes": 0}
                except:
                    loveRoom_data = {"total_hours": 0, "total_minutes": 0}
                
                total_hours = loveRoom_data.get('total_hours', 0)
                total_minutes = loveRoom_data.get('total_minutes', 0)
                
                # Добавляем в список для сортировки
                couples_data.append({
                    'partner_1': partner_1,
                    'partner_2': partner_2,
                    'total_hours': total_hours,
                    'total_minutes': total_minutes,
                    'total_in_minutes': (total_hours * 60) + total_minutes
                })
            
            # Сортируем по общему времени
            couples_data.sort(key=lambda x: x['total_in_minutes'], reverse=True)
            
            # Ограничиваем количество
            couples_data = couples_data[:limit]
            
            # Форматируем результат для совместимости с существующим кодом
            result = []
            for couple in couples_data:
                # Возвращаем partner_1 как идентификатор пары и время
                result.append((couple['partner_1'], couple['total_hours'], couple['total_minutes']))
            
            return result
            
        except Exception as e:
            logger.error(f"Ошибка при получении топа пар по онлайну: {e}")
            return []

    # НОВЫЙ МЕТОД: Получить топ пар по общему балансу
    def get_top_love_balance(self, limit=30):
        """Получает топ пар по общему балансу"""
        try:
            self.cursor.execute("""
                SELECT id, partner_1, partner_2, balance 
                FROM marrieges 
                ORDER BY balance DESC
                LIMIT ?
            """, (limit,))
            
            results = self.cursor.fetchall()
            
            couples = []
            for row in results:
                marriage_id = row[0]
                partner_1 = row[1]
                partner_2 = row[2]
                balance = row[3] if row[3] else 0
                
                couples.append((partner_1, balance))
            
            return couples
            
        except Exception as e:
            logger.error(f"Ошибка при получении топа пар по балансу: {e}")
            return []

    # Transactions

    # Записываем пользователю новую транзакцию
    def write_new_transactions(self, member, reason, amount):
        """Запись новой транзакции"""
        try:
            # Проверяем существование таблицы
            self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='transactions'")
            if not self.cursor.fetchone():
                self.cursor.execute("""
                    CREATE TABLE transactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        member_id INTEGER NOT NULL,
                        reason TEXT NOT NULL,
                        amount INTEGER NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
            
            self.cursor.execute(
                "INSERT INTO transactions (member_id, reason, amount) VALUES (?, ?, ?)",
                (member.id, reason, amount)
            )
            self.conn.commit()
            logger.info(f"Записана транзакция: {member.id} - {reason} - {amount}")
            return True
        except Exception as e:
            logger.error(f"Ошибка при записи транзакции: {e}")
            return False

    # Получаем все транзакции пользователя
    def get_user_transactions(self, member):
        try:
            self.cursor.execute('SELECT member_id, reason, amount, created_at FROM transactions WHERE member_id=? ORDER BY created_at DESC', (member.id,))
            row = self.cursor.fetchall()
            return row
        except Exception as e:
            logger.error(f"Ошибка при получении транзакций: {e}")
            return []

    # Получаем историю открытий кейсов пользователя
    def get_case_history(self, user_id: int, limit: int = 10, offset: int = 0):
        """Получить историю открытий кейсов пользователя"""
        try:
            self.cursor.execute("""
                SELECT id, amount, created_at 
                FROM transactions 
                WHERE member_id = ? AND reason LIKE 'Открытие кейса%'
                ORDER BY created_at DESC 
                LIMIT ? OFFSET ?
            """, (user_id, limit, offset))
            return self.cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка при получении истории кейсов: {e}")
            return []

    # Получаем количество открытий кейсов пользователя
    def get_history_count(self, user_id: int) -> int:
        """Получить общее количество открытий кейсов пользователя"""
        try:
            self.cursor.execute("""
                SELECT COUNT(*) 
                FROM transactions 
                WHERE member_id = ? AND reason LIKE 'Открытие кейса%'
            """, (user_id,))
            result = self.cursor.fetchone()
            return result[0] if result else 0
        except Exception as e:
            logger.error(f"Ошибка при подсчете истории: {e}")
            return 0

    # ============================================================
    # МЕТОДЫ ДЛЯ КЕЙСОВ
    # ============================================================

    def get_cases(self, user_id: int) -> int:
        """Получить количество кейсов у пользователя"""
        try:
            self.cursor.execute("SELECT cases FROM users WHERE member_id = ?", (user_id,))
            result = self.cursor.fetchone()
            return result[0] if result else 0
        except Exception as e:
            logger.error(f"Ошибка при получении кейсов пользователя {user_id}: {e}")
            return 0

    def update_cases(self, user_id: int, amount: int) -> bool:
        """Обновить количество кейсов (прибавить или отнять)"""
        try:
            self.cursor.execute("UPDATE users SET cases = cases + ? WHERE member_id = ?", (amount, user_id))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при обновлении кейсов пользователя {user_id}: {e}")
            return False

    def set_cases(self, user_id: int, amount: int) -> bool:
        """Установить точное количество кейсов"""
        try:
            self.cursor.execute("UPDATE users SET cases = ? WHERE member_id = ?", (amount, user_id))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при установке кейсов пользователя {user_id}: {e}")
            return False

    # ============================================================
    # ОСТАЛЬНЫЕ МЕТОДЫ
    # ============================================================

    # Marry

    # Записываем новый брак
    def write_new_marry(self, member_1, member_2):
        actual_date = datetime.now()
        end = actual_date + timedelta(days=30)

        room = {"name": 0, "total_hours": 0, "total_minutes": 0, "joined_at": 0, "id": 0, "bought": False}

        statement = f"INSERT INTO marrieges (partner_1, partner_2, balance, reg_marry, loveRoom, id_l, themes, theme) VALUES ({member_1.id}, '{member_2.id}', 0, '{int(actual_date.timestamp())}', '{json.dumps(room)}', 0, '[]', 'theme_default')"
        if self.execute_statement(statement):
            self.conn.commit()

            for row in self.cursor.execute(f'SELECT id FROM marrieges where partner_1=? OR partner_2=?', (member_1.id, member_2.id,)):
                self.cursor.execute(f'UPDATE users SET marry="{row[0]}" where member_id=?', (member_1.id,))
                self.cursor.execute(f'UPDATE users SET marry="{row[0]}" where member_id=?', (member_2.id,))

                self.conn.commit()
                
                return True
        return False

    # Есть ли у него уже брак?
    def is_marry(self, member_id):
        for row in self.cursor.execute(f'SELECT marry FROM users where member_id=?', (member_id,)):
            if row[0] != 0:
                return True
            else:
                return False

    # Получаем информацию о браке
    def get_info_marriege(self, member):
        for row in self.cursor.execute(f'SELECT id, partner_1, partner_2, balance, reg_marry, loveRoom FROM marrieges where partner_1=? OR partner_2=?', (member.id, member.id,)):
            return row

    def get_info_marriege_by_user_id(self, user_id):
        """Получает информацию о браке по ID пользователя"""
        try:
            self.cursor.execute("SELECT id, partner_1, partner_2, balance, reg_marry, loveRoom FROM marrieges WHERE partner_1=? OR partner_2=?", (user_id, user_id))
            row = self.cursor.fetchone()
            return row
        except:
            return None

    def write_data_loveRoom(self, member, type, value):
        if type == 'id':
            loveRoom_data = self.get_data_loveRoom(member)
            
            loveRoom_data['id'] = 0

            self.cursor.execute("UPDATE marrieges SET loveRoom=?, id_l=? WHERE partner_1=? OR partner_2=?", (json.dumps(loveRoom_data), value, member.id, member.id,))
        elif type == 'bought':
            loveRoom_data = self.get_data_loveRoom(member)
            
            if loveRoom_data:
                loveRoom_data['bought'] = value
            else:
                loveRoom_data = {"name": 0, "total_hours": 0, "total_minutes": 0, "joined_at": 0, "id": 0, "bought": value}
            
            self.cursor.execute("UPDATE marrieges SET loveRoom=? WHERE partner_1=? OR partner_2=?", (json.dumps(loveRoom_data), member.id, member.id,))
        else:
            loveRoom_data = self.get_data_loveRoom(member)
            
            if loveRoom_data:
                loveRoom_data[type] = value
            else:
                loveRoom_data = {"name": 0, "total_hours": 0, "total_minutes": 0, "joined_at": 0, "id": 0, "bought": False}
                loveRoom_data[type] = value
            
            self.cursor.execute("UPDATE marrieges SET loveRoom=? WHERE partner_1=? OR partner_2=?", (json.dumps(loveRoom_data), member.id, member.id,))

        self.conn.commit()

    def update_data_loveRoom(self, id):
        self.cursor.execute("UPDATE marrieges SET id_l=? WHERE id_l=?", (0, id,))
        self.conn.commit()

    def get_data_loveRoom(self, member):
        try:
            loveRoom_data = {}

            for row in self.cursor.execute("SELECT loveRoom, id_l FROM marrieges WHERE partner_1=? OR partner_2=?", (member.id, member.id,)):
                loveRoom_data = json.loads(row[0])
                loveRoom_data['id'] = int(row[1])
                
                if 'bought' not in loveRoom_data:
                    loveRoom_data['bought'] = False

            return loveRoom_data
        except Exception:
            return {"name": 0, "total_hours": 0, "total_minutes": 0, "joined_at": 0, "id": 0, "bought": False}

    def get_balance_marry(self, member):
        for row in self.cursor.execute("SELECT balance FROM marrieges WHERE partner_1=? OR partner_2=?", (member.id, member.id,)):
            return row[0]

    # Получаем все темы
    def get_themes_lprofile(self, member):
        self.cursor.execute('SELECT themes FROM marrieges WHERE partner_1=? OR partner_2=?', (member.id, member.id,))
        result = self.cursor.fetchone()

        if result is not None:
            return literal_eval(result[0])
        else:
            return 0
        
    # Выдаём тему
    def give_theme_lprofile(self, member, theme):
        themes = self.get_themes_lprofile(member)

        themes.append(theme)

        self.cursor.execute(f'UPDATE marrieges SET themes=? where partner_1=? OR partner_2=?', (json.dumps(themes), member.id, member.id,))

        self.conn.commit()
        
    # Получаем установленную тему у пользователя
    def get_active_theme_lprofile(self, member):
        self.cursor.execute('SELECT theme FROM marrieges WHERE partner_1=? OR partner_2=?', (member.id, member.id,))
        result = self.cursor.fetchone()

        if result is not None:
            return result[0]
        else:
            return 0
        
    # Устанавливаем тему
    def set_active_theme_lprofile(self, member, theme):
        self.cursor.execute(f'UPDATE marrieges SET theme="{theme}" where partner_1=? OR partner_2=?', (member.id, member.id,))

        self.conn.commit()

    # Устанавливаем определенный баланс
    def set_money_marry(self, member, money):
        statement = f"UPDATE marrieges SET balance = {money} WHERE partner_1 = {member.id} OR partner_2 = {member.id}"

        if self.execute_statement(statement):
            self.conn.commit()
            return True
        return False

    # Выдаём деньги
    def give_balance_marry(self, member, value):
        current_balance = self.get_balance_marry(member)

        self.cursor.execute("UPDATE marrieges SET balance=? WHERE partner_1=? OR partner_2=?", (int(current_balance + value), member.id, member.id,))

        self.conn.commit()

    # Списание денег
    def take_money_marry(self, member, money):
        current_balance = self.get_balance_marry(member)
        statement = f"UPDATE marrieges SET balance = {current_balance - money} WHERE partner_1 = {member.id} OR partner_2 = {member.id}"
        
        if self.execute_statement(statement):
            self.conn.commit()
            return True
        return False
    
    # ИСПРАВЛЕННЫЙ МЕТОД write_log_in_history
    def write_log_in_history(self, partner_1, partner_2, type):
        """Записывает историю брака в логовую БД"""
        try:
            # Явно указываем колонки, в которые вставляем данные
            # id генерируется автоматически (AUTOINCREMENT)
            self.cursor_log.execute(
                "INSERT INTO marries_history (partner_1, partner_2, type, time) VALUES (?, ?, ?, ?)", 
                (partner_1.id, partner_2.id, type, int(datetime.now().timestamp()))
            )
            self.conn_log.commit()
            logger.info(f"Записана история брака: {partner_1.id} + {partner_2.id} = {type}")
        except Exception as e:
            logger.error(f"Ошибка при записи в историю браков: {e}")

    def get_marries_history(self, member):
        self.cursor_log.execute(f'SELECT partner_1, partner_2, type, time FROM marries_history WHERE partner_1={member.id} OR partner_2={member.id} ORDER BY type ASC')
        row = self.cursor_log.fetchall()
        
        return row

    # Развод :(
    def divorce_marriege(self, partner_1, partner_2):
        self.cursor.execute(f'DELETE FROM marrieges WHERE partner_1=?', (partner_1,))

        self.cursor.execute(f'UPDATE users SET marry=0 where member_id=?', (partner_1,))
        self.cursor.execute(f'UPDATE users SET marry=0 where member_id=?', (partner_2,))

        self.conn.commit()

    # Personal roles

    # Добавляем новую личную роль в базу
    def write_new_role(self, member, role):
        time_pay = datetime.now() + timedelta(days=30)

        self.cursor.execute(f"INSERT INTO personal_roles VALUES ({role.id}, {member.id}, '[]', {int(time_pay.timestamp())})")

        self.conn.commit()

    # Есть у пользователя личные роли? 
    def is_exists_role(self, member):
        self.cursor.execute(f"SELECT role_id FROM personal_roles WHERE owner={member.id}")

        if self.cursor.fetchone() is None:
            return False
        else:
            return True
        
    # Проверка, является ли роль личной
    def is_personal_role(self, role_id):
        self.cursor.execute("SELECT role_id FROM personal_roles WHERE role_id=?", (role_id,))
        return self.cursor.fetchone() is not None
        
    # Проверка, принадлежит ли роль пользователю
    def is_owner_role(self, user, role):
        self.cursor.execute("SELECT role_id FROM personal_roles WHERE owner=? AND role_id=?", (user.id, role.id))
        return self.cursor.fetchone() is not None

    # Получаем все личные роли пользователя
    def get_all_roles(self, member):
        roles_id = []

        for row in self.cursor.execute(f'SELECT role_id FROM personal_roles where owner=?', (member.id,)):
            roles_id.append(row[0])

        return roles_id
    
    # Получаем владельца роли
    def get_role_owner(self, role_id):
        self.cursor.execute("SELECT owner FROM personal_roles WHERE role_id=?", (role_id,))
        result = self.cursor.fetchone()
        if result:
            return result[0]
        return None
    
    # НОВЫЙ МЕТОД: Получаем ID всех личных ролей
    def get_all_personal_role_ids(self):
        """Получает ID всех личных ролей"""
        try:
            self.cursor.execute("SELECT role_id FROM personal_roles")
            results = self.cursor.fetchall()
            return [row[0] for row in results]
        except Exception as e:
            logger.error(f"Ошибка при получении всех личных ролей: {e}")
            return []
    
    # Обновляем время оплаты роли
    def update_role_payment_time(self, role_id):
        time_pay = datetime.now() + timedelta(days=30)
        self.cursor.execute("UPDATE personal_roles SET time=? WHERE role_id=?", (int(time_pay.timestamp()), role_id))
        self.conn.commit()
    
    # Удаляем личную роль
    def delete_role(self, role):
        self.cursor.execute(f'DELETE FROM personal_roles WHERE role_id=?', (role.id,))
        self.conn.commit()

    def get_time_to_pay(self, role):
        self.cursor.execute(f"SELECT time FROM personal_roles WHERE role_id={role.id}")

        result = self.cursor.fetchone()

        if result is None:
            return False
        else:
            return result[0]

    # НОВЫЕ МЕТОДЫ ДЛЯ ВИДИМОСТИ РОЛЕЙ
    
    def toggle_role_visibility(self, user_id: int, role_id: int, is_hidden: bool):
        """Установить видимость роли (скрыта или нет)"""
        try:
            # Проверяем, существует ли запись
            self.cursor.execute("SELECT hidden FROM user_role_visibility WHERE user_id = ? AND role_id = ?", (user_id, role_id))
            result = self.cursor.fetchone()
            
            if result:
                self.cursor.execute("UPDATE user_role_visibility SET hidden = ? WHERE user_id = ? AND role_id = ?", 
                                  (1 if is_hidden else 0, user_id, role_id))
            else:
                self.cursor.execute("INSERT INTO user_role_visibility (user_id, role_id, hidden) VALUES (?, ?, ?)",
                                  (user_id, role_id, 1 if is_hidden else 0))
            
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при установке видимости роли: {e}")
            return False

    def is_role_hidden(self, user_id: int, role_id: int) -> bool:
        """Проверить, скрыта ли роль для пользователя"""
        try:
            self.cursor.execute("SELECT hidden FROM user_role_visibility WHERE user_id = ? AND role_id = ?", (user_id, role_id))
            result = self.cursor.fetchone()
            return result is not None and result[0] == 1
        except Exception as e:
            logger.error(f"Ошибка при проверке видимости роли: {e}")
            return False

    def get_hidden_roles(self, user_id: int):
        """Получить список скрытых ролей пользователя"""
        try:
            self.cursor.execute("SELECT role_id FROM user_role_visibility WHERE user_id = ? AND hidden = 1", (user_id,))
            return [row[0] for row in self.cursor.fetchall()]
        except Exception as e:
            logger.error(f"Ошибка при получении скрытых ролей: {e}")
            return []

    def get_visible_roles_for_user(self, user_id: int, roles_list: list):
        """Фильтрует список ролей, оставляя только видимые для пользователя"""
        hidden_roles = self.get_hidden_roles(user_id)
        return [role for role in roles_list if role.id not in hidden_roles]

    # ============================================================
    # ИСПРАВЛЕННЫЕ МЕТОДЫ ДЛЯ МАГАЗИНА (БЕЗ ДУБЛИКАТОВ)
    # ============================================================

    def is_role_in_shop(self, role_id):
        """Проверяет, выставлена ли роль в магазин"""
        try:
            self.cursor.execute("SELECT role FROM shop WHERE role = ?", (role_id,))
            return self.cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Ошибка при проверке роли {role_id} в магазине: {e}")
            return False

    def add_role_to_shop(self, owner_id, role_id, price):
        """Добавляет роль в магазин или обновляет цену (без дубликатов)"""
        try:
            # Проверяем, существует ли уже запись
            self.cursor.execute("SELECT role FROM shop WHERE role = ?", (role_id,))
            existing = self.cursor.fetchone()
            
            if existing:
                # Если запись существует - обновляем цену и владельца
                self.cursor.execute("""
                    UPDATE shop 
                    SET owner = ?, cost = ?, count = COALESCE(count, 0)
                    WHERE role = ?
                """, (owner_id, price, role_id))
                logger.info(f"Обновлена цена роли {role_id} в магазине: {price}")
            else:
                # Если записи нет - создаём новую
                self.cursor.execute("""
                    INSERT INTO shop (owner, role, cost, count) 
                    VALUES (?, ?, ?, 0)
                """, (owner_id, role_id, price))
                logger.info(f"Роль {role_id} добавлена в магазин за {price}")
            
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при добавлении роли {role_id} в магазин: {e}")
            return False

    def remove_role_from_shop(self, role_id):
        """Удаляет роль из магазина"""
        try:
            self.cursor.execute("DELETE FROM shop WHERE role = ?", (role_id,))
            self.conn.commit()
            logger.info(f"Роль {role_id} удалена из магазина")
            return True
        except Exception as e:
            logger.error(f"Ошибка при удалении роли {role_id} из магазина: {e}")
            return False

    def update_role_shop_price(self, role_id, new_price):
        """Обновляет цену роли в магазине"""
        try:
            self.cursor.execute("""
                UPDATE shop SET cost = ? 
                WHERE role = ?
            """, (new_price, role_id))
            self.conn.commit()
            logger.info(f"Цена роли {role_id} обновлена на {new_price}")
            return True
        except Exception as e:
            logger.error(f"Ошибка при обновлении цены роли {role_id}: {e}")
            return False

    # Получение всех ролей из магазина
    def get_shop_roles(self):
        try:
            self.cursor.execute("""
                SELECT s.owner, s.role, s.cost,
                       COALESCE((
                           SELECT MAX(COALESCE(s2.count, 0))
                           FROM shop s2
                           WHERE s2.role = s.role
                       ), 0) AS count,
                       30 AS days_left
                FROM shop s
                WHERE s.id = (
                    SELECT MIN(s2.id)
                    FROM shop s2
                    WHERE s2.role = s.role
                )
                ORDER BY s.id ASC
            """)
            results = self.cursor.fetchall()
            
            shop_roles = []
            for row in results:
                owner_id, role_id, cost, count, days_left = row
                
                if days_left is None or days_left <= 0:
                    days_left = 30
                elif days_left > 30:
                    days_left = 30
                
                if count is None:
                    count = 0
                    
                shop_roles.append((owner_id, role_id, cost, count, int(days_left)))
            
            return shop_roles
        except Exception as e:
            logger.error(f"Ошибка при получении ролей из магазина: {e}")
            return []

    # Увеличение счётчика продаж
    def increment_role_purchase(self, role_id):
        try:
            self.cursor.execute("UPDATE shop SET count = count + 1 WHERE role=?", (role_id,))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при увеличении счётчика продаж роли {role_id}: {e}")
            return False
    
    # Получение информации о роли в магазине
    def get_shop_role_info(self, role_id):
        try:
            self.cursor.execute("SELECT owner, cost, count FROM shop WHERE role=?", (role_id,))
            result = self.cursor.fetchone()
            if result:
                return {
                    'owner_id': result[0],
                    'cost': result[1],
                    'purchase_count': result[2] if result[2] is not None else 0
                }
            return None
        except Exception as e:
            logger.error(f"Ошибка при получении информации о роли {role_id} в магазине: {e}")
            return None
    
    # Получение цены роли в магазине
    def get_role_shop_price(self, role_id):
        """Получить цену роли в магазине"""
        try:
            self.cursor.execute("SELECT cost FROM shop WHERE role=?", (role_id,))
            result = self.cursor.fetchone()
            if result:
                return result[0]
            return None
        except Exception as e:
            logger.error(f"Ошибка при получении цены роли {role_id} в магазине: {e}")
            return None

    # НОВЫЙ МЕТОД: Сохранение градиента роли
    def set_role_gradient(self, role_id, gradient_hex):
        """Сохранить градиент роли"""
        try:
            self.cursor.execute("""
                INSERT INTO role_data (role_id, gradient) 
                VALUES (?, ?)
                ON CONFLICT(role_id) DO UPDATE SET 
                gradient = ?, updated_at = CURRENT_TIMESTAMP
            """, (role_id, gradient_hex, gradient_hex))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при сохранении градиента роли {role_id}: {e}")
            return False

    # НОВЫЙ МЕТОД: Сохранение значка роли
    def set_role_icon(self, role_id, icon_url):
        """Сохранить значок роли"""
        try:
            self.cursor.execute("""
                INSERT INTO role_data (role_id, icon_url) 
                VALUES (?, ?)
                ON CONFLICT(role_id) DO UPDATE SET 
                icon_url = ?, updated_at = CURRENT_TIMESTAMP
            """, (role_id, icon_url, icon_url))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при сохранении значка роли {role_id}: {e}")
            return False

    # НОВЫЙ МЕТОД: Получение градиента роли
    def get_role_gradient(self, role_id):
        """Получить градиент роли"""
        try:
            self.cursor.execute("SELECT gradient FROM role_data WHERE role_id = ?", (role_id,))
            result = self.cursor.fetchone()
            if result:
                return result[0]
            return None
        except Exception as e:
            logger.error(f"Ошибка при получении градиента роли {role_id}: {e}")
            return None

    # НОВЫЙ МЕТОД: Получение значка роли
    def get_role_icon(self, role_id):
        """Получить значок роли"""
        try:
            self.cursor.execute("SELECT icon_url FROM role_data WHERE role_id = ?", (role_id,))
            result = self.cursor.fetchone()
            if result:
                return result[0]
            return None
        except Exception as e:
            logger.error(f"Ошибка при получении значка роли {role_id}: {e}")
            return None

    # Role rentals methods

    # Добавление записи об аренде роли
    def add_role_rental(self, role_id, buyer_id, days):
        """Добавляет запись об аренде роли с повторными попытками при блокировке"""
        def _execute():
            self.cursor.execute("""
                INSERT INTO role_rentals (role_id, buyer_id, rental_date, days_left, auto_renew, is_active) 
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(role_id, buyer_id) DO UPDATE SET 
                rental_date = CURRENT_TIMESTAMP, 
                days_left = ?,
                is_active = 1
            """, (role_id, buyer_id, datetime.now(), days, 1, 1, days))
            self.conn.commit()
            return True
        
        return self.execute_with_retry(_execute)

    # Продление аренды роли
    def extend_role_rental(self, role_id, buyer_id):
        def _execute():
            self.cursor.execute("""
                UPDATE role_rentals 
                SET rental_date = CURRENT_TIMESTAMP, days_left = 30, is_active = 1
                WHERE role_id = ? AND buyer_id = ?
            """, (role_id, buyer_id))
            self.conn.commit()
            return True
        
        return self.execute_with_retry(_execute)

    # Получение истёкших аренд
    def get_expired_role_rentals(self):
        self.cursor.execute("""
            SELECT role_id, buyer_id, auto_renew 
            FROM role_rentals 
            WHERE is_active = 1 AND datetime(rental_date, '+' || days_left || ' days') <= datetime('now')
        """)
        return self.cursor.fetchall()

    # Удаление записи об аренде
    def remove_role_rental(self, role_id, buyer_id):
        def _execute():
            self.cursor.execute("""
                UPDATE role_rentals SET is_active = 0 
                WHERE role_id = ? AND buyer_id = ?
            """, (role_id, buyer_id))
            self.conn.commit()
            return True
        
        return self.execute_with_retry(_execute)

    # Проверка, арендована ли роль пользователем
    def is_role_rented_by_user(self, role_id, user_id):
        self.cursor.execute("""
            SELECT * FROM role_rentals 
            WHERE role_id = ? AND buyer_id = ? AND is_active = 1
        """, (role_id, user_id))
        return self.cursor.fetchone() is not None

    # Получение информации об аренде
    def get_role_rental_info(self, role_id, buyer_id):
        self.cursor.execute("""
            SELECT *, 
                   CAST((julianday(rental_date) + days_left - julianday('now')) AS INTEGER) as days_left_calc
            FROM role_rentals 
            WHERE role_id = ? AND buyer_id = ? AND is_active = 1
        """, (role_id, buyer_id))
        result = self.cursor.fetchone()
        if result:
            days_left = result[7] if len(result) > 7 else result[4]
            return {
                'id': result[0],
                'role_id': result[1],
                'buyer_id': result[2],
                'rental_date': result[3],
                'days_left': days_left if days_left > 0 else 0,
                'auto_renew': result[5] == 1,
                'is_active': result[6] == 1
            }
        return None

    # Включение/отключение автопродления
    def set_auto_renew_role(self, role_id, user_id, enabled):
        def _execute():
            self.cursor.execute("""
                UPDATE role_rentals SET auto_renew = ? 
                WHERE role_id = ? AND buyer_id = ? AND is_active = 1
            """, (1 if enabled else 0, role_id, user_id))
            self.conn.commit()
            return True
        
        return self.execute_with_retry(_execute)
    
    # Получение всех активных аренд пользователя
    def get_user_active_rentals(self, user_id):
        self.cursor.execute("""
            SELECT role_id, rental_date, days_left, auto_renew
            FROM role_rentals 
            WHERE buyer_id = ? AND is_active = 1
        """, (user_id,))
        return self.cursor.fetchall()
    
    # Получение всех аренд роли
    def get_role_rentals(self, role_id):
        self.cursor.execute("""
            SELECT buyer_id, rental_date, days_left, auto_renew, is_active
            FROM role_rentals 
            WHERE role_id = ?
        """, (role_id,))
        return self.cursor.fetchall()

    # Inventory methods (купленные роли пользователя)

    def add_role_to_inventory(self, user_id, role_id, role_name, days=30):
        """Добавление купленной роли в инвентарь пользователя"""
        try:
            # Проверяем, есть ли уже такая роль в инвентаре
            self.cursor.execute('''
                SELECT id, days_left FROM user_inventory 
                WHERE user_id = ? AND role_id = ? AND is_active = 1
            ''', (user_id, role_id))
            
            existing = self.cursor.fetchone()
            
            if existing:
                # Обновляем оставшиеся дни
                new_days = existing[1] + days
                self.cursor.execute('''
                    UPDATE user_inventory 
                    SET days_left = ?, purchase_date = CURRENT_TIMESTAMP
                    WHERE user_id = ? AND role_id = ? AND is_active = 1
                ''', (new_days, user_id, role_id))
            else:
                # Добавляем новую роль
                self.cursor.execute('''
                    INSERT INTO user_inventory (user_id, role_id, role_name, days_left, is_active)
                    VALUES (?, ?, ?, ?, 1)
                ''', (user_id, role_id, role_name, days))
            
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при добавлении роли {role_id} в инвентарь пользователя {user_id}: {e}")
            return False

    def get_user_inventory(self, user_id):
        """Получение всех ролей пользователя из инвентаря"""
        try:
            self.cursor.execute('''
                SELECT role_id, role_name, purchase_date, days_left, is_active
                FROM user_inventory 
                WHERE user_id = ? AND is_active = 1
                ORDER BY purchase_date DESC
            ''', (user_id,))
            
            items = self.cursor.fetchall()
            
            if not items:
                return []
            
            result = []
            for item in items:
                # Рассчитываем оставшиеся дни
                days_left = item[3] if item[3] > 0 else 0
                result.append({
                    'role_id': item[0],
                    'role_name': item[1],
                    'purchase_date': item[2],
                    'days_left': days_left,
                    'is_active': item[4] == 1
                })
            
            return result
        except Exception as e:
            logger.error(f"Ошибка при получении инвентаря пользователя {user_id}: {e}")
            return []

    def remove_role_from_inventory(self, user_id, role_id):
        """Удаление роли из инвентаря пользователя"""
        try:
            self.cursor.execute('''
                UPDATE user_inventory SET is_active = 0 
                WHERE user_id = ? AND role_id = ? AND is_active = 1
            ''', (user_id, role_id))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при удалении роли {role_id} из инвентаря пользователя {user_id}: {e}")
            return False

    def update_role_days_in_inventory(self, user_id, role_id, days_left):
        """Обновление оставшихся дней у роли в инвентаре"""
        try:
            self.cursor.execute('''
                UPDATE user_inventory 
                SET days_left = ?
                WHERE user_id = ? AND role_id = ? AND is_active = 1
            ''', (days_left, user_id, role_id))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при обновлении дней роли {role_id}: {e}")
            return False

    def check_role_in_inventory(self, user_id, role_id):
        """Проверка, есть ли роль в инвентаре пользователя"""
        try:
            self.cursor.execute('''
                SELECT id FROM user_inventory 
                WHERE user_id = ? AND role_id = ? AND is_active = 1
            ''', (user_id, role_id))
            return self.cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Ошибка при проверке роли {role_id} в инвентаре: {e}")
            return False

    def get_expired_inventory_roles(self):
        """Получение ролей, у которых истек срок действия"""
        try:
            self.cursor.execute('''
                SELECT id, user_id, role_id, role_name, days_left
                FROM user_inventory 
                WHERE is_active = 1 AND days_left <= 0
            ''')
            return self.cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка при получении просроченных ролей: {e}")
            return []

    def decrease_inventory_days(self):
        """Уменьшение оставшихся дней у всех ролей (запускать раз в день)"""
        try:
            self.cursor.execute('''
                UPDATE user_inventory 
                SET days_left = days_left - 1 
                WHERE is_active = 1 AND days_left > 0
            ''')
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при уменьшении дней в инвентаре: {e}")
            return False

    # Tracker

    # Записываем нового пользователя в базу трекера
    def write_new_user_tracker(self, member):
        self.cursor.execute(f"SELECT member_id FROM voiceactivity_all where member_id={member.id}")

        if not member.bot:
            if self.cursor.fetchone() is None:
                self.cursor.execute(f"INSERT INTO voiceactivity_all VALUES ({member.id}, 0, 0, 0, 0)")
            else:
                pass
            self.conn.commit()

    # Получаем данные из трекера
    def get_data(self, member):
        for row in self.cursor.execute(f"SELECT joined_at, left_at, total_hours, total_minutes FROM voiceactivity_all where member_id={member.id}"):
            return row
        return None

    # Записываем действие пользователя
    def user_set_action_channel(self, member, action):
        self.write_new_user_tracker(member)

        if action == "join":
            self.cursor.execute(
                "UPDATE voiceactivity_all SET joined_at = ?, left_at = 0 WHERE member_id = ?",
                (int(datetime.timestamp(datetime.now())), member.id),
            )
        elif action == "left":
            self.cursor.execute(
                "UPDATE voiceactivity_all SET left_at = ? WHERE member_id = ?",
                (int(datetime.timestamp(datetime.now())), member.id),
            )

        self.conn.commit()

    # Обновляем данные в базе
    def update_data(self, member, type, total_hours, total_minutes):
        normalized = self.normalize_voice_time(total_hours, total_minutes)
        if normalized is None:
            logger.warning(f"Игнорируется невозможный онлайн для {member.id}: {total_hours} ч. {total_minutes} мин.")
            return False

        total_hours, total_minutes = normalized

        if type == 'default':
            self.write_new_user_tracker(member)
            self.cursor.execute(
                "UPDATE voiceactivity_all SET total_hours = ?, total_minutes = ? WHERE member_id = ?",
                (total_hours, total_minutes, member.id),
            )
            self.conn.commit()
            return True
        elif type == 'love':
            loveRoom_data = self.get_data_loveRoom(member)

            loveRoom_data["total_hours"] = total_hours
            loveRoom_data["total_minutes"] = total_minutes

            self.cursor.execute(f"UPDATE marrieges SET loveRoom=? WHERE partner_1=? OR partner_2=?", (json.dumps(loveRoom_data), member.id, member.id,))
            self.conn.commit()
            return True

        return False

    # Убираем даты входа и выхода
    def set_null_dates(self, member):
        self.cursor.execute(f"UPDATE voiceactivity_all SET joined_at=0, left_at=0 where member_id={member.id}")
        self.conn.commit()

    # --- НОВЫЙ МЕТОД: закрытие открытых сессий при старте ---
    def close_open_voice_sessions(self, active_member_ids):
        """
        Закрывает незавершённые голосовые сессии для активных пользователей
        и начинает новые сессии с текущего момента.
        """
        now_ts = int(datetime.timestamp(datetime.now()))
        updated = 0
        for member_id in active_member_ids:
            self.cursor.execute("SELECT joined_at FROM voiceactivity_all WHERE member_id = ?", (member_id,))
            row = self.cursor.fetchone()
            if not row:
                continue
            joined_at = row[0]
            if joined_at and int(joined_at) > 0:
                delta_minutes = (now_ts - int(joined_at)) // 60
                if delta_minutes > 0:
                    self.add_voice_time(member_id, delta_minutes)
                    updated += 1
            # Начинаем новую сессию
            self.cursor.execute(
                "UPDATE voiceactivity_all SET joined_at = ?, left_at = 0 WHERE member_id = ?",
                (now_ts, member_id)
            )
        self.conn.commit()
        return updated

    # ДОБАВЛЯЕМ МЕТОД add_voice_time (уже был, но оставлю для целостности)
    def add_voice_time(self, member_id, minutes):
        """Добавляет голосовое время пользователю"""
        logger.warning(f"🔥 ADD_VOICE_TIME: user={member_id}, minutes={minutes}")
        try:
            minutes = self.normalize_voice_delta_minutes(minutes)
            if minutes <= 0:
                return False

            # Проверяем, существует ли пользователь в таблице
            self.cursor.execute("SELECT member_id FROM voiceactivity_all WHERE member_id = ?", (member_id,))
            if not self.cursor.fetchone():
                # Если нет - создаем
                self.cursor.execute("INSERT INTO voiceactivity_all (member_id, joined_at, left_at, total_hours, total_minutes) VALUES (?, 0, 0, 0, 0)", (member_id,))

            self.cursor.execute("SELECT total_hours, total_minutes FROM voiceactivity_all WHERE member_id = ?", (member_id,))
            row = self.cursor.fetchone()
            current_hours, current_minutes = self.normalize_voice_time(row[0], row[1]) or (0, 0)
            total_minutes = current_hours * 60 + current_minutes + minutes
            new_hours = total_minutes // 60
            new_minutes = total_minutes % 60

            if new_hours > VOICE_MAX_REASONABLE_HOURS:
                logger.warning(f"Игнорируется переполнение голосового онлайна для {member_id}: {new_hours} ч.")
                return False

            self.cursor.execute(
                "UPDATE voiceactivity_all SET total_hours = ?, total_minutes = ? WHERE member_id = ?",
                (new_hours, new_minutes, member_id),
            )
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при добавлении голосового времени для {member_id}: {e}")
            return False

    # Counter messages

    def log_write_new_user(self, member):
        self.cursor_log.execute(f"SELECT member_id FROM messages WHERE member_id={member.id}")

        if not member.bot:
            if self.cursor_log.fetchone() is None:
                self.cursor_log.execute(f"INSERT INTO messages VALUES ({member.id}, 0)")
            else:
                pass
            self.conn_log.commit()

    def get_message_count(self, member):
        for row in self.cursor_log.execute(f'SELECT count FROM messages WHERE member_id={member.id}'):
            return row[0]
        return 0

    def save_message_count(self, messages):
        if messages:
            for key, value in messages.items():
                self.cursor_log.execute(
                    "INSERT INTO messages (member_id, count) VALUES (?, ?) "
                    "ON CONFLICT(member_id) DO UPDATE SET count = count + excluded.count",
                    (key, int(value)),
                )
            self.conn_log.commit()

    # ============================================================
    # МЕТОДЫ ДЛЯ PRIVATE ROOMS
    # ============================================================

    def write_new_personal_room(self, member, name):
        """Создает новую приватную комнату"""
        try:
            logger.info(f"Создание комнаты для {member.id} с именем {name}")
            self.cursor.execute("""
                INSERT INTO personal_rooms (owner_id, name) 
                VALUES (?, ?)
            """, (member.id, name))
            self.conn.commit()
            room_id = self.cursor.lastrowid
            logger.info(f"Комната создана с ID: {room_id}")
            return room_id
        except Exception as e:
            logger.error(f"Ошибка при создании комнаты: {e}")
            return None

    def get_user_rooms(self, user_id):
        """Получает все комнаты пользователя"""
        try:
            logger.info(f"Получение комнат для пользователя {user_id}")
            
            self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='personal_rooms'")
            if not self.cursor.fetchone():
                logger.error("Таблица personal_rooms не существует!")
                return []
            
            self.cursor.execute("""
                SELECT id, name, channel_id, activity, total_time, is_hidden, CAST(created_at AS TEXT)
                FROM personal_rooms 
                WHERE owner_id = ?
                ORDER BY id DESC
            """, (user_id,))
            rooms = self.cursor.fetchall()
            logger.info(f"Найдено комнат: {len(rooms)}")
            
            result = []
            for room in rooms:
                if len(room) >= 7:
                    result.append({
                        'id': room[0],
                        'name': room[1] if room[1] else "Без названия",
                        'channel_id': room[2] if len(room) > 2 else None,
                        'activity': room[3] if len(room) > 3 else 0,
                        'total_time': room[4] if len(room) > 4 else 0,
                        'is_hidden': room[5] if len(room) > 5 else 0,
                        'created_at': room[6] if len(room) > 6 else None
                    })
                else:
                    logger.warning(f"Неверное количество полей в комнате: {len(room)} - {room}")
            return result
        except Exception as e:
            logger.error(f"Ошибка при получении комнат пользователя {user_id}: {e}")
            return []

    def get_room_by_id(self, room_id):
        """Получает комнату по ID"""
        try:
            self.cursor.execute("""
                SELECT id, owner_id, name, channel_id, activity, total_time, is_hidden, CAST(created_at AS TEXT)
                FROM personal_rooms 
                WHERE id = ?
            """, (room_id,))
            room = self.cursor.fetchone()
            if room and len(room) >= 8:
                return {
                    'id': room[0],
                    'owner_id': room[1],
                    'name': room[2] if room[2] else "Без названия",
                    'channel_id': room[3] if len(room) > 3 else None,
                    'activity': room[4] if len(room) > 4 else 0,
                    'total_time': room[5] if len(room) > 5 else 0,
                    'is_hidden': room[6] if len(room) > 6 else 0,
                    'created_at': room[7] if len(room) > 7 else None
                }
            return None
        except Exception as e:
            logger.error(f"Ошибка при получении комнаты {room_id}: {e}")
            return None

    def get_room_by_channel(self, channel_id):
        """Получает комнату по ID канала"""
        try:
            self.cursor.execute("""
                SELECT id, owner_id, name, channel_id, activity, total_time, is_hidden, created_at
                FROM personal_rooms 
                WHERE channel_id = ?
            """, (channel_id,))
            room = self.cursor.fetchone()
            if room:
                return {
                    'id': room[0],
                    'owner_id': room[1],
                    'name': room[2] if room[2] else "Без названия",
                    'channel_id': room[3],
                    'activity': room[4] if room[4] is not None else 0,
                    'total_time': room[5] if room[5] is not None else 0,
                    'is_hidden': room[6] if room[6] is not None else 0,
                    'created_at': room[7]
                }
            return None
        except Exception as e:
            logger.error(f"Ошибка при получении комнаты по каналу {channel_id}: {e}")
            return None

    def update_room_channel(self, room_id, channel_id):
        """Обновляет ID канала комнаты"""
        try:
            self.cursor.execute("""
                UPDATE personal_rooms 
                SET channel_id = ? 
                WHERE id = ?
            """, (channel_id, room_id))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при обновлении канала комнаты {room_id}: {e}")
            return False

    def update_room_name(self, room_id, new_name):
        """Обновляет название комнаты"""
        try:
            self.cursor.execute("""
                UPDATE personal_rooms 
                SET name = ? 
                WHERE id = ?
            """, (new_name, room_id))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при обновлении названия комнаты {room_id}: {e}")
            return False

    def update_room_hidden(self, room_id, is_hidden):
        """Обновляет статус скрытости комнаты"""
        try:
            self.cursor.execute("""
                UPDATE personal_rooms 
                SET is_hidden = ? 
                WHERE id = ?
            """, (1 if is_hidden else 0, room_id))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при обновлении скрытости комнаты {room_id}: {e}")
            return False

    def delete_room(self, room_id):
        """Удаляет комнату"""
        try:
            # Удаляем доступы
            self.cursor.execute("DELETE FROM room_access WHERE room_id = ?", (room_id,))
            # Удаляем комнату
            self.cursor.execute("DELETE FROM personal_rooms WHERE id = ?", (room_id,))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при удалении комнаты {room_id}: {e}")
            return False

    def add_room_access(self, room_id, user_id):
        """Добавляет доступ пользователю к комнате"""
        try:
            self.cursor.execute("""
                INSERT OR IGNORE INTO room_access (room_id, user_id) 
                VALUES (?, ?)
            """, (room_id, user_id))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при добавлении доступа к комнате {room_id} для пользователя {user_id}: {e}")
            return False

    def remove_room_access(self, room_id, user_id):
        """Удаляет доступ пользователя к комнате"""
        try:
            self.cursor.execute("""
                DELETE FROM room_access 
                WHERE room_id = ? AND user_id = ?
            """, (room_id, user_id))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при удалении доступа к комнате {room_id} для пользователя {user_id}: {e}")
            return False

    def get_room_access(self, room_id):
        """Получает список пользователей с доступом к комнате"""
        try:
            self.cursor.execute("""
                SELECT user_id, granted_at 
                FROM room_access 
                WHERE room_id = ?
            """, (room_id,))
            return self.cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка при получении доступа к комнате {room_id}: {e}")
            return []

    def add_room_activity(self, room_id, amount=1):
        """Увеличивает активность комнаты (количество сообщений)"""
        try:
            self.cursor.execute("""
                UPDATE personal_rooms 
                SET activity = activity + ? 
                WHERE id = ?
            """, (amount, room_id))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при обновлении активности комнаты {room_id}: {e}")
            return False

    def add_room_time(self, room_id, seconds):
        """Добавляет время к общему времени комнаты (в секундах)"""
        try:
            if seconds <= 0:
                return False
            self.cursor.execute("""
                UPDATE personal_rooms 
                SET total_time = total_time + ? 
                WHERE id = ?
            """, (seconds, room_id))
            self.conn.commit()
            logger.info(f"Добавлено {seconds} секунд к комнате {room_id}")
            return True
        except Exception as e:
            logger.error(f"Ошибка при обновлении времени комнаты {room_id}: {e}")
            return False

    def get_top_rooms_by_time(self, limit=5):
        """Получает топ N комнат по времени в голосовом канале"""
        try:
            self.cursor.execute("""
                SELECT id, owner_id, name, total_time, channel_id, is_hidden 
                FROM personal_rooms 
                WHERE total_time > 0
                ORDER BY total_time DESC 
                LIMIT ?
            """, (limit,))
            rooms = self.cursor.fetchall()
            result = []
            for room in rooms:
                if len(room) >= 6:
                    result.append({
                        'id': room[0],
                        'owner_id': room[1],
                        'name': room[2] if room[2] else "Без названия",
                        'total_time': room[3] if room[3] is not None else 0,
                        'channel_id': room[4],
                        'is_hidden': room[5] if len(room) > 5 else 0
                    })
            return result
        except Exception as e:
            logger.error(f"Ошибка при получении топа комнат по времени: {e}")
            return []

    def get_top_rooms_by_activity(self, limit=5):
        """Получает топ N комнат по активности (сообщениям)"""
        try:
            self.cursor.execute("""
                SELECT id, owner_id, name, activity 
                FROM personal_rooms 
                ORDER BY activity DESC 
                LIMIT ?
            """, (limit,))
            rooms = self.cursor.fetchall()
            result = []
            for room in rooms:
                if len(room) >= 4:
                    result.append({
                        'id': room[0],
                        'owner_id': room[1],
                        'name': room[2] if room[2] else "Без названия",
                        'activity': room[3] if room[3] is not None else 0
                    })
            return result
        except Exception as e:
            logger.error(f"Ошибка при получении топа комнат по активности: {e}")
            return []

    # ============================================================
    # НОВЫЙ МЕТОД: Списание и обновление даты
    # ============================================================

    def deduct_balance_and_update_date(self, user_id: int, amount: int):
        """
        Списывает деньги с баланса пары и обновляет дату следующего списания
        Дата = текущая дата + 30 дней
        """
        try:
            # Списываем деньги
            self.cursor.execute("""
                UPDATE marrieges 
                SET balance = balance - ? 
                WHERE partner_1 = ? OR partner_2 = ?
            """, (amount, user_id, user_id))
            
            # Обновляем дату на текущую + 30 дней
            new_date = int((datetime.now() + timedelta(days=30)).timestamp())
            self.cursor.execute("""
                UPDATE marrieges 
                SET reg_marry = ? 
                WHERE partner_1 = ? OR partner_2 = ?
            """, (str(new_date), user_id, user_id))
            
            self.conn.commit()
            logger.info(f"Списано {amount} и обновлена дата списания для пользователя {user_id} на {datetime.fromtimestamp(new_date).strftime('%d.%m.%Y')}")
            return True
        except Exception as e:
            logger.error(f"Ошибка при списании и обновлении даты: {e}")
            return False

    # ============================================================
    # НОВЫЙ МЕТОД: Обновление даты регистрации брака
    # ============================================================

    def update_marry_date(self, partner_1_id: int, partner_2_id: int, new_timestamp: int):
        """
        Обновляет дату регистрации брака для пары
        Используется при списании средств за изменение названия любовной комнаты
        """
        try:
            # Обновляем reg_marry для пары
            self.cursor.execute("""
                UPDATE marrieges 
                SET reg_marry = ? 
                WHERE (partner_1 = ? AND partner_2 = ?) 
                   OR (partner_1 = ? AND partner_2 = ?)
            """, (str(new_timestamp), partner_1_id, partner_2_id, partner_2_id, partner_1_id))
            self.conn.commit()
            
            if self.cursor.rowcount > 0:
                logger.info(f"Обновлена дата брака для пары {partner_1_id} и {partner_2_id} на {new_timestamp}")
                return True
            else:
                logger.warning(f"Не найдена пара для обновления даты: {partner_1_id} и {partner_2_id}")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка при обновлении даты брака: {e}")
            return False

    # ============================================================
    # НОВЫЙ МЕТОД: Сброс баланса всех пользователей
    # ============================================================

    def reset_all_balances(self):
        """Сбрасывает баланс всех пользователей до 0 монет"""
        try:
            self.cursor.execute("UPDATE users SET money = 0")
            self.conn.commit()
            count = self.cursor.rowcount
            logger.info(f"Сброшен баланс у {count} пользователей")
            return count
        except Exception as e:
            logger.error(f"Ошибка при сбросе баланса всех пользователей: {e}")
            raise e

    def close(self):
        try:
            self.conn.close()
            self.conn_log.close()
            logger.info("Соединения с БД закрыты")
        except Exception as e:
            logger.error(f"Ошибка закрытия соединений: {e}")