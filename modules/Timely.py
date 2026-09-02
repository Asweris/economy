import inspect
import random
from datetime import datetime, timedelta

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

TIMELY_IMAGE_URL = "https://cdn.discordapp.com/attachments/992883178362642453/1029462389130792970/-1.png"


async def maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def clamp_text(value, limit=3800):
    value = "" if value is None else str(value)
    return value if len(value) <= limit else value[: limit - 3] + "..."


class V2Mixin:
    def build_view(self, title, description=None, *, footer=None, rows=None, image_url=None, thumbnail_url=None):
        view = discord.ui.LayoutView(timeout=120)
        container = discord.ui.Container()

        content = f"## {title}"
        if description:
            content += f"\n\n{description}"
        if footer:
            content += f"\n\n-# {footer}"

        # Добавляем аватарку как Thumbnail в правом верхнем углу
        if thumbnail_url:
            container.add_item(
                discord.ui.Section(
                    discord.ui.TextDisplay(content=clamp_text(content)),
                    accessory=discord.ui.Thumbnail(thumbnail_url),
                )
            )
        else:
            container.add_item(discord.ui.TextDisplay(content=clamp_text(content)))

        if image_url:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(image_url)))

        if rows:
            container.add_item(discord.ui.Separator())

            for row_items in rows:
                container.add_item(row_items)

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

    async def edit_original(self, interaction, view):
        return await interaction.edit_original_response(view=view)


class Timely(commands.Cog, V2Mixin):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database()

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("/timely - start")

    def cog_unload(self):
        close = getattr(self.db, "close", None)
        if close:
            close()

    def get_discord_timestamp(self, dt: datetime) -> str:
        """Возвращает временную метку Discord в относительном формате"""
        return f"<t:{int(dt.timestamp())}:R>"

    @app_commands.command(name="timely", description="Временная награда.")
    @app_commands.guilds(discord.Object(id=guild_id_cmd))
    async def timely(self, interaction: discord.Interaction):
        need_timestamp = int(await maybe_await(self.db.get_daily_award(interaction.user.id)) or 0)
        need_time = datetime.fromtimestamp(need_timestamp) if need_timestamp > 0 else datetime.fromtimestamp(0)
        current_time = datetime.now()

        # Получаем URL аватарки пользователя
        user_avatar_url = str(interaction.user.display_avatar.url)

        if need_timestamp != 0 and current_time < need_time:
            next_time_ts = self.get_discord_timestamp(need_time)

            return await self.respond(
                interaction,
                self.build_view(
                    "Ежедневная награда",
                    "**Вы уже забрали свои монеты.**\n\n"
                    f"Следующая награда будет доступна {next_time_ts}.",
                    footer="Возвращайтесь позже, чтобы забрать новую награду.",
                    image_url=TIMELY_IMAGE_URL,
                    thumbnail_url=user_avatar_url,  # Аватарка в правом верхнем углу
                ),
                ephemeral=True,
            )

        money = random.randint(50, 100)
        next_time = current_time + timedelta(hours=12)
        next_time_ts = self.get_discord_timestamp(next_time)

        await maybe_await(self.db.give_money(interaction.user.id, money))
        await maybe_await(self.db.write_new_transactions(interaction.user, "Временная награда", money))
        await maybe_await(self.db.update_daily_award(interaction.user.id, int(datetime.timestamp(next_time))))

        logger.info(f"{interaction.user.name} получил ежедневную награду: {money} валюты")

        await self.respond(
            interaction,
            self.build_view(
                "Ежедневная награда",
                f"**Вы успешно получили награду.**\n\n"
                f"**Пользователь:** {interaction.user.mention}\n"
                f"**Получено:** **{money}** {COIN}\n\n"
                f"Следующая награда будет доступна {next_time_ts}.",
                image_url=TIMELY_IMAGE_URL,
                thumbnail_url=user_avatar_url,  # Аватарка в правом верхнем углу
            ),
        )


# ============================================================
# SETUP
# ============================================================
async def setup(bot: commands.Bot):
    """Функция для загрузки кога"""
    await bot.add_cog(Timely(bot))