import asyncio
import json

import discord
from discord.ext import commands

from modules.Logger import *
from modules.Database import Database
from modules.Utils import Utils

guild_id_cmd = Utils.get_guild_id()


class LoveRooms(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database()
        self.guild = None
        self.entry_love_room = None
        self.love_category = None

        try:
            with open("./assets/settings.json", "r", encoding="utf8") as settings:
                data = json.load(settings)

            self.guild_id = data.get("guild_id")
            self.settings_roles = data.get("roles") or {}
            self.settings_channels = data.get("channels") or {}
            self.settings_prices = data.get("prices") or {}

            logger.info("Настройки загружены.")

        except Exception as e:
            logger.error(f"Не можем загрузить настройки: {e}")
            raise

    @commands.Cog.listener()
    async def on_ready(self):
        self.guild = discord.utils.get(self.bot.guilds, id=self.guild_id)

        if not self.guild:
            logger.error(f"Guild {self.guild_id} не найден.")
            return

        self.entry_love_room = discord.utils.get(
            self.guild.voice_channels,
            id=self.settings_channels.get("entry_love_room"),
        )
        self.love_category = discord.utils.get(
            self.guild.channels,
            id=self.settings_channels.get("love_category"),
        )

        logger.info("LoveRooms - start")

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if member.bot:
            return

        try:
            # Проверяем, что пользователь вообще в голосовом канале
            if not member.voice or not member.voice.channel:
                return

            # Только перемещение в существующую комнату, если она куплена
            await self._handle_love_room_join(member, before, after)
        except discord.HTTPException as e:
            if e.code == 40032:  # Target user is not connected to voice
                logger.debug(f"Пользователь {member.name} не в голосовом канале при попытке перемещения")
            else:
                logger.error(f"HTTP ошибка в on_voice_state_update LoveRooms: {e}")
        except Exception as e:
            logger.error(f"Ошибка в on_voice_state_update LoveRooms: {e}")

    async def _handle_love_room_join(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        # Проверяем, что входной канал существует
        if not self.entry_love_room:
            logger.warning("Входной канал любовной комнаты не найден")
            return

        if after.channel != self.entry_love_room:
            return

        if before.channel == after.channel:
            return

        # Проверяем, находится ли пользователь в голосовом канале сейчас
        if not member.voice or not member.voice.channel:
            logger.debug(f"Пользователь {member.name} покинул голосовой канал")
            return

        # Проверяем, есть ли у пользователя брак
        try:
            marriage_info = self.db.get_info_marriege(member)
        except Exception as e:
            logger.error(f"Ошибка при получении информации о браке для {member.id}: {e}")
            await self._move_to_none_safely(member)
            return

        if not marriage_info or marriage_info[0] == 0:
            await self._move_to_none_safely(member)
            return

        # Проверяем, куплена ли комната
        try:
            love_room_data = self.db.get_data_loveRoom(member)
        except Exception as e:
            logger.error(f"Ошибка при получении данных любовной комнаты для {member.id}: {e}")
            await self._move_to_none_safely(member)
            return

        if not love_room_data or not love_room_data.get("bought", False):
            await self._move_to_none_safely(member)
            return

        # Проверяем, существует ли уже комната
        if love_room_data.get("id", 0) != 0:
            channel = discord.utils.get(self.guild.channels, id=love_room_data["id"])
            if channel:
                # Проверяем, что пользователь все еще в голосовом канале перед перемещением
                if member.voice and member.voice.channel:
                    try:
                        await member.move_to(channel)
                        logger.info(f"{member.name} перемещен в любовную комнату {channel.name}")
                    except discord.HTTPException as e:
                        if e.code == 40032:
                            logger.debug(f"Пользователь {member.name} покинул голосовой канал до перемещения")
                        else:
                            logger.error(f"Ошибка при перемещении в любовную комнату: {e}")
                return

        # Если комната куплена, но не создана - не создаем автоматически
        await self._move_to_none_safely(member)

    async def _move_to_none_safely(self, member: discord.Member):
        """Безопасно перемещает пользователя в None (отключает от голосового канала)"""
        try:
            # Проверяем, что пользователь все еще в голосовом канале
            if member.voice and member.voice.channel:
                await member.move_to(None)
        except discord.HTTPException as e:
            if e.code == 40032:
                logger.debug(f"Пользователь {member.name} уже не в голосовом канале")
            else:
                logger.error(f"Ошибка при отключении пользователя {member.name}: {e}")
        except Exception as e:
            logger.error(f"Неизвестная ошибка при отключении пользователя {member.name}: {e}")

    def cog_unload(self):
        try:
            self.db.conn.close()
            self.db.conn_log.close()
        except Exception:
            pass

        logger.info("LoveRooms выгружен")


async def setup(bot: commands.Bot):
    await bot.add_cog(LoveRooms(bot))