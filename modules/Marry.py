import inspect
import json

import discord
from discord import app_commands
from discord.ext import commands

from modules.Logger import *
from modules.Database import Database
from modules.Utils import Utils

guild_id_cmd = Utils.get_guild_id()

DEFAULT_IMAGE = "https://cdn.discordapp.com/attachments/992883178362642453/1029462389130792970/-1.png"


async def maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def clamp_text(value, limit=3800):
    value = "" if value is None else str(value)
    return value if len(value) <= limit else value[: limit - 3] + "..."


class Marry(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database()
        self.guild = None
        self.marry_role = None

        try:
            with open("./assets/settings.json", "r", encoding="utf8") as settings:
                data = json.load(settings)

            self.guild_id = data.get("guild_id")
            self.settings_roles = data.get("roles") or {}
            self.settings_prices = data.get("prices") or {}

            logger.info("Настройки загружены.")

        except Exception as e:
            logger.error(f"Не можем загрузить настройки: {e}")
            raise

    @commands.Cog.listener()
    async def on_ready(self):
        self._bind_guild_objects(discord.utils.get(self.bot.guilds, id=self.guild_id))
        logger.info("/marry - start")

    def _bind_guild_objects(self, guild: discord.Guild | None):
        if guild is None:
            return

        self.guild = guild
        self.marry_role = guild.get_role(self.settings_roles.get("marry_role"))

        if self.marry_role is None:
            logger.warning("Роль marry_role не найдена в настройках!")

    def build_view(self, title, description=None, *, footer=None, rows=None, image_url=None, timeout=None):
        view = discord.ui.LayoutView(timeout=timeout or None)
        container = discord.ui.Container()

        content = f"## {title}"
        if description:
            content += f"\n\n{description}"
        if footer:
            content += f"\n\n-# {footer}"

        container.add_item(discord.ui.TextDisplay(content=clamp_text(content)))

        if image_url:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(image_url)))

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
            style=style
        )
        if callback is not None:
            button.callback = callback
        return button

    async def respond(self, interaction, view, *, ephemeral=False):
        if interaction.response.is_done():
            return await interaction.followup.send(view=view, ephemeral=ephemeral, wait=True)
        return await interaction.response.send_message(view=view, ephemeral=ephemeral)

    async def send_notice(self, interaction, title, description, *, ephemeral=True, image_url=DEFAULT_IMAGE):
        view = self.build_view(title, description, image_url=image_url)
        if interaction.response.is_done():
            await interaction.followup.send(view=view, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(view=view, ephemeral=ephemeral)

    class ProposalView(discord.ui.LayoutView):

        def __init__(
            self,
            cog: "Marry",
            author: discord.Member,
            пользователь: discord.Member,
            cost_marry: int,
        ):
            super().__init__(timeout=180)  # 3 минуты на ответ
            self.cog = cog
            self.author = author
            self.пользователь = пользователь
            self.cost_marry = cost_marry
            self.message: discord.Message | None = None
            self._resolved = False

            accept_button = discord.ui.Button(
                label="Принять",
                style=discord.ButtonStyle.success,
                custom_id=f"marry_accept_{author.id}_{пользователь.id}",
            )
            accept_button.callback = self.accept_callback

            decline_button = discord.ui.Button(
                label="Отклонить",
                style=discord.ButtonStyle.danger,
                custom_id=f"marry_decline_{author.id}_{пользователь.id}",
            )
            decline_button.callback = self.decline_callback

            row = discord.ui.ActionRow()
            row.add_item(accept_button)
            row.add_item(decline_button)

            container = discord.ui.Container()
            container.add_item(
                discord.ui.TextDisplay(
                    content=clamp_text(
                        f"## Создание пары\n\n"
                        f"{пользователь.mention}, {author.mention} предлагает вам вступить в брак!\n\n"
                        "Вы согласны?"
                    )
                )
            )
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(DEFAULT_IMAGE)))
            container.add_item(discord.ui.Separator())
            container.add_item(row)

            self.add_item(container)

        async def on_timeout(self):
            if self._resolved or self.message is None:
                return

            self._resolved = True
            
            # Отключаем кнопки
            for container in self.children:
                if isinstance(container, discord.ui.Container):
                    for child in container.children:
                        if isinstance(child, discord.ui.ActionRow):
                            for item in child.children:
                                if isinstance(item, discord.ui.Button):
                                    item.disabled = True

            view = self.cog.build_view(
                "Упс...",
                f"К сожалению {self.пользователь.mention} не принял ваше предложение.",
                image_url=DEFAULT_IMAGE,
            )

            try:
                await self.message.edit(view=view)
            except Exception:
                pass

        async def _ensure_target(self, interaction: discord.Interaction) -> bool:
            if self._resolved:
                await self.cog.send_notice(
                    interaction,
                    "Ошибка",
                    "Это предложение уже обработано.",
                    ephemeral=True,
                    image_url=None,
                )
                return False

            if interaction.user.id == self.пользователь.id:
                return True

            await self.cog.send_notice(
                interaction,
                "Ошибка",
                "Эта кнопка не для вас!",
                ephemeral=True,
                image_url=None,
            )
            return False

        async def accept_callback(self, interaction: discord.Interaction):
            if not await self._ensure_target(interaction):
                return

            self._resolved = True
            await interaction.response.defer()

            # Отключаем кнопки
            for container in self.children:
                if isinstance(container, discord.ui.Container):
                    for child in container.children:
                        if isinstance(child, discord.ui.ActionRow):
                            for item in child.children:
                                if isinstance(item, discord.ui.Button):
                                    item.disabled = True

            if await maybe_await(self.cog.db.is_marry(self.пользователь.id)):
                view = self.cog.build_view(
                    "Создание пары",
                    "Вы уже состоите в браке!",
                    image_url=DEFAULT_IMAGE,
                )
                await interaction.edit_original_response(view=view)
                self.stop()
                return

            if await maybe_await(self.cog.db.is_marry(self.author.id)):
                view = self.cog.build_view(
                    "Создание пары",
                    "Инициатор уже состоит в браке!",
                    image_url=DEFAULT_IMAGE,
                )
                await interaction.edit_original_response(view=view)
                self.stop()
                return

            await maybe_await(self.cog.db.write_new_marry(self.author, self.пользователь))

            if self.cog.marry_role:
                try:
                    await self.author.add_roles(self.cog.marry_role)
                    await self.пользователь.add_roles(self.cog.marry_role)
                except Exception as e:
                    logger.error(f"Ошибка при выдаче роли: {e}")

            await maybe_await(self.cog.db.take_money(self.author.id, self.cost_marry))
            await maybe_await(
                self.cog.db.write_new_transactions(
                    self.author,
                    "Создание брака",
                    -self.cost_marry,
                )
            )
            await maybe_await(
                self.cog.db.write_log_in_history(
                    self.author,
                    self.пользователь,
                    "creature",
                )
            )

            logger.info(f"Создан брак между {self.author.name} и {self.пользователь.name}")

            view = self.cog.build_view(
                "Брак",
                f"{self.author.mention} и {self.пользователь.mention} заключили брак, поздравьте их!",
                image_url=DEFAULT_IMAGE,
            )

            message = self.message or interaction.message
            await message.edit(view=view)
            self.stop()

        async def decline_callback(self, interaction: discord.Interaction):
            if not await self._ensure_target(interaction):
                return

            self._resolved = True
            await interaction.response.defer()

            # Отключаем кнопки
            for container in self.children:
                if isinstance(container, discord.ui.Container):
                    for child in container.children:
                        if isinstance(child, discord.ui.ActionRow):
                            for item in child.children:
                                if isinstance(item, discord.ui.Button):
                                    item.disabled = True

            view = self.cog.build_view(
                "Отказ",
                f"К сожалению {self.пользователь.mention} отказался от брака с {self.author.mention}.",
                image_url=DEFAULT_IMAGE,
            )

            message = self.message or interaction.message
            await message.edit(view=view)
            self.stop()

    @app_commands.command(name="marry", description="Заключить брак.")
    @app_commands.describe(пользователь="Выберите пользователя.")
    @app_commands.guilds(discord.Object(id=guild_id_cmd))
    async def marry(
        self,
        interaction: discord.Interaction,
        пользователь: discord.Member,
    ):
        if interaction.guild and self.guild is None:
            self._bind_guild_objects(interaction.guild)

        author = interaction.user

        if not isinstance(author, discord.Member):
            author = interaction.guild.get_member(interaction.user.id)

        if author is None:
            return await self.send_notice(
                interaction,
                "Ошибка",
                "Не удалось определить пользователя.",
                ephemeral=True,
                image_url=None,
            )

        if self.marry_role is None:
            return await self.send_notice(
                interaction,
                "Ошибка",
                "Роль для брака не настроена! Обратитесь к администратору.",
                ephemeral=True,
                image_url=None,
            )

        if пользователь.bot:
            return await self.send_notice(
                interaction,
                "Создание пары",
                "Нельзя создать брак с ботом.",
                ephemeral=True,
            )

        if пользователь.id == author.id:
            return await self.send_notice(
                interaction,
                "Создание пары",
                "Вы не можете создать брак с самим собой.",
                ephemeral=True,
            )

        if await maybe_await(self.db.is_marry(author.id)):
            return await self.send_notice(
                interaction,
                "Создание пары",
                "Вы уже состоите в браке!",
                ephemeral=True,
            )

        if await maybe_await(self.db.is_marry(пользователь.id)):
            return await self.send_notice(
                interaction,
                "Создание пары",
                "Этот человек уже состоит в браке!",
                ephemeral=True,
            )

        cost_marry = self.settings_prices.get("marry_create_standart", 1500)
        balance = await maybe_await(self.db.get_balance(author.id))

        if balance < cost_marry:
            return await self.send_notice(
                interaction,
                "Создание пары",
                (
                    "На вашем счету недостаточно средств!\n\n"
                    f"Для создания пары вам нужно ещё **{cost_marry - balance}** "
                    "<:coin:1515637898735652924>"
                ),
                ephemeral=True,
            )

        view = self.ProposalView(self, author, пользователь, cost_marry)

        await interaction.response.send_message(view=view)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot):
    await bot.add_cog(Marry(bot))