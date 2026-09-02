import random
import discord
from discord import app_commands
from discord.ext import commands

from modules.Logger import *
from modules.Database import Database
from modules.Utils import Utils


guild_id_cmd = Utils.get_guild_id()

COIN = "<:coin:1515637898735652924>"
ACCENT = 0x2F3136
ERROR_ACCENT = discord.Color.red().value
SUCCESS_ACCENT = discord.Color.green().value

NO_MENTIONS = discord.AllowedMentions.none()

CASE_PRICE = 350
CASE_MIN = 75
CASE_MAX = 750


class V2Mixin:
    def build_view(self, title, description=None, *, footer=None, buttons=None, image_url=None):
        view = discord.ui.LayoutView(timeout=None)  # timeout=None для всех кнопок
        container = discord.ui.Container()
        
        container.add_item(discord.ui.TextDisplay(content=f"## {title}"))
        
        if description:
            container.add_item(discord.ui.TextDisplay(content=description))
        
        if footer:
            container.add_item(discord.ui.TextDisplay(content=f"-# {footer}"))
        
        if image_url:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(image_url)))
        
        if buttons:
            container.add_item(discord.ui.Separator())
            row = discord.ui.ActionRow()
            for button in buttons:
                row.add_item(button)
            container.add_item(row)
        
        view.add_item(container)
        return view

    def button(self, label=None, emoji=None, style=discord.ButtonStyle.secondary, url=None, custom_id=None, disabled=False):
        """Создание кнопки"""
        btn = discord.ui.Button(
            label=label,
            emoji=emoji,
            style=style,
            url=url,
            custom_id=custom_id,
            disabled=disabled
            # timeout убираем - Button не принимает этот параметр
        )
        return btn

    async def respond(self, interaction, view, *, ephemeral=False):
        if interaction.response.is_done():
            return await interaction.followup.send(
                view=view,
                ephemeral=ephemeral,
                allowed_mentions=NO_MENTIONS,
                wait=True,
            )
        
        return await interaction.response.send_message(
            view=view,
            ephemeral=ephemeral,
            allowed_mentions=NO_MENTIONS,
        )

    async def edit_original(self, interaction, view):
        return await interaction.edit_original_response(view=view, allowed_mentions=NO_MENTIONS)


