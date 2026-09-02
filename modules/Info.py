import discord
from discord import app_commands
from discord.ext import commands

from modules.Logger import *
from modules.Utils import Utils


guild_id_cmd = Utils.get_guild_id()

NO_MENTIONS = discord.AllowedMentions.none()


class V2Mixin:
    def build_view(self, title, description=None, *, footer=None, buttons=None, image_url=None):
        view = discord.ui.LayoutView(timeout=None)  # timeout=None для LayoutView
        container = discord.ui.Container()
        
        # Заголовок
        container.add_item(discord.ui.TextDisplay(content=f"## {title}"))
        
        # Описание
        if description:
            container.add_item(discord.ui.TextDisplay(content=description))
        
        # Футер
        if footer:
            container.add_item(discord.ui.TextDisplay(content=f"-# {footer}"))
        
        # Изображение через MediaGallery
        if image_url:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(image_url)))
        
        # Кнопки - создаем ActionRow и добавляем все кнопки в одну строку
        if buttons:
            container.add_item(discord.ui.Separator())
            row = discord.ui.ActionRow()
            for button in buttons:
                row.add_item(button)
            container.add_item(row)
        
        view.add_item(container)
        return view

    def button(self, label=None, *, emoji=None, callback=None, url=None, style=discord.ButtonStyle.secondary):
        # Убираем timeout=None, так как у Button нет этого параметра
        button = discord.ui.Button(
            label=label,
            emoji=emoji,
            style=style,
            url=url
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


class UserInfo(commands.Cog, V2Mixin):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("/avatar и /banner - загружены")

    @app_commands.command(name="avatar", description="Просмотр аватара пользователя.")
    @app_commands.describe(
        пользователь="Выберите пользователя для просмотра аватара.",
    )
    @app_commands.guilds(discord.Object(id=guild_id_cmd))
    async def avatar(
        self,
        interaction: discord.Interaction,
        пользователь: discord.Member = None,
    ):
        # Если пользователь не указан, берем себя
        target_user = пользователь or interaction.user
        
        # Получаем URL аватара в максимальном качестве
        avatar_url = target_user.display_avatar.url
        
        # Создаем кнопку
        open_button = self.button(
            label="Открыть в браузере",
            url=avatar_url,
            style=discord.ButtonStyle.link
        )
        
        # Создаем view с изображением
        view = self.build_view(
            title=f"Аватар - {target_user.display_name}",
            buttons=[open_button],
            image_url=avatar_url
        )
        
        await self.respond(interaction, view, ephemeral=False)

    @app_commands.command(name="banner", description="Просмотр баннера пользователя.")
    @app_commands.describe(
        пользователь="Выберите пользователя для просмотра баннера.",
    )
    @app_commands.guilds(discord.Object(id=guild_id_cmd))
    async def banner(
        self,
        interaction: discord.Interaction,
        пользователь: discord.Member = None,
    ):
        # Если пользователь не указан, берем себя
        target_user = пользователь or interaction.user
        
        # Получаем пользователя через API для доступа к баннеру
        user = await self.bot.fetch_user(target_user.id)
        
        # Проверяем наличие баннера
        if not user.banner:
            view = self.build_view(
                "Ошибка",
                description=f"У пользователя {target_user.display_name} нет баннера!"
            )
            return await self.respond(interaction, view, ephemeral=True)
        
        # Получаем URL баннера в максимальном качестве
        banner_url = user.banner.url
        
        # Создаем кнопку
        open_button = self.button(
            label="Открыть в браузере",
            url=banner_url,
            style=discord.ButtonStyle.link
        )
        
        # Создаем view с изображением
        view = self.build_view(
            title=f"Баннер - {target_user.display_name}",
            buttons=[open_button],
            image_url=banner_url
        )
        
        await self.respond(interaction, view, ephemeral=False)


# ============================================================
# SETUP
# ============================================================
async def setup(bot: commands.Bot):
    """Функция для загрузки кога"""
    await bot.add_cog(UserInfo(bot))