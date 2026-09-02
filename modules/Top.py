import inspect
import math
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from modules.Database import Database
from modules.Logger import *
from modules.Utils import Utils


guild_id_cmd = Utils.get_guild_id()
ACCENT = 0x2F3136
COIN = "<:coin:1515637898735652924>"
MARRY = "<:marry:1515641492675497984>"
NO_MENTIONS = discord.AllowedMentions.none()


async def maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def clamp_text(value, limit=3800):
    value = "" if value is None else str(value)
    return value if len(value) <= limit else value[: limit - 3] + "..."


def guild_age_minutes(guild):
    if guild is None or guild.created_at is None:
        return None

    created_at = guild.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    age_seconds = (datetime.now(timezone.utc) - created_at).total_seconds()
    return max(int(age_seconds // 60) + 10, 0)


class Top(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database()
        
    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("/top - start")
        guild = discord.utils.get(self.bot.guilds, id=guild_id_cmd)
        active_ids = self.active_voice_member_ids(guild)
        closed = await maybe_await(self.db.close_open_voice_sessions(active_ids))
        if closed:
            logger.info(f"Закрыто {closed} открытых сессий при старте бота.")

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

            for row_items in rows:
                # row_items уже является ActionRow, просто добавляем его
                container.add_item(row_items)

        view.add_item(container)
        return view

    def row(self, *items):
        row = discord.ui.ActionRow()
        for item in items:
            row.add_item(item)
        return row

    def button(self, *, emoji=None, custom_id=None, callback=None):
        button = discord.ui.Button(
            emoji=emoji,
            custom_id=custom_id,
            style=discord.ButtonStyle.secondary,
        )
        if callback is not None:
            button.callback = callback
        return button

    def active_voice_member_ids(self, guild):
        if guild is None:
            return []

        member_ids = set()
        for channel in guild.channels:
            if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                continue
            for member in channel.members:
                if not member.bot:
                    member_ids.add(member.id)

        return list(member_ids)

    def user_name(self, user_id):
        user = self.bot.get_user(int(user_id))
        return user.mention if user else f"Пользователь {user_id}"

    async def couple_name(self, user_id):
        marry_info = await maybe_await(self.db.get_info_marriege_by_user_id(user_id))
        if not marry_info:
            return f"Пара {user_id}"

        partner_1 = self.bot.get_user(marry_info[1])
        partner_2 = self.bot.get_user(marry_info[2])

        if partner_1 and partner_2:
            return f"{partner_1.mention} {MARRY} {partner_2.mention}"
        return f"Пара {user_id}"

    async def make_page_balance(self, page, total_pages, users, *, rows=None, thumbnail_url=None):
        page_users = users[(page - 1) * 10:page * 10]
        lines = []

        for index, (user_id, balance) in enumerate(page_users):
            place = (page - 1) * 10 + index + 1
            lines.append(f"**{place}.** {self.user_name(user_id)} — **{balance}** {COIN}")

        return self.build_view(
            "Топ пользователей по балансу",
            "\n".join(lines) if lines else "Нет данных для отображения.",
            footer=f"Страница {page} из {total_pages}",
            rows=rows,
            thumbnail_url=thumbnail_url,
        )

    async def make_page_online(self, page, total_pages, users, *, rows=None, thumbnail_url=None):
        page_users = users[(page - 1) * 10:page * 10]
        lines = []

        for index, (user_id, hours, minutes) in enumerate(page_users):
            place = (page - 1) * 10 + index + 1
            online = f"{hours} ч. {minutes} мин." if minutes > 0 else f"{hours} ч."
            lines.append(f"**{place}.** {self.user_name(user_id)} — **{online}**")

        return self.build_view(
            "Топ пользователей по онлайну",
            "\n".join(lines) if lines else "Нет данных для отображения.",
            footer=f"Страница {page} из {total_pages}",
            rows=rows,
            thumbnail_url=thumbnail_url,
        )

    async def make_page_messages(self, page, total_pages, users, *, rows=None, thumbnail_url=None):
        page_users = users[(page - 1) * 10:page * 10]
        lines = []

        for index, (user_id, count) in enumerate(page_users):
            place = (page - 1) * 10 + index + 1
            lines.append(f"**{place}.** {self.user_name(user_id)} — **{count} сооб.**")

        return self.build_view(
            "Топ пользователей по сообщениям",
            "\n".join(lines) if lines else "Нет данных для отображения.",
            footer=f"Страница {page} из {total_pages}",
            rows=rows,
            thumbnail_url=thumbnail_url,
        )

    async def make_page_love_online(self, page, total_pages, users, *, rows=None, thumbnail_url=None):
        page_users = users[(page - 1) * 10:page * 10]
        lines = []

        for index, (user_id, hours, minutes) in enumerate(page_users):
            place = (page - 1) * 10 + index + 1
            couple_name = await self.couple_name(user_id)
            online = f"{hours} ч. {minutes} мин." if minutes > 0 else f"{hours} ч."
            lines.append(f"**{place}.** {couple_name} — **{online}**")

        return self.build_view(
            "Топ пар по времени в лав руме",
            "\n".join(lines) if lines else "Нет данных для отображения.",
            footer=f"Страница {page} из {total_pages}",
            rows=rows,
            thumbnail_url=thumbnail_url,
        )

    async def make_page_love_balance(self, page, total_pages, users, *, rows=None, thumbnail_url=None):
        page_users = users[(page - 1) * 10:page * 10]
        lines = []

        for index, (user_id, balance) in enumerate(page_users):
            place = (page - 1) * 10 + index + 1
            couple_name = await self.couple_name(user_id)
            lines.append(f"**{place}.** {couple_name} — **{balance}** {COIN}")

        return self.build_view(
            "Топ пар по балансу",
            "\n".join(lines) if lines else "Нет данных для отображения.",
            footer=f"Страница {page} из {total_pages}",
            rows=rows,
            thumbnail_url=thumbnail_url,
        )

    async def make_page_view(self, action_type, page, total_pages, users_data, *, rows=None, thumbnail_url=None):
        if action_type == "balance":
            return await self.make_page_balance(page, total_pages, users_data, rows=rows, thumbnail_url=thumbnail_url)
        if action_type == "online":
            return await self.make_page_online(page, total_pages, users_data, rows=rows, thumbnail_url=thumbnail_url)
        if action_type == "messages":
            return await self.make_page_messages(page, total_pages, users_data, rows=rows, thumbnail_url=thumbnail_url)
        if action_type == "love_online":
            return await self.make_page_love_online(page, total_pages, users_data, rows=rows, thumbnail_url=thumbnail_url)
        if action_type == "love_balance":
            return await self.make_page_love_balance(page, total_pages, users_data, rows=rows, thumbnail_url=thumbnail_url)

        return self.build_view(
            "Ошибка",
            "Неизвестный тип топа",
            rows=rows,
            thumbnail_url=thumbnail_url,
        )

    async def navigation_view(self, interaction, action_type, users_data, page, total_pages, thumbnail_url):
        async def back_callback(btn_interaction: discord.Interaction):
            await btn_interaction.response.defer()
            if btn_interaction.user.id != interaction.user.id:
                return
            if page > 1:
                await btn_interaction.message.edit(
                    view=await self.navigation_view(
                        interaction,
                        action_type,
                        users_data,
                        page - 1,
                        total_pages,
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
            if page < total_pages:
                await btn_interaction.message.edit(
                    view=await self.navigation_view(
                        interaction,
                        action_type,
                        users_data,
                        page + 1,
                        total_pages,
                        thumbnail_url,
                    ),
                    allowed_mentions=NO_MENTIONS,
                )

        row = self.row(
            self.button(
                emoji=discord.PartialEmoji(name="left", id=1515638771071324250),
                custom_id="top_back",
                callback=back_callback,
            ),
            self.button(
                emoji=discord.PartialEmoji(name="del", id=1515639124256751676),
                custom_id="top_delete",
                callback=delete_callback,
            ),
            self.button(
                emoji=discord.PartialEmoji(name="right", id=1515638675931795626),
                custom_id="top_next",
                callback=next_callback,
            ),
        )

        return await self.make_page_view(
            action_type,
            page,
            total_pages,
            users_data,
            rows=[row],
            thumbnail_url=thumbnail_url,
        )

    @app_commands.command(name="top", description="Топ пользователей.")
    @app_commands.describe(тип="Выберите показатель")
    @app_commands.choices(тип=[
        app_commands.Choice(name="Баланс", value="Баланс"),
        app_commands.Choice(name="Онлайн", value="Онлайн"),
        app_commands.Choice(name="Сообщения", value="Сообщения"),
        app_commands.Choice(name="Лав Онлайн", value="Лав Онлайн"),
        app_commands.Choice(name="Лав баланс", value="Лав баланс"),
    ])
    @app_commands.guilds(discord.Object(id=guild_id_cmd))
    async def top(
        self,
        interaction: discord.Interaction,
        тип: str,
    ):
        await interaction.response.defer()

        action_map = {
            "Баланс": ("balance", self.db.get_top_users_balance, "Топ пользователей по балансу"),
            "Онлайн": ("online", self.db.get_top_users_online, "Топ пользователей по онлайну"),
            "Сообщения": ("messages", self.db.get_top_users_messages, "Топ пользователей по сообщениям"),
            "Лав Онлайн": ("love_online", self.db.get_top_love_online, "Топ пар по времени в лав руме"),
            "Лав баланс": ("love_balance", self.db.get_top_love_balance, "Топ пар по балансу"),
        }

        action_data = action_map.get(тип)
        thumbnail_url = str(interaction.user.display_avatar.url)

        if action_data is None:
            await interaction.edit_original_response(
                view=self.build_view("Ошибка", "Неизвестный тип топа", thumbnail_url=thumbnail_url),
                allowed_mentions=NO_MENTIONS,
            )
            return

        action_type, getter, empty_title = action_data
        if action_type == "online":
            users = await maybe_await(getter(max_total_minutes=guild_age_minutes(interaction.guild)))
        else:
            users = await maybe_await(getter())

        if not users:
            await interaction.edit_original_response(
                view=self.build_view(
                    empty_title,
                    "Нет данных для отображения.",
                    thumbnail_url=thumbnail_url,
                ),
                allowed_mentions=NO_MENTIONS,
            )
            return

        total_pages = math.ceil(len(users) / 10)
        await interaction.edit_original_response(
            view=await self.navigation_view(
                interaction,
                action_type,
                users,
                1,
                total_pages,
                thumbnail_url,
            ),
            allowed_mentions=NO_MENTIONS,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Top(bot))