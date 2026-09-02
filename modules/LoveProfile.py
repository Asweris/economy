import inspect
import json
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
WARNING_ACCENT = discord.Color.orange().value

DEFAULT_IMAGE_URL = "https://cdn.discordapp.com/attachments/992883178362642453/1029462389130792970/-1.png"


async def maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


class V2Mixin:
    def build_view(self, title, description=None, *, footer=None, rows=None, image_url=None, **kwargs):
        view = discord.ui.LayoutView(timeout=None)
        container = discord.ui.Container()

        container.add_item(discord.ui.TextDisplay(content=f"## {title}"))

        if description:
            container.add_item(discord.ui.TextDisplay(content=description))

        if footer:
            container.add_item(discord.ui.TextDisplay(content=f"-# {footer}"))

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

    async def respond(self, interaction, view, *, ephemeral=False, file=None):
        kwargs = {
            "view": view,
            "ephemeral": ephemeral,
        }
        if file is not None:
            kwargs["file"] = file

        if interaction.response.is_done():
            return await interaction.followup.send(
                **kwargs,
                wait=True,
            )

        return await interaction.response.send_message(
            **kwargs,
        )

    async def edit_original(self, interaction, view, *, attachments=None):
        kwargs = {"view": view}

        if attachments is not None:
            kwargs["attachments"] = [
                attachment for attachment in attachments if attachment is not None
            ]

        return await interaction.edit_original_response(**kwargs)


