import inspect
from datetime import datetime

import discord
from discord.ext import commands, tasks

from modules.Database import Database
from modules.Logger import *
from modules.Utils import Utils


guild_id = Utils.get_guild_id()


async def maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database()
        self.utils = Utils()

        # Убраны voice_tracker.start() и всё, что связано с дублирующим учётом войса.
        # Теперь время считает только Tracker.
        self.messages_counter.start()
        self.inventory_cleaner.start()
        self.role_rental_checker.start()

    # ============================================================
    # LISTENERS
    # ============================================================

    @commands.Cog.listener()
    async def on_ready(self):
        try:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                logger.warning(f"Гильдия с ID {guild_id} не найдена")
                return

            members = guild.members
            logger.info(f"Начинаю добавление {len(members)} участников в БД...")

            for member in members:
                if member.bot:
                    continue

                await maybe_await(self.db.write_new_user(member))
                await maybe_await(self.db.write_new_user_tracker(member))
                await maybe_await(self.db.log_write_new_user(member))
                await maybe_await(self.db.set_null_dates(member))

            logger.info("Все участники добавлены в БД")
        except Exception as exc:
            logger.error(f"Ошибка при добавлении участников в БД: {exc}")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        try:
            await maybe_await(self.db.write_new_user(member))
            await maybe_await(self.db.write_new_user_tracker(member))
            await maybe_await(self.db.log_write_new_user(member))
            logger.info(f"Новый участник добавлен в БД: {member.name}#{member.discriminator}")
        except Exception as exc:
            logger.error(f"Ошибка при добавлении участника {member.id}: {exc}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            await self.bot.process_commands(message)
            return

        try:
            self.utils.write_message(message.author.id)
        except Exception as exc:
            logger.error(f"Ошибка при обработке сообщения: {exc}")
        finally:
            await self.bot.process_commands(message)

    # Удалён on_voice_state_update – теперь время считает только Tracker.

    # ============================================================
    # HELPERS
    # ============================================================

    async def _remove_role_safely(self, member, role, reason):
        try:
            await member.remove_roles(role, reason=reason)
            return True
        except Exception as exc:
            logger.error(f"Ошибка удаления роли {role.id} у пользователя {member.id}: {exc}")
            return False

    # ============================================================
    # BACKGROUND TASKS
    # ============================================================

    @tasks.loop(seconds=30)
    async def messages_counter(self):
        try:
            messages_data = self.utils.get_messages()
            if messages_data:
                await maybe_await(self.db.save_message_count(messages_data))
                logger.debug(f"Сохранено {sum(messages_data.values())} сообщений")
        except Exception as exc:
            logger.error(f"Ошибка сохранения счётчика сообщений: {exc}")

    # voice_tracker удалён – всё идёт через Tracker.

    @tasks.loop(hours=24)
    async def inventory_cleaner(self):
        try:
            await maybe_await(self.db.decrease_inventory_days())
            expired_roles = await maybe_await(self.db.get_expired_inventory_roles())

            for role_data in expired_roles:
                role_id = role_data[2]
                user_id = role_data[1]
                role_name = role_data[3]

                await maybe_await(self.db.remove_role_from_inventory(user_id, role_id))

                guild = self.bot.get_guild(guild_id)
                if not guild:
                    continue

                member = guild.get_member(user_id)
                role = guild.get_role(role_id)

                if member and role:
                    removed = await self._remove_role_safely(member, role, "Срок аренды истёк")
                    if removed:
                        logger.info(f"Роль {role_name} удалена у пользователя {member.name} (срок истёк)")

            logger.info(f"Очистка инвентаря завершена, удалено {len(expired_roles)} просроченных ролей")
        except Exception as exc:
            logger.error(f"Ошибка очистки инвентаря: {exc}")

    @tasks.loop(hours=1)
    async def role_rental_checker(self):
        try:
            expired_rentals = await maybe_await(self.db.get_expired_role_rentals())

            for rental in expired_rentals:
                role_id = rental[0]
                buyer_id = rental[1]
                auto_renew = rental[2]

                if auto_renew:
                    shop_info = await maybe_await(self.db.get_shop_role_info(role_id))
                    if not shop_info:
                        await maybe_await(self.db.extend_role_rental(role_id, buyer_id))
                        logger.info(f"Автоматическое продление аренды роли {role_id} для пользователя {buyer_id}")
                        continue

                    cost = shop_info["cost"]
                    balance = await maybe_await(self.db.get_balance(buyer_id))

                    if balance >= cost:
                        await maybe_await(self.db.take_money(buyer_id, cost))
                        await maybe_await(self.db.extend_role_rental(role_id, buyer_id))
                        logger.info(f"Списано {cost} монет за продление роли {role_id}")
                    else:
                        await maybe_await(self.db.set_auto_renew_role(role_id, buyer_id, False))
                        logger.warning(f"Недостаточно средств для автопродления роли {role_id} у пользователя {buyer_id}")
                    continue

                await maybe_await(self.db.remove_role_rental(role_id, buyer_id))

                guild = self.bot.get_guild(guild_id)
                if guild:
                    member = guild.get_member(buyer_id)
                    role = guild.get_role(role_id)
                    if member and role:
                        removed = await self._remove_role_safely(member, role, "Срок аренды истёк")
                        if removed:
                            logger.info(f"Роль {role_id} удалена у пользователя {buyer_id} (аренда истекла)")

                await maybe_await(self.db.remove_role_from_inventory(buyer_id, role_id))
                logger.info(f"Аренда роли {role_id} для пользователя {buyer_id} завершена")

            if expired_rentals:
                logger.info(f"Проверка аренд завершена, обработано {len(expired_rentals)} записей")
        except Exception as exc:
            logger.error(f"Ошибка проверки аренд ролей: {exc}")

    # ============================================================
    # BEFORES
    # ============================================================

    @messages_counter.before_loop
    @inventory_cleaner.before_loop
    @role_rental_checker.before_loop
    async def before_tasks(self):
        await self.bot.wait_until_ready()

    # ============================================================
    # UNLOAD
    # ============================================================

    def cog_unload(self):
        self.messages_counter.cancel()
        self.inventory_cleaner.cancel()
        self.role_rental_checker.cancel()

        close = getattr(self.db, "close", None)
        if close:
            close()


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))