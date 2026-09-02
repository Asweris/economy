import inspect
import math
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from modules.Database import Database
from modules.Logger import *
from modules.Utils import Utils


guild_id_cmd = Utils.get_guild_id()
ACCENT = 0x2F3136
MONTHS = ["янв.", "фев.", "мар.", "апр.", "май", "июн.", "июл.", "авг.", "сен.", "окт.", "ноя.", "дек."]
NO_MENTIONS = discord.AllowedMentions.none()


async def maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def clamp_text(value, limit=3800):
    value = "" if value is None else str(value)
    return value if len(value) <= limit else value[: limit - 3] + "..."


class Marries(commands.Cog):
    marries = app_commands.Group(
        name="marries",
        description="Команды для управления браками",
        guild_ids=[guild_id_cmd],
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database()

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("/marries history - start")

    def build_view(self, title, description=None, *, footer=None, rows=None, thumbnail_url=None, timeout=None):
        view = discord.ui.LayoutView(timeout=timeout)
        container = discord.ui.Container()

        content = f"## {title}"
        if description:
            content += f"\n\n{description}"
        if footer:
            content += f"\n\n-# {footer}"

        if thumbnail_url:
            container.add_item(
                discord.ui.Section(
                    discord.ui.TextDisplay(content=clamp_text(content)),
                    accessory=discord.ui.Thumbnail(thumbnail_url),
                )
            )
        else:
            container.add_item(discord.ui.TextDisplay(content=clamp_text(content)))

        if rows:
            container.add_item(discord.ui.Separator())

            for row in rows:
                container.add_item(row)

        view.add_item(container)
        return view

    def row(self, *items):
        row = discord.ui.ActionRow()
        for item in items:
            row.add_item(item)
        return row

    def button(self, *, emoji=None, custom_id=None, callback=None, disabled=False):
        button = discord.ui.Button(
            emoji=emoji,
            custom_id=custom_id,
            style=discord.ButtonStyle.secondary,
            disabled=disabled,
        )
        if callback is not None:
            button.callback = callback
        return button

    async def get_user(self, user_id: int) -> str:
        user = self.bot.get_user(int(user_id))
        if user is None:
            return f"Пользователь {user_id}"
        return user.mention

    async def make_page_history_view(
        self,
        page: int,
        total_pages: int,
        history: list,
        *,
        title: str = "История браков",
        rows=None,
        thumbnail_url=None,
    ):
        page_users = history[(page - 1) * 5:page * 5]
        lines = []

        for partner_1, partner_2, event_type, event_time in page_users:
            date = datetime.fromtimestamp(event_time)
            username_1 = await self.get_user(partner_1)
            username_2 = await self.get_user(partner_2)
            formatted_date = f"{date.day:02} {MONTHS[date.month - 1]}, {date.hour:02}:{date.minute:02}"

            if event_type == "creature":
                status = "Создан"
            elif event_type == "divorce":
                status = "Развод"
            else:
                status = str(event_type)

            lines.append(
                f"<:marry:1515641492675497984> **{status}**\n"
                f"{username_1} и {username_2} — **{formatted_date}**"
            )

        description = "\n\n".join(lines) if lines else "История чиста..."
        return self.build_view(
            title,
            description,
            footer=f"Страница {page} из {total_pages}",
            rows=rows,
            thumbnail_url=thumbnail_url,
        )

    async def make_navigation_view(self, interaction, history, page, total_pages, title, thumbnail_url):
        # Определяем, какие кнопки должны быть потухшими
        is_first_page = page == 1
        is_last_page = page == total_pages
        has_multiple_pages = total_pages > 1

        async def back_callback(btn_interaction: discord.Interaction):
            await btn_interaction.response.defer()
            if btn_interaction.user.id != interaction.user.id:
                return

            new_page = max(page - 1, 1)
            await btn_interaction.message.edit(
                view=await self.make_navigation_view(
                    interaction,
                    history,
                    new_page,
                    total_pages,
                    title,
                    thumbnail_url,
                ),
                allowed_mentions=NO_MENTIONS,
            )

        async def delete_callback(btn_interaction: discord.Interaction):
            await btn_interaction.response.defer()
            if btn_interaction.user.id == interaction.user.id:
                await btn_interaction.message.delete()

        async def next_callback(btn_interaction: discord.Interaction):
            await btn_interaction.response.defer()
            if btn_interaction.user.id != interaction.user.id:
                return

            new_page = min(page + 1, total_pages)
            await btn_interaction.message.edit(
                view=await self.make_navigation_view(
                    interaction,
                    history,
                    new_page,
                    total_pages,
                    title,
                    thumbnail_url,
                ),
                allowed_mentions=NO_MENTIONS,
            )

        # Создаем кнопки с учетом состояния disabled
        back_button = self.button(
            emoji=discord.PartialEmoji(name="left", id=1515638771071324250),
            custom_id="marries_back",
            callback=back_callback,
            disabled=is_first_page or not has_multiple_pages,  # Потухшая если первая страница или всего 1 страница
        )

        delete_button = self.button(
            emoji=discord.PartialEmoji(name="del", id=1515639124256751676),
            custom_id="marries_delete",
            callback=delete_callback,
            disabled=False,  # Кнопка удаления всегда активна
        )

        next_button = self.button(
            emoji=discord.PartialEmoji(name="right", id=1515638675931795626),
            custom_id="marries_next",
            callback=next_callback,
            disabled=is_last_page or not has_multiple_pages,  # Потухшая если последняя страница или всего 1 страница
        )

        row = self.row(back_button, delete_button, next_button)

        return await self.make_page_history_view(
            page,
            total_pages,
            history,
            title=title,
            rows=[row],
            thumbnail_url=thumbnail_url,
        )

    @marries.command(name="history", description="История браков.")
    @app_commands.describe(пользователь="Выберите пользователя.")
    async def history(
        self,
        interaction: discord.Interaction,
        пользователь: discord.Member | None = None,
    ):
        await interaction.response.defer()

        target = пользователь or interaction.user
        history = await maybe_await(self.db.get_marries_history(target))

        if not history:
            await interaction.edit_original_response(
                view=self.build_view(
                    "История браков",
                    "История чиста...",
                    thumbnail_url=str(interaction.user.display_avatar.url),
                ),
                allowed_mentions=NO_MENTIONS,
            )
            return

        total_pages = math.ceil(len(history) / 5)
        
        if пользователь:
            title = f"История браков — {пользователь.display_name}"
        else:
            title = "История браков"

        await interaction.edit_original_response(
            view=await self.make_navigation_view(
                interaction,
                history,
                1,
                total_pages,
                title,
                str(interaction.user.display_avatar.url),
            ),
            allowed_mentions=NO_MENTIONS,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Marries(bot))