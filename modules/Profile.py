from easy_pil import Editor, Canvas, Font, load_image_async
from PIL import ImageDraw, ImageFilter, Image, ImageEnhance

import discord
import sqlite3
import random
import os
import sys
import time

from discord.ext import commands, tasks
from discord import File, app_commands

# Добавляем путь для импорта modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.Database import Database
from modules.Logger import logger

# =====================================================
# CONFIG
# =====================================================

guild_id_cmd = 1439176098632957955

# =====================================================
# FONTS
# =====================================================

font_30 = Font("assets/font.ttf", size=30)
font_35 = Font("assets/font.ttf", size=35)
font_40 = Font("assets/font.ttf", size=40)
font_45 = Font("assets/font.ttf", size=45)
font_50 = Font("assets/font.ttf", size=50)
font_55 = Font("assets/font.ttf", size=55)
font_60 = Font("assets/font.ttf", size=60)
font_70 = Font("assets/font.ttf", size=70)

font_bighaustitul_35 = Font("assets/font_bighaustitul.ttf", size=35)
font_bighaustitul_40 = Font("assets/font_bighaustitul.ttf", size=40)
font_bighaustitul_45 = Font("assets/font_bighaustitul.ttf", size=45)
font_bighaustitul_45_stats = Font("assets/font_bighaustitul.ttf", size=45)
font_bighaustitul_50 = Font("assets/font_bighaustitul.ttf", size=50)
font_bighaustitul_60 = Font("assets/font_bighaustitul.ttf", size=60)
font_bighaustitul_70 = Font("assets/font_bighaustitul.ttf", size=70)
font_bighaustitul_120 = Font("assets/font_bighaustitul.ttf", size=120)
font_bighaustitul_200 = Font("assets/font_bighaustitul.ttf", size=200)


