import discord
import sqlite3
import random
import os
import sys

from discord.ext import commands, tasks
from discord import app_commands

# Добавляем путь для импорта modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.Database import Database
from modules.Logger import logger

# =====================================================
# CONFIG
# =====================================================

guild_id_cmd = 1439176098632957955

# =====================================================
# ЛОКАЛЬНАЯ БД ДЛЯ ПРОФИЛЯ (репутация, статус, уровень)
# =====================================================

class ProfileDatabase:

    def __init__(self):
        self.connection = sqlite3.connect("main.db")
        self.cursor = self.connection.cursor()
        self.create_tables()

    def create_tables(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_profile (
                user_id INTEGER PRIMARY KEY,
                reputation INTEGER DEFAULT 0,
                status TEXT DEFAULT '',
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 0
            )
        """)

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS profile_likes (
                user_id INTEGER,
                liked_by INTEGER,
                UNIQUE(user_id, liked_by)
            )
        """)

        self.connection.commit()

    def create_user(self, user_id):
        self.cursor.execute(
            "INSERT OR IGNORE INTO user_profile (user_id) VALUES (?)",
            (user_id,)
        )
        self.connection.commit()

    def get_profile(self, user_id):
        self.create_user(user_id)
        self.cursor.execute(
            "SELECT reputation, status, xp, level FROM user_profile WHERE user_id = ?",
            (user_id,)
        )
        return self.cursor.fetchone()

    def set_status(self, user_id, status):
        self.create_user(user_id)
        self.cursor.execute(
            "UPDATE user_profile SET status = ? WHERE user_id = ?",
            (status, user_id)
        )
        self.connection.commit()

    def add_xp(self, user_id, amount):
        self.create_user(user_id)
        self.cursor.execute("SELECT xp FROM user_profile WHERE user_id = ?", (user_id,))
        current_xp = self.cursor.fetchone()[0]
        new_xp = current_xp + amount
        level = new_xp // 500
        self.cursor.execute(
            "UPDATE user_profile SET xp = ?, level = ? WHERE user_id = ?",
            (new_xp, level, user_id)
        )
        self.connection.commit()

    def has_liked(self, user_id, liked_by):
        self.cursor.execute(
            "SELECT * FROM profile_likes WHERE user_id = ? AND liked_by = ?",
            (user_id, liked_by)
        )
        return self.cursor.fetchone()

    def add_like(self, user_id, liked_by):
        self.create_user(user_id)
        if self.has_liked(user_id, liked_by):
            return False
        self.cursor.execute(
            "INSERT INTO profile_likes (user_id, liked_by) VALUES (?, ?)",
            (user_id, liked_by)
        )
        self.cursor.execute(
            "UPDATE user_profile SET reputation = reputation + 1 WHERE user_id = ?",
            (user_id,)
        )
        self.connection.commit()
        return True

    def close(self):
        self.connection.close()

# =====================================================
# PROFILE COG
# =====================================================