class LoveProfile(commands.Cog, V2Mixin):

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
            self.settings_channels = data.get("channels") or {}
            self.settings_prices = data.get("prices") or {}

            self.cost_room_change_name = self.settings_prices.get("change_name_love_room")
            self.cost_buy_love_room = self.settings_prices.get("buy_love_room")
            self.cost_marry_create_standart = self.settings_prices.get("marry_create_standart")
            self.cost_marry_create_nonstandart = self.settings_prices.get("marry_create_nonstandart")

            logger.info("Настройки загружены.")

        except Exception as exc:
            logger.error(f"Не можем загрузить настройки: {exc}")
            raise

    @commands.Cog.listener()
    async def on_ready(self):
        self.guild = discord.utils.get(self.bot.guilds, id=self.guild_id)

        if not self.guild:
            logger.error("Гильдия для LoveProfile не найдена.")
            return

        self.marry_role = discord.utils.get(
            self.guild.roles,
            id=self.settings_roles.get("marry_role"),
        )

        if self.marry_role is None:
            logger.warning("Роль marry_role не найдена в настройках!")

        logger.info("/lprofile - start")

    def cog_unload(self):
        close = getattr(self.db, "close", None)
        if close:
            close()

    def no_access_view(self):
        return self.build_view(
            "Ошибка",
            "Эта кнопка не для вас.",
        )

    def error_view(self, title, description):
        return self.build_view(
            title,
            description,
            image_url=DEFAULT_IMAGE_URL,
        )

    def success_view(self, title, description):
        return self.build_view(
            title,
            description,
            image_url=DEFAULT_IMAGE_URL,
        )

    async def resolve_user(self, user_id: int):
        if self.guild:
            member = self.guild.get_member(int(user_id))
            if member:
                return member

            try:
                return await self.guild.fetch_member(int(user_id))
            except Exception:
                pass

        user = self.bot.get_user(int(user_id))
        if user:
            return user

        try:
            return await self.bot.fetch_user(int(user_id))
        except Exception:
            return None

    async def resolve_member(self, user_id: int):
        if not self.guild:
            return None

        member = self.guild.get_member(int(user_id))
        if member:
            return member

        try:
            return await self.guild.fetch_member(int(user_id))
        except Exception:
            return None

    def format_time_spent(self, days):
        total_hours = int(days * 24)

        if total_hours < 24:
            if total_hours == 0:
                return "0ч."
            return f"{total_hours}ч."

        days_count = int(days)
        hours_count = int((days - days_count) * 24)

        if days_count == 0:
            return f"{hours_count}ч."

        if days_count == 1:
            if hours_count == 0:
                return "1д."
            return f"1д.{hours_count}ч."

        if hours_count == 0:
            return f"{days_count}д."

        return f"{days_count}д.{hours_count}ч."

    async def get_profile_text(self, interaction: discord.Interaction, member):
        """Генерация текстового профиля вместо изображения"""
        data = await maybe_await(self.db.get_info_marriege(member))
        if not data:
            return None

        partner_1 = await self.resolve_user(int(data[1]))
        partner_2 = await self.resolve_user(int(data[2]))

        if not partner_1 or not partner_2:
            return None

        if member and member.id == partner_1.id:
            user = partner_1
            partner = partner_2
        elif member and member.id == partner_2.id:
            user = partner_2
            partner = partner_1
        elif interaction.user.id == partner_1.id:
            user = partner_1
            partner = partner_2
        else:
            user = partner_2
            partner = partner_1

        reg_date = datetime.fromtimestamp(int(data[4]))
        reg_days = (datetime.now() - reg_date).total_seconds() / 86400
        end = reg_date + timedelta(days=30)

        love_room_data = await maybe_await(self.db.get_data_loveRoom(member))
        voice_hours = love_room_data.get("total_hours", 0) if love_room_data else 0

        time_spent = self.format_time_spent(reg_days)
        balance = str(data[3])

        # Формируем текстовый профиль
        profile_text = f"""## Любовный профиль
### {user.display_name} ❤️ {partner.display_name}

**Участники:**
• {user.mention} 
• {partner.mention}

**Время вместе:** {time_spent}
**Дата обновления:** {end.day:02}.{end.month:02}.{end.year}

**Голосовых часов:** {voice_hours}ч.
**Баланс пары:** {balance} {COIN}

---

*Для управления профилем используйте кнопки ниже*"""

        return profile_text

    async def refresh_profile_message(self, root_interaction: discord.Interaction):
        """Обновление текстового профиля"""
        profile_text = await self.get_profile_text(root_interaction, root_interaction.user)

        if not profile_text:
            return await self.edit_original(
                root_interaction,
                self.error_view("Ошибка", "Не удалось получить данные любовного профиля."),
                attachments=[],
            )

        await self.edit_original(
            root_interaction,
            await self.main_profile_view(root_interaction, profile_text),
            attachments=[],
        )

    def profile_only_view(self, member, partner, profile_text):
        return self.build_view(
            profile_text,
            image_url=None,
        )

    async def main_profile_view(self, root_interaction: discord.Interaction, profile_text=None):
        """Основной вид профиля с кнопками управления"""
        if profile_text is None:
            profile_text = await self.get_profile_text(root_interaction, root_interaction.user)
            
        if not profile_text:
            return self.error_view("Ошибка", "Не удалось получить данные профиля.")

        async def add_balance(button_interaction: discord.Interaction):
            if button_interaction.user.id != root_interaction.user.id:
                return await self.respond(
                    button_interaction,
                    self.no_access_view(),
                    ephemeral=True,
                )

            await button_interaction.response.send_modal(
                AddBalanceModal(self, root_interaction)
            )

        async def settings(button_interaction: discord.Interaction):
            await button_interaction.response.defer()

            if button_interaction.user.id != root_interaction.user.id:
                return await button_interaction.followup.send(
                    view=self.no_access_view(),
                    ephemeral=True,
                )

            await root_interaction.edit_original_response(
                attachments=[],
                view=self.settings_marry_view(root_interaction),
            )

        async def divorce(button_interaction: discord.Interaction):
            await button_interaction.response.defer()

            if button_interaction.user.id != root_interaction.user.id:
                return await button_interaction.followup.send(
                    view=self.no_access_view(),
                    ephemeral=True,
                )

            await self.handle_divorce(root_interaction, button_interaction)

        return self.build_view(
            profile_text,
            image_url=None,
            rows=[
                [
                    self.button("Пополнить баланс", callback=add_balance, custom_id="love_balance_add"),
                    self.button("Настройки", callback=settings, custom_id="love_settings"),
                    self.button("Развестись", callback=divorce, custom_id="love_divorce"),
                ]
            ],
        )

    def settings_marry_view(self, root_interaction: discord.Interaction):
        async def back(button_interaction: discord.Interaction):
            await button_interaction.response.defer()

            if button_interaction.user.id != root_interaction.user.id:
                return await button_interaction.followup.send(
                    view=self.no_access_view(),
                    ephemeral=True,
                )

            await self.refresh_profile_message(root_interaction)

        async def room_settings(button_interaction: discord.Interaction):
            await button_interaction.response.defer()

            if button_interaction.user.id != root_interaction.user.id:
                return await button_interaction.followup.send(
                    view=self.no_access_view(),
                    ephemeral=True,
                )

            love_room_data = await maybe_await(self.db.get_data_loveRoom(root_interaction.user))

            if not love_room_data or not love_room_data.get("bought", False):
                return await root_interaction.edit_original_response(
                    attachments=[],
                    view=self.buy_love_room_view(root_interaction),
                )

            await root_interaction.edit_original_response(
                attachments=[],
                view=self.room_settings_view(root_interaction),
            )

        return self.build_view(
            "Настройки пары",
            "**Выберите** раздел настроек, который хотите открыть.",
            rows=[
                [
                    self.button("Назад", callback=back, custom_id="love_settings_back"),
                    self.button("Настройки комнаты", callback=room_settings, custom_id="love_room_settings"),
                ]
            ],
        )

    def buy_love_room_view(self, root_interaction: discord.Interaction):
        async def buy(button_interaction: discord.Interaction):
            await button_interaction.response.defer()

            if button_interaction.user.id != root_interaction.user.id:
                return await button_interaction.followup.send(
                    view=self.no_access_view(),
                    ephemeral=True,
                )

            await self.handle_buy_love_room(root_interaction, button_interaction)

        async def back(button_interaction: discord.Interaction):
            await button_interaction.response.defer()

            if button_interaction.user.id != root_interaction.user.id:
                return await button_interaction.followup.send(
                    view=self.no_access_view(),
                    ephemeral=True,
                )

            await root_interaction.edit_original_response(
                attachments=[],
                view=self.settings_marry_view(root_interaction),
            )

        return self.build_view(
            "Любовная комната",
            f"У вас ещё нет **Любовной комнаты**.\n\n"
            f"**Стоимость покупки:** **{self.cost_buy_love_room}** {COIN}",
            image_url=DEFAULT_IMAGE_URL,
            rows=[
                [
                    self.button("Купить комнату", callback=buy, custom_id="love_room_buy"),
                    self.button("Назад", callback=back, custom_id="love_room_buy_back"),
                ]
            ],
        )

    async def handle_buy_love_room(
        self,
        root_interaction: discord.Interaction,
        button_interaction: discord.Interaction,
    ):
        balance = int(await maybe_await(self.db.get_balance_marry(root_interaction.user)) or 0)
        cost = int(self.cost_buy_love_room or 0)

        if balance < cost:
            return await button_interaction.followup.send(
                view=self.error_view(
                    "Недостаточно средств",
                    f"Вам не хватает **{cost - balance}** {COIN} для покупки комнаты!",
                ),
                ephemeral=True,
            )

        try:
            data = await maybe_await(self.db.get_info_marriege(root_interaction.user))
            if not data:
                return await button_interaction.followup.send(
                    view=self.error_view("Ошибка", "Информация о браке не найдена."),
                    ephemeral=True,
                )

            partner_1 = await self.resolve_member(int(data[1]))
            partner_2 = await self.resolve_member(int(data[2]))

            if not partner_1 or not partner_2:
                return await button_interaction.followup.send(
                    view=self.error_view("Ошибка", "Не удалось найти участников пары на сервере."),
                    ephemeral=True,
                )

            bitrates = [96000, 128000, 256000, 384000]
            bitrate = bitrates[self.guild.premium_tier]

            channel_name = f"{partner_1.display_name} ❤️ {partner_2.display_name}"

            overwrites = {
                self.guild.default_role: discord.PermissionOverwrite(connect=False, view_channel=False),
                partner_1: discord.PermissionOverwrite(connect=True, view_channel=True),
                partner_2: discord.PermissionOverwrite(connect=True, view_channel=True),
            }

            love_category_id = self.settings_channels.get("love_category")
            love_category = discord.utils.get(self.guild.channels, id=love_category_id)

            channel = await self.guild.create_voice_channel(
                channel_name,
                bitrate=bitrate,
                overwrites=overwrites,
                category=love_category,
            )

            await maybe_await(self.db.deduct_balance_and_update_date(root_interaction.user.id, cost))
            await maybe_await(self.db.write_data_loveRoom(root_interaction.user, "bought", True))
            await maybe_await(self.db.write_data_loveRoom(partner_1, "id", channel.id))
            await maybe_await(self.db.write_data_loveRoom(partner_2, "id", channel.id))

            await button_interaction.followup.send(
                view=self.success_view(
                    "Поздравляем!",
                    f"Вы успешно приобрели **Любовную комнату** за **{cost}** {COIN}.",
                ),
                ephemeral=True,
            )

            await root_interaction.edit_original_response(
                attachments=[],
                view=self.settings_marry_view(root_interaction),
            )

        except Exception as exc:
            logger.error(f"Ошибка при создании Love Room: {exc}")

            await button_interaction.followup.send(
                view=self.error_view("Ошибка", "Не удалось создать комнату. Попробуйте позже."),
                ephemeral=True,
            )

    def room_settings_view(self, root_interaction: discord.Interaction):
        async def back(button_interaction: discord.Interaction):
            await button_interaction.response.defer()

            if button_interaction.user.id != root_interaction.user.id:
                return await button_interaction.followup.send(
                    view=self.no_access_view(),
                    ephemeral=True,
                )

            await root_interaction.edit_original_response(
                attachments=[],
                view=self.settings_marry_view(root_interaction),
            )

        async def change_name(button_interaction: discord.Interaction):
            if button_interaction.user.id != root_interaction.user.id:
                return await self.respond(
                    button_interaction,
                    self.no_access_view(),
                    ephemeral=True,
                )

            await button_interaction.response.send_modal(
                ChangeLoveRoomNameModal(self, root_interaction)
            )

        async def reset_name(button_interaction: discord.Interaction):
            await button_interaction.response.defer()

            if button_interaction.user.id != root_interaction.user.id:
                return await button_interaction.followup.send(
                    view=self.no_access_view(),
                    ephemeral=True,
                )

            await self.handle_reset_room_name(root_interaction, button_interaction)

        async def toggle_hide(button_interaction: discord.Interaction):
            await button_interaction.response.defer()

            if button_interaction.user.id != root_interaction.user.id:
                return await button_interaction.followup.send(
                    view=self.no_access_view(),
                    ephemeral=True,
                )

            await self.handle_toggle_room_visibility(root_interaction, button_interaction)

        async def delete_room(button_interaction: discord.Interaction):
            await button_interaction.response.defer()

            if button_interaction.user.id != root_interaction.user.id:
                return await button_interaction.followup.send(
                    view=self.no_access_view(),
                    ephemeral=True,
                )

            await self.show_delete_room_confirm(root_interaction, button_interaction)

        return self.build_view(
            "Настройки любовной комнаты",
            "**Выберите** действие для управления вашей любовной комнатой.",
            rows=[
                [
                    self.button("Назад", callback=back, custom_id="love_room_back"),
                    self.button("Изменить название", callback=change_name, custom_id="love_room_rename"),
                ],
                [
                    self.button("Сбросить название", callback=reset_name, custom_id="love_room_reset_name"),
                    self.button("Скрыть/Показать", callback=toggle_hide, custom_id="love_room_toggle"),
                ],
                [
                    self.button("Удалить комнату", callback=delete_room, custom_id="love_room_delete"),
                ],
            ],
        )

    async def handle_reset_room_name(
        self,
        root_interaction: discord.Interaction,
        button_interaction: discord.Interaction,
    ):
        love_room_data = await maybe_await(self.db.get_data_loveRoom(root_interaction.user))
        data = await maybe_await(self.db.get_info_marriege(root_interaction.user))

        if not love_room_data or not data:
            return await button_interaction.followup.send(
                view=self.error_view("Ошибка", "Данные любовной комнаты не найдены."),
                ephemeral=True,
            )

        partner_1 = await self.resolve_user(int(data[1]))
        partner_2 = await self.resolve_user(int(data[2]))

        if not partner_1 or not partner_2:
            return await button_interaction.followup.send(
                view=self.error_view("Ошибка", "Не удалось найти участников пары."),
                ephemeral=True,
            )

        default_name = f"{partner_1.display_name} ❤️ {partner_2.display_name}"

        await maybe_await(self.db.write_data_loveRoom(root_interaction.user, "name", 0))

        love_room_voice = self.guild.get_channel(love_room_data.get("id"))
        if love_room_voice:
            await love_room_voice.edit(name=default_name)

        await button_interaction.followup.send(
            view=self.success_view(
                "Название любовной комнаты",
                f"Вы успешно **сбросили название** любовной комнаты.\n\n"
                f"Новое название: **{default_name}**",
            ),
            ephemeral=True,
        )

    async def handle_toggle_room_visibility(
        self,
        root_interaction: discord.Interaction,
        button_interaction: discord.Interaction,
    ):
        love_room_data = await maybe_await(self.db.get_data_loveRoom(root_interaction.user))

        if not love_room_data or not love_room_data.get("id"):
            return await button_interaction.followup.send(
                view=self.error_view("Ошибка", "У вас нет активной любовной комнаты."),
                ephemeral=True,
            )

        love_room_voice = self.guild.get_channel(love_room_data.get("id"))

        if not love_room_voice:
            return await button_interaction.followup.send(
                view=self.error_view("Ошибка", "Канал любовной комнаты не найден."),
                ephemeral=True,
            )

        old_overwrites = love_room_voice.overwrites_for(self.guild.default_role)
        overwrite = discord.PermissionOverwrite()

        if old_overwrites.view_channel:
            overwrite.view_channel = False
            await love_room_voice.set_permissions(self.guild.default_role, overwrite=overwrite)

            title = "Изменение любовной комнаты"
            description = "Вы успешно **скрыли** вашу комнату."
        else:
            overwrite.view_channel = True
            await love_room_voice.set_permissions(self.guild.default_role, overwrite=overwrite)

            title = "Изменение любовной комнаты"
            description = "Вы успешно **показали** вашу комнату для всех!"

        await button_interaction.followup.send(
            view=self.success_view(title, description),
            ephemeral=True,
        )

    async def show_delete_room_confirm(
        self,
        root_interaction: discord.Interaction,
        button_interaction: discord.Interaction,
    ):
        love_room_data = await maybe_await(self.db.get_data_loveRoom(root_interaction.user))

        if not love_room_data or not love_room_data.get("id"):
            return await button_interaction.followup.send(
                view=self.error_view("Ошибка", "У вас нет активной любовной комнаты для удаления!"),
                ephemeral=True,
            )

        delete_message = None

        async def confirm(confirm_interaction: discord.Interaction):
            await confirm_interaction.response.defer()

            if confirm_interaction.user.id != root_interaction.user.id:
                return await confirm_interaction.followup.send(
                    view=self.no_access_view(),
                    ephemeral=True,
                )

            love_room_voice = self.guild.get_channel(love_room_data.get("id"))

            if love_room_voice:
                await love_room_voice.delete()

            await maybe_await(self.db.write_data_loveRoom(root_interaction.user, "id", 0))

            if delete_message:
                await delete_message.edit(
                    view=self.success_view(
                        "Удаление комнаты",
                        "Ваша любовная комната успешно удалена.\n\n"
                        "Чтобы создать новую, зайдите в комнату входа.",
                    )
                )

            await root_interaction.edit_original_response(
                attachments=[],
                view=self.room_settings_view(root_interaction),
            )

        async def cancel(cancel_interaction: discord.Interaction):
            await cancel_interaction.response.defer()

            if cancel_interaction.user.id != root_interaction.user.id:
                return await cancel_interaction.followup.send(
                    view=self.no_access_view(),
                    ephemeral=True,
                )

            if delete_message:
                await delete_message.delete()

        delete_message = await button_interaction.followup.send(
            view=self.build_view(
                "Подтверждение удаления",
                "Вы уверены, что хотите **удалить** вашу любовную комнату?\n\n"
                "**Это действие невозможно отменить.**",
                image_url=DEFAULT_IMAGE_URL,
                rows=[
                    [
                        self.button("Удалить", callback=confirm, custom_id="love_room_delete_confirm", style=discord.ButtonStyle.danger),
                        self.button("Отмена", callback=cancel, custom_id="love_room_delete_cancel"),
                    ]
                ],
            ),
            ephemeral=True,
            wait=True,
        )

    async def handle_divorce(
        self,
        root_interaction: discord.Interaction,
        button_interaction: discord.Interaction,
    ):
        if self.marry_role is None:
            return await button_interaction.followup.send(
                view=self.error_view("Ошибка", "Роль для брака не настроена!"),
                ephemeral=True,
            )

        data = await maybe_await(self.db.get_info_marriege(root_interaction.user))

        if not data:
            return await button_interaction.followup.send(
                view=self.error_view("Ошибка", "Информация о браке не найдена."),
                ephemeral=True,
            )

        partner_1 = await self.resolve_member(int(data[1]))
        partner_2 = await self.resolve_member(int(data[2]))

        love_room_data = await maybe_await(self.db.get_data_loveRoom(root_interaction.user))

        if love_room_data and love_room_data.get("id", 0) != 0:
            love_room_voice = self.guild.get_channel(love_room_data.get("id"))

            if love_room_voice:
                try:
                    await love_room_voice.delete()
                    logger.info(f"Удалена любовная комната {love_room_voice.name} при разводе")
                except Exception as exc:
                    logger.error(f"Ошибка при удалении комнаты: {exc}")

        await maybe_await(self.db.divorce_marriege(data[1], data[2]))

        if partner_1 and self.marry_role:
            try:
                await partner_1.remove_roles(self.marry_role)
            except Exception as exc:
                logger.error(f"Ошибка при снятии роли с {partner_1.name}: {exc}")

        if partner_2 and self.marry_role:
            try:
                await partner_2.remove_roles(self.marry_role)
            except Exception as exc:
                logger.error(f"Ошибка при снятии роли с {partner_2.name}: {exc}")

        if partner_1 and partner_2:
            await maybe_await(self.db.write_log_in_history(partner_1, partner_2, "divorce"))

        initiator = root_interaction.user

        dm_view = self.build_view(
            "Расторжение брака",
            f"Ваш брак был расторгнут по инициативе {initiator.mention}.",
            image_url=DEFAULT_IMAGE_URL,
        )

        try:
            if partner_1 and initiator.id == partner_2.id:
                await partner_1.send(view=dm_view)
            elif partner_2 and initiator.id == partner_1.id:
                await partner_2.send(view=dm_view)
        except Exception:
            pass

        await button_interaction.followup.send(
            view=self.success_view(
                "Расторжение брака",
                "Вы успешно развелись.",
            ),
            ephemeral=True,
        )

        try:
            await root_interaction.delete_original_response()
        except Exception:
            pass

    @app_commands.command(name="lprofile", description="Любовный профиль.")
    @app_commands.describe(пользователь="Выберите пользователя.")
    @app_commands.guilds(discord.Object(id=guild_id_cmd))
    async def lprofile(
        self,
        interaction: discord.Interaction,
        пользователь: discord.Member | None = None,
    ):
        target = пользователь or interaction.user

        if not await maybe_await(self.db.is_marry(target.id)):
            if пользователь:
                return await self.respond(
                    interaction,
                    self.build_view(
                        "Любовный профиль",
                        "Этот человек ещё не состоит в браке!\n\n"
                        "Может это твоя судьба?",
                        image_url=DEFAULT_IMAGE_URL,
                    ),
                    ephemeral=True,
                )

            return await self.respond(
                interaction,
                self.build_view(
                    "Любовный профиль",
                    f"У вас отсутствует пара!\n\n"
                    f"Для её создания используйте команду: `/marry @пользователь`.\n"
                    f"Стоимость создания пары — **{self.cost_marry_create_standart}** {COIN}",
                    image_url=DEFAULT_IMAGE_URL,
                ),
                ephemeral=True,
            )

        await interaction.response.defer()

        profile_text = await self.get_profile_text(interaction, target)

        if not profile_text:
            return await interaction.followup.send(
                view=self.error_view("Ошибка", "Не удалось сгенерировать профиль."),
                ephemeral=True,
            )

        if пользователь:
            data = await maybe_await(self.db.get_info_marriege(target))
            partner_1 = await self.resolve_user(int(data[1]))
            partner_2 = await self.resolve_user(int(data[2]))
            
            if target.id == partner_1.id:
                partner = partner_2
            else:
                partner = partner_1
                
            return await interaction.followup.send(
                view=self.profile_only_view(target, partner, profile_text),
            )

        await interaction.followup.send(
            view=await self.main_profile_view(interaction, profile_text),
        )