def clamp_text(value, limit=3800):
    value = "" if value is None else str(value)
    return value if len(value) <= limit else value[: limit - 3] + "..."


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

        # Убрали self.voice_states и self.voice_xp_task.start(),
        # так как голосовой онлайн теперь считается только в Tracker.
        # Оставляем только задачу для XP за голос.
        self.voice_xp_task.start()

    def cog_unload(self):
        self.voice_xp_task.cancel()
        self.profile_db.close()
        try:
            self.main_db.conn.close()
            self.main_db.conn_log.close()
        except Exception:
            pass

    # УДАЛЁН старый обработчик on_voice_state_update!
    # Теперь всё время считает Tracker, а Profile только выдаёт XP за нахождение в войсе.

    # =====================================================
    # MESSAGE XP И СООБЩЕНИЯ
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
    # VOICE XP (фоновая задача)
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

        container.add_item(discord.ui.TextDisplay(content=clamp_text(content)))

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

    def button(self, label=None, *, emoji=None, callback=None, custom_id=None):
        button = discord.ui.Button(
            label=label,
            emoji=emoji,
            custom_id=custom_id,
            style=discord.ButtonStyle.secondary,
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
                    content=clamp_text(f"## Профиль — {self.profile_owner.display_name}")
                )
            )
            container.add_item(discord.ui.Separator())
            container.add_item(
                discord.ui.MediaGallery(
                    discord.MediaGalleryItem("attachment://profile.png")
                )
            )
            container.add_item(discord.ui.Separator())

            row = discord.ui.ActionRow()
            row.add_item(like_button)
            row.add_item(edit_button)
            container.add_item(row)
            self.add_item(container)

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

        profile = await self.generate_profile(member)
        view = self.ProfileView(self, member, message)

        edit_attempts = (
            lambda: {"attachments": [self._profile_file(profile)], "view": view},
            lambda: {"attachments": [], "files": [self._profile_file(profile)], "view": view},
            lambda: {"attachments": [], "file": self._profile_file(profile), "view": view},
            lambda: {"view": view},
        )

        last_error = None
        for build_kwargs in edit_attempts:
            try:
                await message.edit(**build_kwargs())
                return
            except TypeError as error:
                last_error = error

        if last_error:
            raise last_error

    # =====================================================
    # GENERATE PROFILE
    # =====================================================

    async def generate_profile(self, member):

        print(f"\n[PROFILE] Генерация профиля для {member.name} ({member.id})")
        
        canvas = Canvas((2167, 1065))
        editor = Editor(canvas)

        background = Editor("assets/profile/themes/theme_default.png")
        editor.paste(background.image, (0, 0))

        profile_data = self.profile_db.get_profile(member.id)
        
        if profile_data:
            reputation, status, xp, level = profile_data
        else:
            reputation, status, xp, level = 0, "", 0, 0

        current_xp = xp % 500
        progress = current_xp / 500

        messages = self.main_db.get_message_count(member)
        
        voice_data = self.main_db.get_data(member)
        if voice_data:
            voice_hours = voice_data[2] if voice_data[2] else 0
        else:
            voice_hours = 0

        message_rank = None
        top_messages = self.main_db.get_top_users_messages()
        for idx, (uid, _) in enumerate(top_messages, 1):
            if uid == member.id:
                message_rank = idx
                break

        print(f"  📝 Сообщения: {messages}")
        print(f"  🎤 Голосовое время: {voice_hours} ч.")
        print(f"  🏆 Место в топе сообщений: {message_rank}")
        print(f"  ⭐ Репутация: {reputation}")
        print(f"  📊 Уровень: {level}, XP: {xp}\n")

        # =====================================================
        # АВАТАР
        # =====================================================

        avatar = await load_image_async(str(member.display_avatar.url))
        avatar = Editor(avatar).resize((335, 335)).circle_image()
        editor.paste(avatar.image, (916, 80))

        # =====================================================
        # USERNAME
        # =====================================================

        username = member.display_name
        username_x = 1083
        
        if len(username) > 18:
            username = username[:25] + "..."
            username_x = 1100
        elif len(username) > 12:
            username_x = 1090

        editor.text(
            (username_x, 440),
            username,
            color="#5e7289",
            font=font_70,
            align="center"
        )

        # =====================================================
        # STATUS
        # =====================================================

        if not status:
            status = "Нет статуса"

        status_x = 1083
        
        if len(status) > 28:
            status = status[:35] + "..."
            status_x = 1110
        elif len(status) > 20:
            status_x = 1095

        editor.text(
            (status_x, 515),
            status,
            color="#5e7289",
            font=font_bighaustitul_50,
            align="center"
        )

        # =====================================================
        # VOICE TIME
        # =====================================================

        voice_text = f"{voice_hours} ч." if voice_hours > 0 else "0 ч."

        editor.text(
            (400, 400),
            voice_text,
            color="#bdbec1",
            font=font_bighaustitul_45_stats,
            align="left"
        )

        # =====================================================
        # MESSAGES
        # =====================================================

        editor.text(
            (495, 586),
            str(messages),
            color="#bdbec1",
            font=font_bighaustitul_45_stats,
            align="left"
        )

        # =====================================================
        # REPUTATION
        # =====================================================

        editor.text(
            (1930, 394),
            str(reputation),
            color="#bdbec1",
            font=font_bighaustitul_45_stats,
            align="left"
        )

        # =====================================================
        # TOP (место в топе по сообщениям)
        # =====================================================

        top_text = str(message_rank) if message_rank else "0"

        editor.text(
            (1790, 586),
            top_text,
            color="#bdbec1",
            font=font_bighaustitul_45_stats,
            align="left"
        )

        # =====================================================
        # LEVEL
        # =====================================================

        level_text = str(level)
        level_center_x = 1083
        level_center_y = 840

        temp_img = Image.new('RGBA', (1, 1), (0, 0, 0, 0))
        temp_draw = ImageDraw.Draw(temp_img)
        bbox = temp_draw.textbbox((0, 0), level_text, font=font_bighaustitul_200.font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        shadow_img = Image.new('RGBA', (text_width + 80, text_height + 80), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_img)
        
        shadow_draw.text(
            (40 - bbox[0], 40 - bbox[1]),
            level_text,
            font=font_bighaustitul_200.font,
            fill=(94, 114, 137, 255)
        )
        
        pixels = shadow_img.load()
        height = shadow_img.size[1]
        
        for y in range(height):
            alpha = int(30 + (1 - y / height) * 170)
            alpha = min(220, max(30, alpha))
            for x in range(shadow_img.size[0]):
                r, g, b, a = pixels[x, y]
                if a > 0:
                    pixels[x, y] = (r, g, b, alpha)
        
        editor.image.paste(
            shadow_img,
            (level_center_x - (text_width + 80) // 2, level_center_y - (text_height + 80) // 2),
            shadow_img
        )

        editor.text(
            (level_center_x, level_center_y),
            level_text,
            color="#5e7289",
            font=font_bighaustitul_120,
            align="center"
        )

        # =====================================================
        # XP BAR
        # =====================================================

        draw = ImageDraw.Draw(editor.image)

        bar_x = 580
        bar_y = 970

        bar_width = 1000
        bar_height = 8

        filled_width = int(bar_width * progress)

        draw.rounded_rectangle(
            (bar_x, bar_y, bar_x + bar_width, bar_y + bar_height),
            radius=6,
            fill=(64, 72, 85, 255)
        )

        if filled_width > 0:
            glow_size = 4
            glow_image = Image.new('RGBA', (filled_width + glow_size * 2, bar_height + glow_size * 2), (0, 0, 0, 0))
            glow_draw = ImageDraw.Draw(glow_image)
            
            glow_draw.rounded_rectangle(
                (glow_size, glow_size, glow_size + filled_width, glow_size + bar_height),
                radius=6,
                fill=(140, 155, 172, 80)
            )
            
            glow_blur = glow_image.filter(ImageFilter.GaussianBlur(radius=3))
            
            editor.image.paste(
                glow_blur,
                (bar_x - glow_size, bar_y - glow_size),
                glow_blur
            )

        draw.rounded_rectangle(
            (bar_x, bar_y, bar_x + filled_width, bar_y + bar_height),
            radius=6,
            fill=(140, 155, 172, 255)
        )

        return editor

    def _profile_file(self, profile):
        return File(fp=profile.image_bytes, filename="profile.png")

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
        await interaction.response.defer()

        user = пользователь if пользователь else interaction.user

        profile = await self.generate_profile(user)
        file = self._profile_file(profile)
        view = self.ProfileView(self, user)

        message = await interaction.followup.send(
            file=file,
            view=view,
            wait=True,
        )
        view.original_interaction = message


# =====================================================
# SETUP
# =====================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(Profile(bot))