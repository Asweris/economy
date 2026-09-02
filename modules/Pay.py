import inspect

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

PAY_IMAGE_URL = "https://cdn.discordapp.com/attachments/992883178362642453/1029462389130792970/-1.png"
NO_MENTIONS = discord.AllowedMentions.none()


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


class Pay(commands.Cog, V2Mixin):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database()

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("/pay - start")

    def cog_unload(self):
        close = getattr(self.db, "close", None)
        if close:
            close()

    @app_commands.command(name="pay", description="Передать валюту.")
    @app_commands.describe(
        пользователь="Выберите пользователя.",
        сумма="Сумма для передачи.",
    )
    @app_commands.guilds(discord.Object(id=guild_id_cmd))
    async def pay(
        self,
        interaction: discord.Interaction,
        пользователь: discord.Member,
        сумма: app_commands.Range[int, 50, 10000],
    ):
        balance = await maybe_await(self.db.get_balance(interaction.user.id))
        balance = int(balance or 0)

        # Получаем URL аватарки пользователя
        user_avatar_url = str(interaction.user.display_avatar.url)

        if пользователь.id == interaction.user.id:
            return await self.respond(
                interaction,
                self.build_view(
                    "Ошибка",
                    "Нельзя передать валюту самому себе!",
                    thumbnail_url=user_avatar_url,
                ),
                ephemeral=True,
            )

        if сумма > balance:
            return await self.respond(
                interaction,
                self.build_view(
                    "Ошибка",
                    "Проверьте баланс! У вас недостаточно средств.\n\n"
                    f"**Ваш баланс:** **{balance}** {COIN}\n"
                    f"**Сумма перевода:** **{сумма}** {COIN}",
                    image_url=PAY_IMAGE_URL,
                    thumbnail_url=user_avatar_url,
                ),
                ephemeral=True,
            )

        await maybe_await(self.db.transfer_money(interaction.user, пользователь, сумма))

        await maybe_await(
            self.db.write_new_transactions(
                interaction.user,
                f"Перевод {пользователь.mention}",
                -сумма,
            )
        )

        await maybe_await(
            self.db.write_new_transactions(
                пользователь,
                f"Перевод от {interaction.user.mention}",
                сумма,
            )
        )

        logger.info(f"{interaction.user.name} передал {пользователь.name} {сумма} валюты")

        new_balance = balance - сумма

        await self.respond(
            interaction,
            self.build_view(
                "Передача валюты",
                f"**Перевод успешно выполнен.**\n\n"
                f"**Отправитель:** {interaction.user.mention}\n"
                f"**Получатель:** {пользователь.mention}\n"
                f"**Сумма:** **{сумма}** {COIN}\n\n"
                f"**Ваш баланс после перевода:** **{new_balance}** {COIN}",
                image_url=PAY_IMAGE_URL,
                thumbnail_url=user_avatar_url,
            ),
        )


# ============================================================
# SETUP
# ============================================================
async def setup(bot: commands.Bot):
    """Функция для загрузки кога"""
    await bot.add_cog(Pay(bot))