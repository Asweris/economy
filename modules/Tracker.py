import inspect
from datetime import datetime

import discord
from discord.ext import commands

from modules.Database import Database
from modules.Logger import *
from modules.Utils import Utils


guild_id_cmd = Utils.get_guild_id()


async def maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


class Tracker(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database()
        self.guild = None

    @commands.Cog.listener()
    async def on_ready(self):
        self.guild = discord.utils.get(self.bot.guilds, id=guild_id_cmd)
        logger.info("Tracker - start")

    def cog_unload(self):
        close = getattr(self.db, "close", None)
        if close:
            close()
        logger.info("Tracker выгружен")

    # ------------------ Love Room helpers ------------------
    async def _partner_is_present(self, member: discord.Member, channel: discord.VoiceChannel) -> bool:
        data = await maybe_await(self.db.get_info_marriege(member))
        if not data:
            return False

        if self.guild is None:
            self.guild = member.guild

        partner_1 = self.guild.get_member(data[1])
        partner_2 = self.guild.get_member(data[2])

        for member_in in channel.members:
            if partner_1 and partner_1.id == member.id:
                if partner_2 and member_in.id == partner_2.id:
                    return True
            elif partner_2 and partner_2.id == member.id:
                if partner_1 and member_in.id == partner_1.id:
                    return True
        return False

    async def _try_start_love_room_time(self, member: discord.Member, channel: discord.VoiceChannel):
        is_marry = await maybe_await(self.db.is_marry(member.id))
        if not is_marry:
            return

        love_room_data = await maybe_await(self.db.get_data_loveRoom(member))
        if not love_room_data:
            return

        if channel.id != love_room_data.get("id"):
            return

        if await self._partner_is_present(member, channel):
            await maybe_await(
                self.db.write_data_loveRoom(
                    member,
                    "joined_at",
                    int(datetime.now().timestamp()),
                )
            )

    async def _try_stop_love_room_time(self, member: discord.Member, channel: discord.VoiceChannel):
        is_marry = await maybe_await(self.db.is_marry(member.id))
        if not is_marry:
            return

        love_room_data = await maybe_await(self.db.get_data_loveRoom(member))
        if not love_room_data:
            return

        if channel.id == love_room_data.get("id"):
            # Вычисляем длительность сессии в любовной комнате
            joined_at = int(love_room_data.get("joined_at", 0) or 0)
            if joined_at != 0:
                join_time = datetime.fromtimestamp(joined_at)
                left_time = datetime.now()
                delta = left_time - join_time

                # Добавляем время к статистике любовной комнаты
                total_hours = love_room_data.get("total_hours", 0)
                total_minutes = love_room_data.get("total_minutes", 0)
                total_hours += delta.days * 24 + delta.seconds // 3600
                total_minutes += (delta.seconds % 3600) // 60
                if total_minutes >= 60:
                    total_hours += total_minutes // 60
                    total_minutes %= 60

                await maybe_await(self.db.update_data(member, "love", total_hours, total_minutes))
                await maybe_await(self.db.write_data_loveRoom(member, "joined_at", 0))

    # ------------------ Voice State Update ------------------
    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        try:
            # Зашёл в канал
            if before.channel is None and after.channel is not None:
                await maybe_await(self.db.user_set_action_channel(member, "join"))
                await self._try_start_love_room_time(member, after.channel)
                logger.info(f"[{datetime.now()}] {member.name} зашёл в {after.channel.name}")
                return

            # Вышел из канала
            if before.channel is not None and after.channel is None:
                # Добавляем время обычного войса
                data = await maybe_await(self.db.get_data(member))
                if data:
                    joined_at = int(data[0] or 0)
                    if joined_at > 0:
                        now_ts = int(datetime.now().timestamp())
                        delta_minutes = (now_ts - joined_at) // 60
                        if delta_minutes > 0:
                            await maybe_await(self.db.add_voice_time(member.id, delta_minutes))
                    await maybe_await(self.db.set_null_dates(member))

                # Останавливаем время любовной комнаты, если надо
                await self._try_stop_love_room_time(member, before.channel)
                logger.info(f"[{datetime.now()}] {member.name} вышел с {before.channel.name}")
                return

            # Переключение между каналами
            if before.channel is not None and after.channel is not None:
                if before.channel.id == after.channel.id:
                    return

                logger.info(
                    f"[{datetime.now()}] {member.name} поменял канал с "
                    f"{before.channel.name} на {after.channel.name}"
                )

                # Любовная комната: старт/стоп
                is_marry = await maybe_await(self.db.is_marry(member.id))
                if is_marry:
                    love_room_data = await maybe_await(self.db.get_data_loveRoom(member))
                    if love_room_data:
                        love_room_id = love_room_data.get("id")
                        if after.channel.id == love_room_id:
                            if await self._partner_is_present(member, after.channel):
                                await maybe_await(
                                    self.db.write_data_loveRoom(
                                        member,
                                        "joined_at",
                                        int(datetime.now().timestamp()),
                                    )
                                )
                        elif before.channel.id == love_room_id:
                            await self._try_stop_love_room_time(member, before.channel)

                # Обычный войс: при смене канала закрываем старую сессию и начинаем новую,
                # чтобы время не терялось и не дублировалось.
                data = await maybe_await(self.db.get_data(member))
                if data:
                    joined_at = int(data[0] or 0)
                    if joined_at > 0:
                        now_ts = int(datetime.now().timestamp())
                        delta_minutes = (now_ts - joined_at) // 60
                        if delta_minutes > 0:
                            await maybe_await(self.db.add_voice_time(member.id, delta_minutes))
                await maybe_await(self.db.user_set_action_channel(member, "join"))

        except Exception as exc:
            logger.error(f"Ошибка Tracker.on_voice_state_update для {member.id}: {exc}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Tracker(bot))