import json
import time
import inspect

import discord
from discord import app_commands
from discord.ext import commands

from modules.Logger import *
from modules.Database import Database
from modules.Utils import Utils

guild_id_cmd = Utils.get_guild_id()

COIN = "<:coin:1515637898735652924>"
NO_MENTIONS = discord.AllowedMentions.none()


async def maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def format_time(seconds: int) -> str:
    """Форматирует время в удобный для чтения вид"""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    
    if hours > 0 and minutes > 0:
        return f"{hours}ч {minutes}м"
    elif hours > 0:
        return f"{hours}ч"
    elif minutes > 0:
        return f"{minutes}м"
    else:
        return "0м"


def _parse_colour(value: str) -> discord.Colour:
    value = value.strip()
    if value.startswith("#"):
        return discord.Colour(int(value[1:], 16))
    return discord.Colour(int(value, 16))


class V2Mixin:
    def build_view(self, title, description=None, *, footer=None, rows=None, image_url=None, thumbnail_url=None):
        view = discord.ui.LayoutView(timeout=None)
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

        if image_url:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(image_url)))

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


def clamp_text(value, limit=3800):
    value = "" if value is None else str(value)
    return value if len(value) <= limit else value[: limit - 3] + "..."


class AdminPanel(commands.Cog, V2Mixin):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database()
        self.utils = Utils()
        
        self.user_room_time = {}

        try:
            with open("./assets/settings.json", "r", encoding="utf8") as settings:
                data = json.load(settings)

            self.settings_roles = data.get("roles")
            self.settings_channels = data.get("channels")
            self.settings_prices = data.get("prices", {})
            logger.info("Настройки загружены.")

        except Exception:
            logger.error("Не можем загрузить настройки :(")
            exit()

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("/apanel - start")
        logger.info("/room-manage - start")
        logger.info("/top-room - start")
        logger.info("/room-create - start")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        # Проверяем, покинул ли пользователь канал
        if before.channel:
            room = self.db.get_room_by_channel(before.channel.id)
            if room:
                user_key = f"{member.id}_{room['id']}"
                if user_key in self.user_room_time:
                    spent_time = int(time.time()) - self.user_room_time[user_key]
                    if spent_time > 0:
                        self.db.add_room_time(room['id'], spent_time)
                        logger.info(f"Добавлено {spent_time} секунд для комнаты {room['name']} (ID: {room['id']})")
                    del self.user_room_time[user_key]
        
        # Проверяем, зашел ли пользователь в канал
        if after.channel:
            room = self.db.get_room_by_channel(after.channel.id)
            if room:
                user_key = f"{member.id}_{room['id']}"
                self.user_room_time[user_key] = int(time.time())
                logger.info(f"Начат отсчет для {member.name} в комнате {room['name']}")

    def _is_admin(self, interaction: discord.Interaction) -> bool:
        return interaction.user.guild_permissions.administrator

    # =====================================================
    # ЭКРАНЫ ПАНЕЛИ
    # =====================================================

    def _main_view(self, author: discord.Member, member: discord.Member, panel_message: discord.Message):
        cog = self

        async def currency_cb(interaction: discord.Interaction):
            if not cog._is_admin(interaction):
                return
            await interaction.response.defer(ephemeral=True)
            await panel_message.edit(view=cog._currency_view(author, member, panel_message), allowed_mentions=NO_MENTIONS)

        async def rooms_cb(interaction: discord.Interaction):
            if not cog._is_admin(interaction):
                return
            await interaction.response.defer(ephemeral=True)
            await panel_message.edit(view=cog._rooms_view(author, member, panel_message), allowed_mentions=NO_MENTIONS)

        async def close_cb(interaction: discord.Interaction):
            if not cog._is_admin(interaction):
                return
            await interaction.response.defer(ephemeral=True)
            await panel_message.delete()

        btn_currency = self.button(
            label="Валюта",
            custom_id="button_manipulate_balance",
            style=discord.ButtonStyle.secondary,
            callback=currency_cb
        )

        btn_rooms = self.button(
            label="Личные комнаты",
            custom_id="button_manipulate_rooms",
            style=discord.ButtonStyle.secondary,
            callback=rooms_cb
        )

        btn_close = self.button(
            emoji=discord.PartialEmoji(name="del", id=1515639124256751676),
            custom_id="button_manipulate_close",
            style=discord.ButtonStyle.secondary,
            callback=close_cb
        )

        return self.build_view(
            "Управление пользователем",
            f"{author.mention}, **Выберите** операцию для **взаимодействия** с {member.mention}",
            rows=[self.row(btn_currency, btn_rooms, btn_close)]
        )

    def _currency_view(self, author: discord.Member, member: discord.Member, panel_message: discord.Message):
        cog = self
        balance = self.db.get_balance(member.id)

        async def give_cb(interaction: discord.Interaction):
            if not cog._is_admin(interaction):
                return
            await interaction.response.send_modal(
                BalanceGiveModal(cog, author, member, panel_message)
            )

        async def remove_cb(interaction: discord.Interaction):
            if not cog._is_admin(interaction):
                return
            await interaction.response.send_modal(
                BalanceRemoveModal(cog, author, member, panel_message)
            )

        async def back_cb(interaction: discord.Interaction):
            if not cog._is_admin(interaction):
                return
            await interaction.response.defer(ephemeral=True)
            await panel_message.edit(view=cog._main_view(author, member, panel_message), allowed_mentions=NO_MENTIONS)

        btn_give = self.button(
            label="Выдать валюту",
            custom_id="button_balance_give",
            callback=give_cb
        )

        btn_remove = self.button(
            label="Снять валюту",
            custom_id="button_balance_remove",
            callback=remove_cb
        )

        btn_back = self.button(
            label="Вернуться к управлению",
            emoji=discord.PartialEmoji(name="left", id=1515638771071324250),
            style=discord.ButtonStyle.secondary,
            callback=back_cb
        )

        return self.build_view(
            "Валюта",
            f"{author.mention}, **Выберите** операцию для **взаимодействия** с **балансом** {member.mention}\n\n"
            f"> **Баланс пользователя**\n```\n{balance}\n```",
            rows=[self.row(btn_give, btn_remove), self.row(btn_back)]
        )

    def _rooms_view(self, author: discord.Member, member: discord.Member, panel_message: discord.Message):
        cog = self

        async def create_cb(interaction: discord.Interaction):
            if not cog._is_admin(interaction):
                return
            await interaction.response.send_modal(
                RoomCreateModal(cog, author, member, panel_message)
            )

        async def delete_room_cb(interaction: discord.Interaction):
            if not cog._is_admin(interaction):
                return
            await interaction.response.defer(ephemeral=True)
            await panel_message.edit(
                view=cog._admin_delete_room_view(author, member, panel_message),
                allowed_mentions=NO_MENTIONS
            )

        async def back_cb(interaction: discord.Interaction):
            if not cog._is_admin(interaction):
                return
            await interaction.response.defer(ephemeral=True)
            await panel_message.edit(view=cog._main_view(author, member, panel_message), allowed_mentions=NO_MENTIONS)

        btn_create = self.button(
            label="Создать комнату",
            custom_id="button_rooms_create",
            callback=create_cb
        )

        btn_delete_room = self.button(
            label="Удалить комнату",
            custom_id="button_rooms_delete",
            style=discord.ButtonStyle.secondary,
            callback=delete_room_cb
        )

        btn_back = self.button(
            label="Вернуться к управлению",
            emoji=discord.PartialEmoji(name="left", id=1515638771071324250),
            style=discord.ButtonStyle.secondary,
            callback=back_cb
        )

        return self.build_view(
            "Личные комнаты",
            f"{author.mention}, **Выберите** операцию для **взаимодействия** с {member.mention}",
            rows=[self.row(btn_create, btn_delete_room), self.row(btn_back)]
        )

    def _admin_delete_room_view(self, author: discord.Member, member: discord.Member, panel_message: discord.Message):
        cog = self
        
        user_rooms = self.db.get_user_rooms(member.id)
        
        async def back_to_rooms_cb(interaction: discord.Interaction):
            if not cog._is_admin(interaction):
                return
            await interaction.response.defer(ephemeral=True)
            await panel_message.edit(
                view=cog._rooms_view(author, member, panel_message),
                allowed_mentions=NO_MENTIONS
            )
        
        if not user_rooms:
            btn_back = self.button(
                label="Назад",
                emoji=discord.PartialEmoji(name="left", id=1515638771071324250),
                style=discord.ButtonStyle.secondary,
                callback=back_to_rooms_cb
            )
            
            return self.build_view(
                "Удаление комнаты",
                f"У пользователя {member.mention} нет созданных приватных комнат.",
                rows=[self.row(btn_back)]
            )
        
        select_options = []
        for room in user_rooms:
            room_name = room.get('name', 'Без названия')
            room_id = room.get('id')
            select_options.append(
                discord.SelectOption(
                    label=room_name[:100],
                    value=str(room_id),
                    description=f"ID: {room_id}"
                )
            )
        
        select_menu = discord.ui.Select(
            placeholder="Выберите комнату для удаления",
            options=select_options,
            custom_id="admin_delete_room_select"
        )
        
        async def select_callback(interaction: discord.Interaction):
            if not cog._is_admin(interaction):
                return
            
            room_id = int(select_menu.values[0])
            room_data = cog.db.get_room_by_id(room_id)
            
            if not room_data:
                return await interaction.response.send_message(
                    "Комната не найдена.", ephemeral=True
                )
            
            room_name = room_data.get('name', 'Без названия')
            channel_id = room_data.get('channel_id')
            
            room_role = discord.utils.get(interaction.guild.roles, name=room_name)
            voice_channel = None
            if channel_id:
                voice_channel = interaction.guild.get_channel(channel_id)
            
            success = cog.db.delete_room(room_id)
            
            if success:
                if room_role:
                    await room_role.delete()
                if voice_channel:
                    await voice_channel.delete()
                
                await interaction.response.defer(ephemeral=True)
                await panel_message.edit(
                    view=cog._success_admin_delete_view(
                        author,
                        member,
                        panel_message,
                        "Комната удалена",
                        f"{author.mention}, комната **{room_name}** пользователя {member.mention} успешно удалена.",
                        "Вернуться к управлению комнатами",
                        lambda: cog._rooms_view(author, member, panel_message)
                    ),
                    allowed_mentions=NO_MENTIONS
                )
            else:
                await interaction.response.send_message(
                    "Ошибка при удалении комнаты.", ephemeral=True
                )
        
        select_menu.callback = select_callback
        
        btn_back = self.button(
            label="Назад",
            emoji=discord.PartialEmoji(name="left", id=1515638771071324250),
            style=discord.ButtonStyle.secondary,
            callback=back_to_rooms_cb
        )
        
        return self.build_view(
            "Удаление комнаты",
            f"{author.mention}, выберите комнату пользователя {member.mention} для удаления.",
            rows=[self.row(select_menu), self.row(btn_back)]
        )

    def _success_admin_delete_view(self, author: discord.Member, member: discord.Member, panel_message: discord.Message, title: str, body: str, back_label: str, back_factory):
        cog = self

        async def back_cb(interaction: discord.Interaction):
            if not cog._is_admin(interaction):
                return
            await interaction.response.defer(ephemeral=True)
            await panel_message.edit(view=back_factory(), allowed_mentions=NO_MENTIONS)

        btn_back = self.button(
            label=back_label,
            emoji=discord.PartialEmoji(name="left", id=1515638771071324250),
            style=discord.ButtonStyle.secondary,
            callback=back_cb
        )

        return self.build_view(
            title,
            body,
            rows=[self.row(btn_back)]
        )

    def _success_view(self, author: discord.Member, member: discord.Member, panel_message: discord.Message, title: str, body: str, back_label: str, back_factory):
        cog = self

        async def back_cb(interaction: discord.Interaction):
            if not cog._is_admin(interaction):
                return
            await interaction.response.defer(ephemeral=True)
            await panel_message.edit(view=back_factory(), allowed_mentions=NO_MENTIONS)

        btn_back = self.button(
            label=back_label,
            emoji=discord.PartialEmoji(name="left", id=1515638771071324250),
            style=discord.ButtonStyle.secondary,
            callback=back_cb
        )

        return self.build_view(
            title,
            body,
            rows=[self.row(btn_back)]
        )

    # =====================================================
    # ЭКРАНЫ УПРАВЛЕНИЯ КОМНАТАМИ (ДЛЯ ПОЛЬЗОВАТЕЛЕЙ)
    # =====================================================

    def _room_select_view(self, author: discord.Member, panel_message: discord.Message):
        cog = self
        
        user_rooms = self.db.get_user_rooms(author.id)
        
        if not user_rooms:
            return self.build_view(
                "Управление комнатами",
                f"{author.mention}, у вас нет созданных приватных комнат."
            )
        
        select_options = []
        for room in user_rooms:
            room_name = room.get('name', 'Без названия')
            room_id = room.get('id')
            select_options.append(
                discord.SelectOption(
                    label=room_name[:100],
                    value=str(room_id),
                    description=f"ID: {room_id}"
                )
            )
        
        select_menu = discord.ui.Select(
            placeholder="Выберите комнату для управления",
            options=select_options,
            custom_id="room_select"
        )
        
        async def select_callback(interaction: discord.Interaction):
            if interaction.user.id != author.id:
                return await interaction.response.send_message(
                    "Это не ваша панель управления.", ephemeral=True
                )
            
            room_id = int(select_menu.values[0])
            await interaction.response.defer(ephemeral=True)
            await panel_message.edit(
                view=cog._room_manage_view(author, room_id, panel_message),
                allowed_mentions=NO_MENTIONS
            )
        
        select_menu.callback = select_callback
        
        return self.build_view(
            "Управление комнатами",
            f"{author.mention}, **выберите** комнату для управления.",
            rows=[self.row(select_menu)]
        )

    def _room_manage_view(self, author: discord.Member, room_id: int, panel_message: discord.Message):
        cog = self
        
        room_data = self.db.get_room_by_id(room_id)
        if not room_data:
            return cog._room_select_view(author, panel_message)
        
        room_name = room_data.get('name', 'Без названия')
        is_hidden = room_data.get('is_hidden', False)
        owner_id = room_data.get('owner_id')
        
        is_owner = author.id == owner_id
        
        async def give_access_cb(interaction: discord.Interaction):
            if interaction.user.id != owner_id:
                return await interaction.response.send_message(
                    "Только владелец комнаты может выдавать доступ.", ephemeral=True
                )
            await interaction.response.send_modal(
                RoomGiveAccessModal(cog, author, room_id, room_name, panel_message)
            )
        
        async def remove_access_cb(interaction: discord.Interaction):
            if interaction.user.id != owner_id:
                return await interaction.response.send_message(
                    "Только владелец комнаты может забирать доступ.", ephemeral=True
                )
            await interaction.response.send_modal(
                RoomRemoveAccessModal(cog, author, room_id, room_name, panel_message)
            )
        
        async def rename_cb(interaction: discord.Interaction):
            if interaction.user.id != owner_id:
                return await interaction.response.send_message(
                    "Только владелец комнаты может изменять название.", ephemeral=True
                )
            await interaction.response.send_modal(
                RoomRenameModal(cog, author, room_id, room_name, panel_message)
            )
        
        async def delete_cb(interaction: discord.Interaction):
            if interaction.user.id != owner_id:
                return await interaction.response.send_message(
                    "Только владелец комнаты может удалять комнату.", ephemeral=True
                )
            
            channel_id = room_data.get('channel_id')
            voice_channel = None
            if channel_id:
                voice_channel = interaction.guild.get_channel(channel_id)
            
            success = self.db.delete_room(room_id)
            if success:
                room_role = discord.utils.get(interaction.guild.roles, name=room_name)
                if room_role:
                    await room_role.delete()
                if voice_channel:
                    await voice_channel.delete()
            
            await interaction.response.defer(ephemeral=True)
            await panel_message.edit(
                view=cog._success_manage_view(
                    author,
                    panel_message,
                    "Комната удалена",
                    f"{author.mention}, комната **{room_name}** успешно удалена.",
                    "Вернуться к списку комнат",
                    lambda: cog._room_select_view(author, panel_message)
                ),
                allowed_mentions=NO_MENTIONS
            )
        
        async def toggle_hidden_cb(interaction: discord.Interaction):
            if interaction.user.id != owner_id:
                return await interaction.response.send_message(
                    "Только владелец комнаты может изменять видимость.", ephemeral=True
                )
            
            channel_id = room_data.get('channel_id')
            voice_channel = None
            if channel_id:
                voice_channel = interaction.guild.get_channel(channel_id)
            
            new_hidden = not is_hidden
            self.db.update_room_hidden(room_id, new_hidden)
            
            if voice_channel:
                overwrite = voice_channel.overwrites_for(author.guild.default_role)
                overwrite.connect = not new_hidden
                overwrite.view_channel = not new_hidden
                await voice_channel.set_permissions(author.guild.default_role, overwrite=overwrite)
            
            status = "скрыта" if new_hidden else "показана"
            await interaction.response.defer(ephemeral=True)
            await panel_message.edit(
                view=cog._success_manage_view(
                    author,
                    panel_message,
                    f"Комната {status}",
                    f"{author.mention}, комната **{room_name}** теперь **{status}**.",
                    "Вернуться к управлению",
                    lambda: cog._room_manage_view(author, room_id, panel_message)
                ),
                allowed_mentions=NO_MENTIONS
            )
        
        async def access_list_cb(interaction: discord.Interaction):
            if interaction.user.id != owner_id:
                return await interaction.response.send_message(
                    "Только владелец комнаты может просматривать список доступа.", ephemeral=True
                )
            
            room_role = discord.utils.get(interaction.guild.roles, name=room_name)
            
            members_with_access = []
            if room_role:
                members_with_access = [member.mention for member in room_role.members if not member.bot]
            
            access_list = ", ".join(members_with_access) if members_with_access else "Нет участников с доступом"
            
            async def back_to_manage_cb(interaction: discord.Interaction):
                if interaction.user.id != owner_id:
                    return
                await interaction.response.defer(ephemeral=True)
                await panel_message.edit(
                    view=cog._room_manage_view(author, room_id, panel_message),
                    allowed_mentions=NO_MENTIONS
                )
            
            btn_back = cog.button(
                label="Назад",
                emoji=discord.PartialEmoji(name="left", id=1515638771071324250),
                style=discord.ButtonStyle.secondary,
                callback=back_to_manage_cb
            )
            
            access_view = cog.build_view(
                f"Участники с доступом к {room_name}",
                f"{interaction.user.mention}, список пользователей с доступом к комнате **{room_name}**:\n\n"
                f"> **Участники с доступом**: {access_list}",
                rows=[cog.row(btn_back)]
            )
            
            await interaction.response.defer(ephemeral=True)
            await panel_message.edit(view=access_view, allowed_mentions=NO_MENTIONS)
        
        async def back_cb(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            await panel_message.edit(view=cog._room_select_view(author, panel_message), allowed_mentions=NO_MENTIONS)
        
        btn_give_access = self.button(
            label="Выдать доступ",
            style=discord.ButtonStyle.secondary,
            custom_id="room_give_access",
            callback=give_access_cb
        )
        
        btn_remove_access = self.button(
            label="Забрать доступ",
            style=discord.ButtonStyle.secondary,
            custom_id="room_remove_access",
            callback=remove_access_cb
        )
        
        btn_rename = self.button(
            label="Изменить название",
            style=discord.ButtonStyle.secondary,
            custom_id="room_rename",
            callback=rename_cb
        )
        
        btn_delete = self.button(
            label="Удалить комнату",
            style=discord.ButtonStyle.secondary,
            custom_id="room_delete",
            callback=delete_cb
        )
        
        btn_toggle_hidden = self.button(
            label="Скрыть" if not is_hidden else "Показать",
            style=discord.ButtonStyle.secondary,
            custom_id="room_toggle_hidden",
            callback=toggle_hidden_cb
        )
        
        btn_access_list = self.button(
            label="Доступ",
            style=discord.ButtonStyle.secondary,
            custom_id="room_access_list",
            callback=access_list_cb
        )
        
        btn_back = self.button(
            label="Назад",
            emoji=discord.PartialEmoji(name="left", id=1515638771071324250),
            style=discord.ButtonStyle.secondary,
            custom_id="room_back",
            callback=back_cb
        )
        
        if is_owner:
            return self.build_view(
                f"Управление: {room_name}",
                f"{author.mention}, управление комнатой **{room_name}**\n\n"
                f"> **Статус**: {'Скрыта' if is_hidden else 'Видна всем'}",
                rows=[
                    self.row(btn_give_access, btn_remove_access),
                    self.row(btn_rename, btn_delete),
                    self.row(btn_toggle_hidden, btn_access_list),
                    self.row(btn_back)
                ]
            )
        else:
            return self.build_view(
                f"Комната: {room_name}",
                f"Просмотр комнаты **{room_name}**\n\n"
                f"> **Статус**: {'Скрыта' if is_hidden else 'Видна всем'}",
                rows=[
                    self.row(btn_back)
                ]
            )

    def _success_manage_view(self, author: discord.Member, panel_message: discord.Message, title: str, body: str, back_label: str, back_factory):
        cog = self

        async def back_cb(interaction: discord.Interaction):
            if interaction.user.id != author.id:
                return
            await interaction.response.defer(ephemeral=True)
            await panel_message.edit(view=back_factory(), allowed_mentions=NO_MENTIONS)

        btn_back = self.button(
            label=back_label,
            emoji=discord.PartialEmoji(name="left", id=1515638771071324250),
            style=discord.ButtonStyle.secondary,
            callback=back_cb
        )

        return self.build_view(
            title,
            body,
            rows=[self.row(btn_back)]
        )

    # =====================================================
    # КОМАНДА /apanel
    # =====================================================

    @app_commands.command(name="apanel", description="Панель разработчика.")
    @app_commands.describe(пользователь="Выберите пользователя..")
    @app_commands.guilds(discord.Object(id=guild_id_cmd))
    async def apanel(self, interaction: discord.Interaction, пользователь: discord.Member):
        if not interaction.user.guild_permissions.administrator:
            return await self.respond(
                interaction,
                self.build_view(
                    "Ошибка",
                    "У вас недостаточно прав для использования этой команды. Требуются права администратора."
                ),
                ephemeral=True,
            )

        if пользователь.bot:
            return await self.respond(
                interaction,
                self.build_view(
                    "Ошибка",
                    "Нельзя управлять ботом."
                ),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        panel_message = await interaction.followup.send(
            view=self.build_view(
                "Управление пользователем",
                f"{interaction.user.mention}, **Выберите** операцию для **взаимодействия** с {пользователь.mention}",
            ),
            ephemeral=True,
            allowed_mentions=NO_MENTIONS,
            wait=True,
        )

        await panel_message.edit(
            view=self._main_view(interaction.user, пользователь, panel_message),
            allowed_mentions=NO_MENTIONS
        )

    # =====================================================
    # КОМАНДА /room-manage
    # =====================================================

    @app_commands.command(name="room-manage", description="Управление приватными комнатами.")
    @app_commands.guilds(discord.Object(id=guild_id_cmd))
    async def room_manage(self, interaction: discord.Interaction):
        user_rooms = self.db.get_user_rooms(interaction.user.id)
        
        if not user_rooms:
            return await self.respond(
                interaction,
                self.build_view(
                    "Управление комнатами",
                    "У вас нет созданных приватных комнат."
                ),
                ephemeral=False,
            )
        
        await interaction.response.defer(ephemeral=False)
        
        panel_message = await interaction.followup.send(
            view=self.build_view(
                "Управление комнатами",
                f"{interaction.user.mention}, **выберите** комнату для управления."
            ),
            ephemeral=False,
            allowed_mentions=NO_MENTIONS,
            wait=True,
        )
        
        await panel_message.edit(
            view=self._room_select_view(interaction.user, panel_message),
            allowed_mentions=NO_MENTIONS
        )

    # =====================================================
    # КОМАНДА /top-room
    # =====================================================

    @app_commands.command(name="top-room", description="Топ 5 комнат по времени в голосовом канале.")
    @app_commands.guilds(discord.Object(id=guild_id_cmd))
    async def top_room(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        top_rooms = self.db.get_top_rooms_by_time(limit=5)
        
        if not top_rooms:
            return await self.respond(
                interaction,
                self.build_view(
                    "Топ комнат",
                    "Нет активных комнат для отображения."
                ),
                ephemeral=True,
            )
        
        description_parts = []
        
        for i, room in enumerate(top_rooms, 1):
            room_name = room.get('name', 'Без названия')
            total_time = room.get('total_time', 0)
            owner_id = room.get('owner_id')
            
            owner = interaction.guild.get_member(owner_id)
            owner_name = owner.mention if owner else f"<@{owner_id}>"
            
            room_block = (
                f"**{i}. {room_name}**\n"
                f"<:own:1519386427509571715> Владелец: {owner_name}\n"
                f"<:gg:1519386614885908721> Время: **{format_time(total_time)}**"
            )
            
            description_parts.append(room_block)
        
        full_description = "\n\n---\n\n".join(description_parts)
        
        # Используем аватарку сервера вместо аватарки пользователя
        server_avatar_url = interaction.guild.icon.url if interaction.guild.icon else None
        
        view = self.build_view(
            "<:fire:1519313816486285363> Топ 5 комнат по активности",
            full_description,
            thumbnail_url=server_avatar_url
        )
        
        await interaction.followup.send(
            view=view,
            allowed_mentions=NO_MENTIONS
        )

    # =====================================================
    # КОМАНДА /room-create
    # =====================================================

    @app_commands.command(name="room-create", description="Создать приватную комнату за 1500 монет.")
    @app_commands.guilds(discord.Object(id=guild_id_cmd))
    async def room_create(self, interaction: discord.Interaction):
        """Создание приватной комнаты за 1500 монет"""
        
        room_price = self.settings_prices.get("room_create", 1500)
        balance = self.db.get_balance(interaction.user.id)
        
        if balance < room_price:
            return await self.respond(
                interaction,
                self.build_view(
                    "Ошибка",
                    f"У вас недостаточно монет для создания комнаты.\n"
                    f"Требуется: **{room_price}** {COIN}\n"
                    f"Ваш баланс: **{balance}** {COIN}"
                ),
                ephemeral=True,
            )
        
        await interaction.response.send_modal(
            RoomCreateUserModal(self, interaction.user, room_price)
        )


# =====================================================
# МОДАЛКИ (Административные)
# =====================================================

class BalanceGiveModal(discord.ui.Modal, title="Выдача валюты"):
    def __init__(
        self,
        cog: AdminPanel,
        author: discord.Member,
        member: discord.Member,
        panel_message: discord.Message,
    ):
        super().__init__()
        self.cog = cog
        self.author = author
        self.member = member
        self.panel_message = panel_message

        self.amount_input = discord.ui.TextInput(
            label="Выдать валюту",
            placeholder="Например: 1000",
            min_length=1,
            max_length=15,
            required=True,
        )
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            amount = int(self.amount_input.value)
        except ValueError:
            return await self.cog.respond(
                interaction,
                self.cog.build_view(
                    "Ошибка",
                    "Пожалуйста, введите корректное число."
                ),
                ephemeral=True,
            )

        self.cog.db.give_money(self.member.id, amount)

        view = self.cog._success_view(
            self.author,
            self.member,
            self.panel_message,
            "Выдать валюту",
            f"{self.author.mention}, Вы **успешно выдали** пользователю {self.member.mention}, **{amount}** {COIN}",
            "Вернуться к управлению балансом",
            lambda: self.cog._currency_view(self.author, self.member, self.panel_message),
        )

        await self.panel_message.edit(view=view, allowed_mentions=NO_MENTIONS)


class BalanceRemoveModal(discord.ui.Modal, title="Снятие валюты"):
    def __init__(
        self,
        cog: AdminPanel,
        author: discord.Member,
        member: discord.Member,
        panel_message: discord.Message,
    ):
        super().__init__()
        self.cog = cog
        self.author = author
        self.member = member
        self.panel_message = panel_message

        self.amount_input = discord.ui.TextInput(
            label="Снятие валюты",
            placeholder="Например: 1000",
            min_length=1,
            max_length=15,
            required=True,
        )
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            amount = int(self.amount_input.value)
        except ValueError:
            return await self.cog.respond(
                interaction,
                self.cog.build_view(
                    "Ошибка",
                    "Пожалуйста, введите корректное число."
                ),
                ephemeral=True,
            )

        self.cog.db.take_money(self.member.id, amount)

        view = self.cog._success_view(
            self.author,
            self.member,
            self.panel_message,
            "Снять валюту",
            f"{self.author.mention}, Вы **забрали** у пользователя {self.member.mention}, **{amount}** {COIN}",
            "Вернуться к управлению балансом",
            lambda: self.cog._currency_view(self.author, self.member, self.panel_message),
        )

        await self.panel_message.edit(view=view, allowed_mentions=NO_MENTIONS)


class RoomCreateModal(discord.ui.Modal, title="Создание личной комнаты"):
    def __init__(
        self,
        cog: AdminPanel,
        author: discord.Member,
        member: discord.Member,
        panel_message: discord.Message,
    ):
        super().__init__()
        self.cog = cog
        self.author = author
        self.member = member
        self.panel_message = panel_message

        self.name_input = discord.ui.TextInput(
            label="1. Название комнаты и роли",
            placeholder="Например: Kairox",
            required=True,
        )
        self.color_input = discord.ui.TextInput(
            label="2. Цвет роли",
            placeholder="Например: #FFFFFF",
            required=True,
        )
        self.add_item(self.name_input)
        self.add_item(self.color_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        room_name = self.name_input.value
        colour = _parse_colour(self.color_input.value)

        room_id = self.cog.db.write_new_personal_room(self.member, room_name)

        role = await interaction.guild.create_role(name=room_name)

        sort_role = interaction.guild.get_role(
            self.cog.settings_roles.get("personal_rooms_sort")
        )

        if sort_role:
            await role.edit(
                position=sort_role.position - 1,
                colour=colour,
            )
        else:
            await role.edit(colour=colour)
            
        await self.member.add_roles(role)

        category = interaction.guild.get_channel(
            self.cog.settings_channels.get("personal_rooms_category")
        )
        
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(connect=False, view_channel=False),
            self.member: discord.PermissionOverwrite(connect=True, view_channel=True),
            role: discord.PermissionOverwrite(connect=True, view_channel=True)
        }
        
        voice_channel = await interaction.guild.create_voice_channel(
            room_name,
            category=category,
            overwrites=overwrites
        )
        
        self.cog.db.update_room_channel(room_id, voice_channel.id)

        view = self.cog._success_view(
            self.author,
            self.member,
            self.panel_message,
            "Создание личной комнаты",
            f"{self.author.mention}, Вы **успешно создали** пользователю {self.member.mention} личную комнату {role.mention}\n"
            f"Голосовой канал: {voice_channel.mention}",
            "Вернуться к управлению комнатами",
            lambda: self.cog._rooms_view(self.author, self.member, self.panel_message),
        )

        await self.panel_message.edit(view=view, allowed_mentions=NO_MENTIONS)


# =====================================================
# МОДАЛКА ДЛЯ /room-create (Пользовательская)
# =====================================================

class RoomCreateUserModal(discord.ui.Modal, title="Создание комнаты"):
    def __init__(
        self,
        cog: AdminPanel,
        user: discord.Member,
        price: int,
    ):
        super().__init__()
        self.cog = cog
        self.user = user
        self.price = price

        self.name_input = discord.ui.TextInput(
            label="Название комнаты и роли",
            placeholder="Например: Kairox",
            min_length=1,
            max_length=100,
            required=True,
        )
        self.color_input = discord.ui.TextInput(
            label="Цвет роли (HEX)",
            placeholder="Например: #FF6B6B",
            min_length=6,
            max_length=7,
            required=False,
            default="#FFFFFF"
        )
        self.add_item(self.name_input)
        self.add_item(self.color_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        balance = self.cog.db.get_balance(self.user.id)
        if balance < self.price:
            return await self.cog.respond(
                interaction,
                self.cog.build_view(
                    "Ошибка",
                    f"У вас недостаточно монет для создания комнаты.\n"
                    f"Требуется: **{self.price}** {COIN}\n"
                    f"Ваш баланс: **{balance}** {COIN}"
                ),
                ephemeral=True,
            )

        room_name = self.name_input.value
        
        try:
            colour = _parse_colour(self.color_input.value)
        except ValueError:
            return await self.cog.respond(
                interaction,
                self.cog.build_view(
                    "Ошибка",
                    "Пожалуйста, введите корректный цвет в HEX формате (например: #FF6B6B)."
                ),
                ephemeral=True,
            )

        existing_role = discord.utils.get(interaction.guild.roles, name=room_name)
        if existing_role:
            return await self.cog.respond(
                interaction,
                self.cog.build_view(
                    "Ошибка",
                    f"Роль с названием **{room_name}** уже существует на сервере. Пожалуйста, выберите другое название."
                ),
                ephemeral=True,
            )

        existing_channel = discord.utils.get(interaction.guild.voice_channels, name=room_name)
        if existing_channel:
            return await self.cog.respond(
                interaction,
                self.cog.build_view(
                    "Ошибка",
                    f"Голосовой канал с названием **{room_name}** уже существует на сервере. Пожалуйста, выберите другое название."
                ),
                ephemeral=True,
            )

        self.cog.db.take_money(self.user.id, self.price)

        room_id = self.cog.db.write_new_personal_room(self.user, room_name)

        role = await interaction.guild.create_role(name=room_name)

        sort_role = interaction.guild.get_role(
            self.cog.settings_roles.get("personal_rooms_sort")
        )

        if sort_role:
            await role.edit(
                position=sort_role.position - 1,
                colour=colour,
            )
        else:
            await role.edit(colour=colour)
            
        await self.user.add_roles(role)

        category = interaction.guild.get_channel(
            self.cog.settings_channels.get("personal_rooms_category")
        )
        
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(connect=False, view_channel=False),
            self.user: discord.PermissionOverwrite(connect=True, view_channel=True),
            role: discord.PermissionOverwrite(connect=True, view_channel=True)
        }
        
        voice_channel = await interaction.guild.create_voice_channel(
            room_name,
            category=category,
            overwrites=overwrites
        )
        
        self.cog.db.update_room_channel(room_id, voice_channel.id)

        # Создаем кнопку с серым цветом
        manage_button = self.cog.button(
            label="Управлять комнатой",
            style=discord.ButtonStyle.secondary,
            custom_id="go_to_room_manage"
        )
        
        # Добавляем callback для кнопки
        async def go_to_manage_cb(button_interaction: discord.Interaction):
            if button_interaction.user.id != self.user.id:
                return await button_interaction.response.send_message(
                    "Это не ваша панель управления.", ephemeral=True
                )
            
            await button_interaction.response.defer(ephemeral=False)
            
            user_rooms = self.cog.db.get_user_rooms(self.user.id)
            if not user_rooms:
                return await button_interaction.followup.send(
                    view=self.cog.build_view(
                        "Управление комнатами",
                        "У вас нет созданных приватных комнат."
                    ),
                    ephemeral=False,
                    allowed_mentions=NO_MENTIONS
                )
            
            manage_message = await button_interaction.followup.send(
                view=self.cog.build_view(
                    "Управление комнатами",
                    f"{self.user.mention}, **выберите** комнату для управления."
                ),
                ephemeral=False,
                allowed_mentions=NO_MENTIONS,
                wait=True,
            )
            
            await manage_message.edit(
                view=self.cog._room_select_view(self.user, manage_message),
                allowed_mentions=NO_MENTIONS
            )
        
        manage_button.callback = go_to_manage_cb

        view = self.cog.build_view(
            "Комната создана! <:own:1519386427509571715>",
            f"{self.user.mention}, вы **успешно создали** личную комнату **{room_name}**!\n\n"
            f"<:coin:1515637898735652924> Стоимость: **{self.price}** {COIN}\n"
            f"<:qq:1520114172145307759> Роль: {role.mention}\n"
            f"<:home:1520114245302354060> Канал: {voice_channel.mention}\n\n"
            f"Используйте `/room-manage` для управления комнатой.\n"
            f"Вы можете выдавать доступ другим участникам и настраивать комнату.",
            rows=[
                self.cog.row(manage_button)
            ]
        )

        await interaction.followup.send(
            view=view,
            ephemeral=False,
            allowed_mentions=NO_MENTIONS
        )


# =====================================================
# МОДАЛКИ (Управление комнатами для пользователей)
# =====================================================

class RoomGiveAccessModal(discord.ui.Modal, title="Выдать доступ к комнате"):
    def __init__(
        self,
        cog: AdminPanel,
        author: discord.Member,
        room_id: int,
        room_name: str,
        panel_message: discord.Message,
    ):
        super().__init__()
        self.cog = cog
        self.author = author
        self.room_id = room_id
        self.room_name = room_name
        self.panel_message = panel_message

        self.user_input = discord.ui.TextInput(
            label="Пользователь (юзернейм или ID)",
            placeholder="Например: User или 123456789",
            required=True,
        )
        self.add_item(self.user_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        user_input = self.user_input.value.strip()
        target_user = None
        
        try:
            user_id = int(user_input)
            target_user = interaction.guild.get_member(user_id)
        except ValueError:
            clean_input = user_input.lower()
            
            for member in interaction.guild.members:
                if member.name.lower() == clean_input or member.display_name.lower() == clean_input:
                    target_user = member
                    break
                if str(member).lower() == clean_input:
                    target_user = member
                    break
        
        if not target_user:
            return await self.cog.respond(
                interaction,
                self.cog.build_view(
                    "Ошибка",
                    "Пользователь не найден на сервере. Убедитесь, что вы правильно ввели юзернейм или ID."
                ),
                ephemeral=True,
            )
        
        if target_user.id == self.author.id:
            return await self.cog.respond(
                interaction,
                self.cog.build_view(
                    "Ошибка",
                    "Вы не можете выдать доступ самому себе."
                ),
                ephemeral=True,
            )
        
        room_role = discord.utils.get(interaction.guild.roles, name=self.room_name)
        if not room_role:
            return await self.cog.respond(
                interaction,
                self.cog.build_view(
                    "Ошибка",
                    "Роль комнаты не найдена."
                ),
                ephemeral=True,
            )
        
        room_data = self.cog.db.get_room_by_id(self.room_id)
        if room_data and room_data.get('channel_id'):
            voice_channel = interaction.guild.get_channel(room_data['channel_id'])
            if voice_channel:
                overwrite = voice_channel.overwrites_for(target_user)
                overwrite.connect = True
                overwrite.view_channel = True
                await voice_channel.set_permissions(target_user, overwrite=overwrite)
        
        await target_user.add_roles(room_role)
        self.cog.db.add_room_access(self.room_id, target_user.id)
        
        view = self.cog._success_manage_view(
            self.author,
            self.panel_message,
            "Доступ выдан",
            f"{self.author.mention}, пользователь **{target_user.name}** получил доступ к комнате **{self.room_name}**.",
            "Вернуться к управлению",
            lambda: self.cog._room_manage_view(self.author, self.room_id, self.panel_message)
        )
        
        await self.panel_message.edit(view=view, allowed_mentions=NO_MENTIONS)


class RoomRemoveAccessModal(discord.ui.Modal, title="Забрать доступ к комнате"):
    def __init__(
        self,
        cog: AdminPanel,
        author: discord.Member,
        room_id: int,
        room_name: str,
        panel_message: discord.Message,
    ):
        super().__init__()
        self.cog = cog
        self.author = author
        self.room_id = room_id
        self.room_name = room_name
        self.panel_message = panel_message

        self.user_input = discord.ui.TextInput(
            label="Пользователь (юзернейм или ID)",
            placeholder="Например: User или 123456789",
            required=True,
        )
        self.add_item(self.user_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        user_input = self.user_input.value.strip()
        target_user = None
        
        try:
            user_id = int(user_input)
            target_user = interaction.guild.get_member(user_id)
        except ValueError:
            clean_input = user_input.lower()
            
            for member in interaction.guild.members:
                if member.name.lower() == clean_input or member.display_name.lower() == clean_input:
                    target_user = member
                    break
                if str(member).lower() == clean_input:
                    target_user = member
                    break
        
        if not target_user:
            return await self.cog.respond(
                interaction,
                self.cog.build_view(
                    "Ошибка",
                    "Пользователь не найден на сервере. Убедитесь, что вы правильно ввели юзернейм или ID."
                ),
                ephemeral=True,
            )
        
        if target_user.id == self.author.id:
            return await self.cog.respond(
                interaction,
                self.cog.build_view(
                    "Ошибка",
                    "Вы не можете забрать доступ у самого себя."
                ),
                ephemeral=True,
            )
        
        room_role = discord.utils.get(interaction.guild.roles, name=self.room_name)
        if not room_role:
            return await self.cog.respond(
                interaction,
                self.cog.build_view(
                    "Ошибка",
                    "Роль комнаты не найдена."
                ),
                ephemeral=True,
            )
        
        room_data = self.cog.db.get_room_by_id(self.room_id)
        if room_data and room_data.get('channel_id'):
            voice_channel = interaction.guild.get_channel(room_data['channel_id'])
            if voice_channel:
                overwrite = voice_channel.overwrites_for(target_user)
                overwrite.connect = None
                overwrite.view_channel = None
                await voice_channel.set_permissions(target_user, overwrite=overwrite)
        
        await target_user.remove_roles(room_role)
        self.cog.db.remove_room_access(self.room_id, target_user.id)
        
        view = self.cog._success_manage_view(
            self.author,
            self.panel_message,
            "Доступ забран",
            f"{self.author.mention}, у пользователя **{target_user.name}** забран доступ к комнате **{self.room_name}**.",
            "Вернуться к управлению",
            lambda: self.cog._room_manage_view(self.author, self.room_id, self.panel_message)
        )
        
        await self.panel_message.edit(view=view, allowed_mentions=NO_MENTIONS)


class RoomRenameModal(discord.ui.Modal, title="Изменение комнаты"):
    def __init__(
        self,
        cog: AdminPanel,
        author: discord.Member,
        room_id: int,
        current_name: str,
        panel_message: discord.Message,
    ):
        super().__init__()
        self.cog = cog
        self.author = author
        self.room_id = room_id
        self.current_name = current_name
        self.panel_message = panel_message

        self.name_input = discord.ui.TextInput(
            label="Новое название комнаты и роли",
            placeholder="Например: Kairox",
            default=current_name,
            required=True,
        )
        self.color_input = discord.ui.TextInput(
            label="Новый цвет роли",
            placeholder="Например: #FFFFFF",
            required=False,
        )
        self.add_item(self.name_input)
        self.add_item(self.color_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        new_name = self.name_input.value
        new_colour = None
        
        if self.color_input.value:
            try:
                new_colour = _parse_colour(self.color_input.value)
            except ValueError:
                return await self.cog.respond(
                    interaction,
                    self.cog.build_view(
                        "Ошибка",
                        "Пожалуйста, введите корректный цвет (например: #FFFFFF)."
                    ),
                    ephemeral=True,
                )
        
        old_role = discord.utils.get(interaction.guild.roles, name=self.current_name)
        
        room_data = self.cog.db.get_room_by_id(self.room_id)
        old_channel = None
        if room_data and room_data.get('channel_id'):
            old_channel = interaction.guild.get_channel(room_data['channel_id'])
        
        self.cog.db.update_room_name(self.room_id, new_name)
        
        if old_role:
            await old_role.edit(name=new_name)
            if new_colour:
                await old_role.edit(colour=new_colour)
        
        if old_channel:
            await old_channel.edit(name=new_name)
        
        view = self.cog._success_manage_view(
            self.author,
            self.panel_message,
            "Комната обновлена",
            f"{self.author.mention}, комната **{self.current_name}** переименована в **{new_name}**.",
            "Вернуться к управлению",
            lambda: self.cog._room_manage_view(self.author, self.room_id, self.panel_message)
        )
        
        await self.panel_message.edit(view=view, allowed_mentions=NO_MENTIONS)


# =====================================================
# SETUP
# =====================================================
async def setup(bot: commands.Bot):
    """Функция для загрузки кога"""
    await bot.add_cog(AdminPanel(bot))