class Cases(commands.Cog, V2Mixin):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database()
        # Словарь для отслеживания открытий, чтобы предотвратить двойные клики
        self.opening_cases = set()
        # Создаем таблицу для истории кейсов при инициализации
        self._create_case_history_table()

    def _create_case_history_table(self):
        """Создание таблицы для истории кейсов"""
        try:
            self.db.cursor.execute("""
                CREATE TABLE IF NOT EXISTS case_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    member_id INTEGER NOT NULL,
                    win_amount INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.db.conn.commit()
            logger.info("Таблица case_history создана/существует")
        except Exception as e:
            logger.error(f"Ошибка при создании таблицы case_history: {e}")

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("/case - система загружена")

    def cog_unload(self):
        close = getattr(self.db, "close", None)
        if close:
            close()

    # ============================================================
    # МЕТОДЫ РАБОТЫ С БАЗОЙ ДАННЫХ
    # ============================================================

    async def get_cases(self, user_id: int) -> int:
        """Получить количество кейсов у пользователя"""
        try:
            self.db.cursor.execute("SELECT cases FROM users WHERE member_id = ?", (user_id,))
            result = self.db.cursor.fetchone()
            return result[0] if result else 0
        except Exception as e:
            logger.error(f"Ошибка при получении кейсов: {e}")
            return 0

    async def update_cases(self, user_id: int, amount: int) -> bool:
        """Обновить количество кейсов"""
        try:
            self.db.cursor.execute("UPDATE users SET cases = cases + ? WHERE member_id = ?", (amount, user_id))
            self.db.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при обновлении кейсов: {e}")
            return False

    async def get_balance(self, user_id: int) -> int:
        """Получить баланс пользователя"""
        try:
            self.db.cursor.execute("SELECT money FROM users WHERE member_id = ?", (user_id,))
            result = self.db.cursor.fetchone()
            return result[0] if result else 0
        except Exception as e:
            logger.error(f"Ошибка при получении баланса: {e}")
            return 0

    async def update_balance(self, user_id: int, amount: int) -> bool:
        """Обновить баланс"""
        try:
            self.db.cursor.execute("UPDATE users SET money = money + ? WHERE member_id = ?", (amount, user_id))
            self.db.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при обновлении баланса: {e}")
            return False

    async def add_case_history(self, user_id: int, win_amount: int) -> bool:
        """Добавить запись об открытии кейса в историю"""
        try:
            self.db.cursor.execute(
                "INSERT INTO case_history (member_id, win_amount) VALUES (?, ?)",
                (user_id, win_amount)
            )
            self.db.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при записи в историю кейсов: {e}")
            return False

    async def get_case_history(self, user_id: int, limit: int = 10, offset: int = 0) -> list:
        """Получить историю открытий кейсов пользователя"""
        try:
            self.db.cursor.execute("""
                SELECT id, win_amount, created_at 
                FROM case_history 
                WHERE member_id = ?
                ORDER BY created_at DESC 
                LIMIT ? OFFSET ?
            """, (user_id, limit, offset))
            return self.db.cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка при получении истории кейсов: {e}")
            return []

    async def get_history_count(self, user_id: int) -> int:
        """Получить общее количество открытий кейсов пользователя"""
        try:
            self.db.cursor.execute("""
                SELECT COUNT(*) 
                FROM case_history 
                WHERE member_id = ?
            """, (user_id,))
            result = self.db.cursor.fetchone()
            return result[0] if result else 0
        except Exception as e:
            logger.error(f"Ошибка при подсчете истории: {e}")
            return 0

    def get_case_reward(self) -> int:
        """Генерация выигрыша с вероятностной системой"""
        roll = random.randint(0, 100)
        
        if roll < 40:
            return random.randint(75, 200)
        elif roll < 70:
            return random.randint(201, 400)
        elif roll < 90:
            return random.randint(401, 600)
        elif roll < 98:
            return random.randint(601, 700)
        else:
            return random.randint(701, 750)

    # ============================================================
    # ОСНОВНАЯ ЛОГИКА ОТКРЫТИЯ КЕЙСА
    # ============================================================

    async def open_case_logic(self, interaction: discord.Interaction, is_button: bool = False):
        """Общая логика открытия кейса"""
        user_id = interaction.user.id
        
        if user_id in self.opening_cases:
            view = self.build_view(
                "⏳ Подождите",
                "Вы уже открываете кейс! Подождите немного."
            )
            await self.respond(interaction, view, ephemeral=True)
            return
        
        self.opening_cases.add(user_id)
        
        try:
            cases_count = await self.get_cases(user_id)
            
            if cases_count < 1:
                view = self.build_view(
                    "Ошибка",
                    "У вас нет кейсов! Купите их командой /case-buy"
                )
                await self.respond(interaction, view, ephemeral=True)
                return
            
            await self.update_cases(user_id, -1)
            win_amount = self.get_case_reward()
            await self.update_balance(user_id, win_amount)
            await self.add_case_history(user_id, win_amount)
            
            self.db.write_new_transactions(
                interaction.user,
                "Открытие кейса",
                win_amount
            )
            
            new_cases = await self.get_cases(user_id)
            new_balance = await self.get_balance(user_id)
            
            buy_button = self.button(
                label="Купить кейс",
                style=discord.ButtonStyle.secondary
            )
            buy_button.callback = self.buy_button_callback
            
            open_button = self.button(
                label="Открыть кейс",
                style=discord.ButtonStyle.secondary,
                disabled=(new_cases < 1)
            )
            open_button.callback = self.open_button_callback
            
            view = self.build_view(
                "<:case:1518992953312411648> Кейс открыт!",
                f"{interaction.user.mention} открыл кейс и выиграл: {win_amount} {COIN}\n\n"
                f"Осталось кейсов: {new_cases}\n"
                f"Ваш баланс: {new_balance} {COIN}",
                buttons=[buy_button, open_button],
                footer=f"Цена 1 кейса: {CASE_PRICE} {COIN}"
            )
            
            await self.respond(interaction, view, ephemeral=False)
            logger.info(f"{interaction.user.name} открыл кейс и выиграл {win_amount} монет")
            
        finally:
            self.opening_cases.discard(user_id)

    # ============================================================
    # ОБРАБОТЧИКИ КНОПОК
    # ============================================================

    async def buy_button_callback(self, interaction: discord.Interaction):
        """Обработчик кнопки 'Купить кейс'"""
        total_price = CASE_PRICE
        balance = await self.get_balance(interaction.user.id)
        
        if balance < total_price:
            view = self.build_view(
                "Ошибка",
                f"Недостаточно средств!\n\n"
                f"Ваш баланс: {balance} {COIN}\n"
                f"Нужно: {total_price} {COIN}"
            )
            await self.respond(interaction, view, ephemeral=True)
            return
        
        await self.update_balance(interaction.user.id, -total_price)
        await self.update_cases(interaction.user.id, 1)
        
        self.db.write_new_transactions(
            interaction.user,
            "Покупка 1 кейса",
            -total_price
        )
        
        new_balance = balance - total_price
        new_cases = await self.get_cases(interaction.user.id)
        
        buy_button = self.button(
            label="Купить кейс",
            style=discord.ButtonStyle.secondary
        )
        buy_button.callback = self.buy_button_callback
        
        open_button = self.button(
            label="Открыть кейс",
            style=discord.ButtonStyle.secondary,
            disabled=(new_cases < 1)
        )
        open_button.callback = self.open_button_callback
        
        view = self.build_view(
            "<:case:1518992953312411648> Кейс куплен",
            f"Куплено: 1\n"
            f"Цена: {total_price} {COIN}\n\n"
            f"Ваш баланс: {new_balance} {COIN}\n"
            f"Кейсов теперь: {new_cases}",
            buttons=[buy_button, open_button],
            footer=f"Цена 1 кейса: {CASE_PRICE} {COIN}"
        )
        
        await self.edit_original(interaction, view)
        logger.info(f"{interaction.user.name} купил 1 кейс через кнопку")

    async def open_button_callback(self, interaction: discord.Interaction):
        """Обработчик кнопки 'Открыть кейс'"""
        await self.open_case_logic(interaction, is_button=True)

    # ============================================================
    # ОБРАБОТЧИК ИСТОРИИ
    # ============================================================

    async def history_navigation_callback(self, interaction: discord.Interaction, user_id: int, page: int, direction: str):
        """Обработчик навигации по истории"""
        target_user = interaction.guild.get_member(user_id) or await self.bot.fetch_user(user_id)
        
        total_records = await self.get_history_count(user_id)
        total_pages = max(1, (total_records + 9) // 10)
        
        if direction == "left" and page > 1:
            page -= 1
        elif direction == "right" and page < total_pages:
            page += 1
        else:
            await interaction.response.defer()
            return
        
        offset = (page - 1) * 10
        history = await self.get_case_history(user_id, 10, offset)
        
        view = await self.create_history_view(target_user, history, page, total_pages, user_id)
        await self.edit_original(interaction, view)

    async def delete_history_callback(self, interaction: discord.Interaction):
        """Обработчик кнопки удаления"""
        await interaction.message.delete()

    async def create_history_view(self, target_user, history, page: int, total_pages: int, user_id: int):
        """Создание view для истории"""
        if not history:
            description = "История открытий кейсов пуста."
        else:
            history_lines = []
            for i, (_, win_amount, created_at) in enumerate(history, 1):
                history_lines.append(f"`#{i + (page - 1) * 10}` +{win_amount} {COIN} — <t:{int(created_at.timestamp())}:R>")
            description = "\n".join(history_lines)
        
        buttons = []
        
        left_btn = self.button(
            emoji="<:left:1515638771071324250>",
            style=discord.ButtonStyle.secondary
        )
        left_btn.callback = lambda i: self.history_navigation_callback(i, user_id, page, "left")
        if page <= 1:
            left_btn.disabled = True
        buttons.append(left_btn)
        
        delete_btn = self.button(
            emoji="<:del:1515639124256751676>",
            style=discord.ButtonStyle.secondary
        )
        delete_btn.callback = self.delete_history_callback
        buttons.append(delete_btn)
        
        right_btn = self.button(
            emoji="<:right:1515638675931795626>",
            style=discord.ButtonStyle.secondary
        )
        right_btn.callback = lambda i: self.history_navigation_callback(i, user_id, page, "right")
        if page >= total_pages:
            right_btn.disabled = True
        buttons.append(right_btn)
        
        title = f"<:fire:1519313816486285363> История кейсов - {target_user.display_name}"
        
        return self.build_view(
            title,
            description,
            footer=f"Страница {page} из {total_pages} | Всего открытий: {await self.get_history_count(user_id)}",
            buttons=buttons
        )

    # ============================================================
    # АДМИН-КОМАНДЫ (СООБЩЕНИЯ ДЛЯ ВСЕХ)
    # ============================================================

    @app_commands.command(name="case-give", description="Выдать кейсы пользователю (Админ)")
    @app_commands.describe(
        пользователь="Выберите пользователя",
        количество="Количество кейсов"
    )
    @app_commands.guilds(discord.Object(id=guild_id_cmd))
    @app_commands.default_permissions(administrator=True)
    async def case_give(
        self,
        interaction: discord.Interaction,
        пользователь: discord.Member,
        количество: app_commands.Range[int, 1, 1000]
    ):
        await self.update_cases(пользователь.id, количество)
        
        # Сообщение для всех в канале
        view = self.build_view(
            "<:case:1518992953312411648> Кейсы выданы",
            f"**Администратор** {interaction.user.mention} выдал **{количество}** кейсов пользователю {пользователь.mention}",
            footer=f"Текущее количество кейсов у {пользователь.display_name}: {await self.get_cases(пользователь.id)}"
        )
        
        await self.respond(interaction, view, ephemeral=False)  # ephemeral=False - видно всем
        logger.info(f"{interaction.user.name} выдал {количество} кейсов {пользователь.name}")

    @app_commands.command(name="case-remove", description="Забрать кейсы у пользователя (Админ)")
    @app_commands.describe(
        пользователь="Выберите пользователя",
        количество="Количество кейсов"
    )
    @app_commands.guilds(discord.Object(id=guild_id_cmd))
    @app_commands.default_permissions(administrator=True)
    async def case_remove(
        self,
        interaction: discord.Interaction,
        пользователь: discord.Member,
        количество: app_commands.Range[int, 1, 1000]
    ):
        current_cases = await self.get_cases(пользователь.id)
        
        if current_cases < количество:
            view = self.build_view(
                "Ошибка",
                f"У пользователя {пользователь.mention} всего **{current_cases}** кейсов!\n"
                f"Запрошено к снятию: **{количество}**"
            )
            return await self.respond(interaction, view, ephemeral=True)
        
        await self.update_cases(пользователь.id, -количество)
        
        # Сообщение для всех в канале
        view = self.build_view(
            "<:case:1518992953312411648> Кейсы сняты",
            f"**Администратор** {interaction.user.mention} снял **{количество}** кейсов у пользователя {пользователь.mention}",
            footer=f"Текущее количество кейсов у {пользователь.display_name}: {await self.get_cases(пользователь.id)}"
        )
        
        await self.respond(interaction, view, ephemeral=False)  # ephemeral=False - видно всем
        logger.info(f"{interaction.user.name} снял {количество} кейсов у {пользователь.name}")

    # ============================================================
    # КОМАНДЫ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ
    # ============================================================

    @app_commands.command(name="cases", description="Просмотр количества кейсов")
    @app_commands.describe(
        пользователь="Выберите пользователя для просмотра"
    )
    @app_commands.guilds(discord.Object(id=guild_id_cmd))
    async def cases(
        self,
        interaction: discord.Interaction,
        пользователь: discord.Member = None
    ):
        target_user = пользователь or interaction.user
        cases_count = await self.get_cases(target_user.id)
        
        history_button = self.button(
            label="История",
            style=discord.ButtonStyle.secondary
        )
        history_button.callback = lambda i: self.history_button_callback(i, target_user.id)
        
        view = self.build_view(
            f"<:case:1518992953312411648> Кейсы - {target_user.display_name}",
            f"Количество кейсов: {cases_count}",
            buttons=[history_button]
        )
        
        await self.respond(interaction, view, ephemeral=False)

    async def history_button_callback(self, interaction: discord.Interaction, user_id: int):
        """Обработчик кнопки 'История'"""
        target_user = interaction.guild.get_member(user_id) or await self.bot.fetch_user(user_id)
        
        total_records = await self.get_history_count(user_id)
        total_pages = max(1, (total_records + 9) // 10)
        page = 1
        
        history = await self.get_case_history(user_id, 10, 0)
        view = await self.create_history_view(target_user, history, page, total_pages, user_id)
        
        await self.respond(interaction, view, ephemeral=False)

    @app_commands.command(name="case-buy", description="Купить кейсы")
    @app_commands.describe(
        количество="Количество кейсов для покупки"
    )
    @app_commands.guilds(discord.Object(id=guild_id_cmd))
    async def case_buy(
        self,
        interaction: discord.Interaction,
        количество: app_commands.Range[int, 1, 100]
    ):
        total_price = количество * CASE_PRICE
        balance = await self.get_balance(interaction.user.id)
        
        if balance < total_price:
            view = self.build_view(
                "Ошибка",
                f"Недостаточно средств!\n\n"
                f"Ваш баланс: {balance} {COIN}\n"
                f"Нужно: {total_price} {COIN}"
            )
            return await self.respond(interaction, view, ephemeral=True)
        
        await self.update_balance(interaction.user.id, -total_price)
        await self.update_cases(interaction.user.id, количество)
        
        self.db.write_new_transactions(
            interaction.user,
            f"Покупка {количество} кейсов",
            -total_price
        )
        
        new_balance = balance - total_price
        new_cases = await self.get_cases(interaction.user.id)
        
        buy_button = self.button(
            label="Купить кейс",
            style=discord.ButtonStyle.secondary
        )
        buy_button.callback = self.buy_button_callback
        
        open_button = self.button(
            label="Открыть кейс",
            style=discord.ButtonStyle.secondary,
            disabled=(new_cases < 1)
        )
        open_button.callback = self.open_button_callback
        
        view = self.build_view(
            "<:case:1518992953312411648> Кейсы куплены",
            f"Куплено: {количество}\n"
            f"Цена: {total_price} {COIN}\n\n"
            f"Ваш баланс: {new_balance} {COIN}\n"
            f"Кейсов теперь: {new_cases}",
            buttons=[buy_button, open_button],
            footer=f"Цена 1 кейса: {CASE_PRICE} {COIN}"
        )
        
        await self.respond(interaction, view, ephemeral=False)
        logger.info(f"{interaction.user.name} купил {количество} кейсов")

    @app_commands.command(name="case-open", description="Открыть кейс")
    @app_commands.guilds(discord.Object(id=guild_id_cmd))
    async def case_open(
        self,
        interaction: discord.Interaction
    ):
        await self.open_case_logic(interaction, is_button=False)

    @app_commands.command(name="case-history", description="Просмотр истории открытий кейсов")
    @app_commands.describe(
        пользователь="Выберите пользователя для просмотра истории"
    )
    @app_commands.guilds(discord.Object(id=guild_id_cmd))
    async def case_history(
        self,
        interaction: discord.Interaction,
        пользователь: discord.Member = None
    ):
        target_user = пользователь or interaction.user
        
        total_records = await self.get_history_count(target_user.id)
        total_pages = max(1, (total_records + 9) // 10)
        page = 1
        
        history = await self.get_case_history(target_user.id, 10, 0)
        view = await self.create_history_view(target_user, history, page, total_pages, target_user.id)
        
        await self.respond(interaction, view, ephemeral=False)


# ============================================================
# SETUP
# ============================================================
async def setup(bot: commands.Bot):
    """Функция для загрузки кога"""
    await bot.add_cog(Cases(bot))