class AddBalanceModal(discord.ui.Modal):
    def __init__(self, cog: LoveProfile, root_interaction: discord.Interaction):
        super().__init__(title="Пополнение баланса пары")

        self.cog = cog
        self.root_interaction = root_interaction

        self.amount_input = discord.ui.TextInput(
            label="Введите сумму пополнения",
            placeholder="100",
            required=True,
            min_length=1,
            max_length=10,
        )

        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            amount = int(str(self.amount_input.value).strip())

            if amount <= 0:
                raise ValueError
        except Exception:
            return await interaction.followup.send(
                view=self.cog.error_view(
                    "Пополнение баланса пары",
                    "Введите корректную сумму пополнения.",
                ),
                ephemeral=True,
            )

        await maybe_await(self.cog.db.give_balance_marry(self.root_interaction.user, amount))

        await self.cog.refresh_profile_message(self.root_interaction)

        await interaction.followup.send(
            view=self.cog.success_view(
                "Пополнение баланса пары",
                f"Вы успешно пополнили баланс пары на **{amount}** {COIN}.",
            ),
            ephemeral=True,
        )


class ChangeLoveRoomNameModal(discord.ui.Modal):
    def __init__(self, cog: LoveProfile, root_interaction: discord.Interaction):
        super().__init__(title="Название любовной комнаты")

        self.cog = cog
        self.root_interaction = root_interaction

        self.name_input = discord.ui.TextInput(
            label="Новое название",
            placeholder="Введите новое название комнаты",
            required=True,
            min_length=1,
            max_length=100,
        )

        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        new_name = str(self.name_input.value).strip()

        if not new_name:
            return await interaction.followup.send(
                view=self.cog.error_view(
                    "Название любовной комнаты",
                    "Введите корректное название комнаты.",
                ),
                ephemeral=True,
            )

        confirm_message = None

        async def yes(button_interaction: discord.Interaction):
            await button_interaction.response.defer()

            if button_interaction.user.id != self.root_interaction.user.id:
                return await button_interaction.followup.send(
                    view=self.cog.no_access_view(),
                    ephemeral=True,
                )

            await self.apply_new_name(button_interaction, new_name, confirm_message)

        async def no(button_interaction: discord.Interaction):
            await button_interaction.response.defer()

            if button_interaction.user.id != self.root_interaction.user.id:
                return await button_interaction.followup.send(
                    view=self.cog.no_access_view(),
                    ephemeral=True,
                )

            if confirm_message:
                await confirm_message.delete()

        confirm_message = await interaction.followup.send(
            view=self.cog.build_view(
                "Название любовной комнаты",
                f"Вы уверены, что хотите установить **{new_name}** новым названием вашей любовной комнаты?\n\n"
                f"Стоимость изменения: **{self.cog.cost_room_change_name}** {COIN}",
                image_url=DEFAULT_IMAGE_URL,
                rows=[
                    [
                        self.cog.button("Да", callback=yes, custom_id="love_room_rename_yes", style=discord.ButtonStyle.success),
                        self.cog.button("Нет", callback=no, custom_id="love_room_rename_no", style=discord.ButtonStyle.danger),
                    ]
                ],
            ),
            ephemeral=True,
            wait=True,
        )

    async def apply_new_name(
        self,
        interaction: discord.Interaction,
        new_name: str,
        confirm_message,
    ):
        love_room_data = await maybe_await(self.cog.db.get_data_loveRoom(self.root_interaction.user))
        data = await maybe_await(self.cog.db.get_info_marriege(self.root_interaction.user))

        if not love_room_data or not data:
            return await interaction.followup.send(
                view=self.cog.error_view("Ошибка", "Данные любовной комнаты не найдены."),
                ephemeral=True,
            )

        balance = int(await maybe_await(self.cog.db.get_balance_marry(self.root_interaction.user)) or 0)
        cost = int(self.cog.cost_room_change_name or 0)

        if balance < cost:
            if confirm_message:
                return await confirm_message.edit(
                    view=self.cog.error_view(
                        "Упс...",
                        "У вас недостаточно средств! Для начала пополните баланс пары.",
                    )
                )

            return

        partner_1 = await self.cog.resolve_user(int(data[1]))
        partner_2 = await self.cog.resolve_user(int(data[2]))

        if not partner_1 or not partner_2:
            return await interaction.followup.send(
                view=self.cog.error_view("Ошибка", "Не удалось найти участников пары."),
                ephemeral=True,
            )

        old_name = love_room_data.get("name")

        if old_name == 0 or old_name is None:
            old_name = f"{partner_1.display_name} ❤️ {partner_2.display_name}"

        love_room_voice = self.cog.guild.get_channel(love_room_data.get("id"))

        if not love_room_voice:
            if confirm_message:
                return await confirm_message.edit(
                    view=self.cog.error_view(
                        "Ошибка",
                        "Канал любовной комнаты не найден.",
                    )
                )

            return

        await love_room_voice.edit(name=new_name)
        await maybe_await(self.cog.db.write_data_loveRoom(self.root_interaction.user, "name", str(new_name)))
        
        await maybe_await(self.cog.db.deduct_balance_and_update_date(self.root_interaction.user.id, cost))
        
        await self.cog.refresh_profile_message(self.root_interaction)

        if confirm_message:
            await confirm_message.edit(
                view=self.cog.success_view(
                    "Название любовной комнаты",
                    f"Вы успешно изменили название вашей любовной комнаты.\n\n"
                    f"**Старое название:** {old_name}\n"
                    f"**Новое название:** {new_name}",
                )
            )


async def setup(bot: commands.Bot):
    """Функция для загрузки кога"""
    await bot.add_cog(LoveProfile(bot))