class Profile(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.profile_db = ProfileDatabase()
        self.main_db = Database()
        self.voice_xp_task.start()

    def cog_unload(self):
        self.voice_xp_task.cancel()
        self.profile_db.close()
        try:
            self.main_db.conn.close()
            self.main_db.conn_log.close()
        except Exception:
            pass

    # =====================================================
    # MESSAGE XP
    # =====================================================

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        xp = random.randint(1, 5)
        self.profile_db.add_xp(message.author.id, xp)
        self.main_db.log_write_new_user(message.author)
        self.main_db.save_message_count({message.author.id: 1})

    # =====================================================
    # VOICE XP
    # =====================================================

    @tasks.loop(minutes=5)
    async def voice_xp_task(self):
        for guild in self.bot.guilds:
            for member in guild.members:
                if member.voice and member.voice.channel and not member.bot:
                    xp = random.randint(1, 5)
                    self.profile_db.add_xp(member.id, xp)

    @voice_xp_task.before_loop
    async def before_voice_xp_task(self):
        await self.bot.wait_until_ready()

    # =====================================================
    # BUILD VIEW
    # =====================================================

    def build_view(self, title, description=None, *, rows=None, timeout=120):
        view = discord.ui.LayoutView(timeout=timeout)
        container = discord.ui.Container()

        content = f"## {title}"
        if description:
            content += f"\n\n{description}"

        container.add_item(discord.ui.TextDisplay(content=content))

        if rows:
            container.add_item(discord.ui.Separator())

            for row_items in rows:
                row = discord.ui.ActionRow()
                for item in row_items:
                    row.add_item(item)
                container.add_item(row)

        view.add_item(container)
        return view

    def row(self, *items):
        row = discord.ui.ActionRow()
        for item in items:
            row.add_item(item)
        return row

    def button(self, label=None, *, emoji=None, callback=None, custom_id=None, style=discord.ButtonStyle.secondary):
        button = discord.ui.Button(
            label=label,
            emoji=emoji,
            custom_id=custom_id,
            style=style,
        )
        if callback is not None:
            button.callback = callback
        return button

    async def respond(self, interaction, view, *, ephemeral=False):
        if interaction.response.is_done():
            return await interaction.followup.send(view=view, ephemeral=ephemeral, wait=True)
        return await interaction.response.send_message(view=view, ephemeral=ephemeral)

    async def send_notice(self, interaction, title, description, *, ephemeral=True):
        view = self.build_view(title, description, timeout=60)
        if interaction.response.is_done():
            await interaction.followup.send(view=view, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(view=view, ephemeral=ephemeral)

    # =====================================================
    # STATUS MODAL
    # =====================================================

    class StatusModal(discord.ui.Modal, title="Изменить профиль"):

        def __init__(self, cog, user_id, original_interaction):
            super().__init__()
            self.cog = cog
            self.user_id = user_id
            self.original_interaction = original_interaction
            self.add_item(
                discord.ui.TextInput(
                    label="Введите статус",
                    placeholder="Мой статус...",
                    max_length=32
                )
            )

        async def on_submit(self, interaction: discord.Interaction):
            status = self.children[0].value
            self.cog.profile_db.set_status(self.user_id, status)
            await self.cog.update_profile_message(self.original_interaction, self.user_id)
            await self.cog.send_notice(interaction, "Профиль", "Статус успешно изменён.")

    # =====================================================
    # PROFILE VIEW
    # =====================================================

    class ProfileView(discord.ui.LayoutView):

        def __init__(self, cog, profile_owner, original_interaction=None):
            super().__init__(timeout=None)
            self.cog = cog
            self.profile_owner = profile_owner
            self.original_interaction = original_interaction
            self._build()

        def _build(self):
            like_button = discord.ui.Button(
                label="Поставить лайк",
                style=discord.ButtonStyle.secondary,
                custom_id=f"profile_like:{self.profile_owner.id}",
            )
            like_button.callback = self.like_button

            edit_button = discord.ui.Button(
                label="Изменить профиль",
                style=discord.ButtonStyle.secondary,
                custom_id=f"profile_edit:{self.profile_owner.id}",
            )
            edit_button.callback = self.edit_profile

            container = discord.ui.Container()
            container.add_item(
                discord.ui.TextDisplay(
                    content=f"## Профиль - {self.profile_owner.display_name}"
                )
            )
            container.add_item(discord.ui.Separator())
            
            # Получаем данные профиля
            profile_data = self.cog.profile_db.get_profile(self.profile_owner.id)
            if profile_data:
                reputation, status, xp, level = profile_data
            else:
                reputation, status, xp, level = 0, "", 0, 0
            
            current_xp = xp % 500
            progress = (current_xp / 500) * 100
            
            messages = self.cog.main_db.get_message_count(self.profile_owner)
            
            voice_data = self.cog.main_db.get_data(self.profile_owner)
            if voice_data:
                voice_hours = voice_data[2] if voice_data[2] else 0
            else:
                voice_hours = 0
            
            # Создаем текстовый профиль
            profile_text = f"""**Статус:** {status if status else 'Нет статуса'}

**Статистика:**
• Уровень: {level}
• Опыт: {xp} XP ({progress:.1f}% до следующего уровня)
• Репутация: {reputation}
• Сообщений: {messages}
• Голосовых часов: {voice_hours} ч.

**Прогресс уровня:**
{self._create_progress_bar(progress)}"""
            
            container.add_item(discord.ui.TextDisplay(content=profile_text))
            container.add_item(discord.ui.Separator())

            row = discord.ui.ActionRow()
            row.add_item(like_button)
            row.add_item(edit_button)
            container.add_item(row)
            self.add_item(container)
        
        def _create_progress_bar(self, progress, length=20):
            """Создает текстовую полосу прогресса"""
            filled = int((progress / 100) * length)
            empty = length - filled
            return f"[{'█' * filled}{'░' * empty}] {progress:.1f}%"

        async def like_button(self, interaction: discord.Interaction):
            if interaction.user.id == self.profile_owner.id:
                return await self.cog.send_notice(
                    interaction,
                    "Профиль",
                    "Нельзя лайкнуть самого себя.",
                )

            liked = self.cog.profile_db.add_like(self.profile_owner.id, interaction.user.id)

            if not liked:
                return await self.cog.send_notice(
                    interaction,
                    "Профиль",
                    "Вы уже лайкали этот профиль.",
                )

            await interaction.response.defer(ephemeral=True)
            await self.cog.update_profile_message(interaction.message, self.profile_owner.id)
            await self.cog.send_notice(interaction, "Профиль", "Лайк успешно поставлен.")

        async def edit_profile(self, interaction: discord.Interaction):
            if interaction.user.id != self.profile_owner.id:
                return await self.cog.send_notice(
                    interaction,
                    "Профиль",
                    "Это не ваш профиль.",
                )

            modal = Profile.StatusModal(self.cog, interaction.user.id, interaction.message)
            await interaction.response.send_modal(modal)

    # =====================================================
    # UPDATE PROFILE MESSAGE
    # =====================================================

    async def update_profile_message(self, message, user_id):
        guild = getattr(message, "guild", None) or self.bot.get_guild(guild_id_cmd)
        if guild is None:
            raise RuntimeError("Не удалось найти guild для обновления профиля")

        member = guild.get_member(user_id)
        if not member:
            member = await guild.fetch_member(user_id)

        view = self.ProfileView(self, member, message)

        await message.edit(view=view)

    # =====================================================
    # PROFILE COMMAND
    # =====================================================

    @app_commands.command(name="profile", description="Профиль пользователя")
    @app_commands.describe(пользователь="Выберите пользователя")
    @app_commands.guilds(discord.Object(id=guild_id_cmd))
    async def profile(
        self,
        interaction: discord.Interaction,
        пользователь: discord.Member | None = None
    ):
        user = пользователь if пользователь else interaction.user
        
        view = self.ProfileView(self, user)
        
        # Проверяем, есть ли уже ответ
        if interaction.response.is_done():
            await interaction.followup.send(view=view, wait=True)
        else:
            await interaction.response.send_message(view=view)

# =====================================================
# SETUP
# =====================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(Profile(bot))
