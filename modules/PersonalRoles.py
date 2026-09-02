from __future__ import annotations

import json
import asyncio
import inspect
import aiohttp
from datetime import datetime, timedelta
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from modules.Database import Database
from modules.Logger import *
from modules.Utils import Utils


guild_id_cmd = Utils.get_guild_id()
COIN = "<:coin:1515637898735652924>"
ACCENT = 0x2F3136
DEFAULT_PERSONAL_ROLE_CATEGORY_ID = 1503488547821322340


async def maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def parse_colour(value: str) -> discord.Colour:
    value = value.strip()
    if not value.startswith("#"):
        value = f"#{value}"
    if len(value) != 7:
        raise ValueError("Invalid HEX color")
    return discord.Colour(int(value[1:], 16))


def parse_gradient(value: str) -> tuple:
    """Парсит градиент из строки вида #FFFFFF-#000000"""
    value = value.strip()
    colors = value.split("-")
    parsed = []
    for color in colors:
        color = color.strip()
        if not color.startswith("#"):
            color = f"#{color}"
        if len(color) != 7:
            raise ValueError("Invalid HEX color in gradient")
        parsed.append(discord.Colour(int(color[1:], 16)))
    if len(parsed) < 2:
        raise ValueError("Gradient needs at least 2 colors")
    return tuple(parsed)


def parse_gradient_hex(value: str) -> tuple:
    """Парсит градиент и возвращает HEX строки"""
    value = value.strip()
    colors = value.split("-")
    parsed = []
    for color in colors:
        color = color.strip()
        if not color.startswith("#"):
            color = f"#{color}"
        if len(color) != 7:
            raise ValueError("Invalid HEX color in gradient")
        parsed.append(color)
    if len(parsed) < 2:
        raise ValueError("Gradient needs at least 2 colors")
    return tuple(parsed)


def clamp_text(value, limit=3800):
    value = "" if value is None else str(value)
    return value if len(value) <= limit else value[: limit - 3] + "..."


async def download_image(url: str) -> bytes:
    """Скачивает изображение по URL и возвращает байты"""
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.read()
            raise Exception(f"Failed to download image: {response.status}")


async def set_role_icon(role: discord.Role, image_data: bytes) -> bool:
    """Устанавливает значок роли с обработкой разных версий Discord.py"""
    try:
        try:
            await role.edit(icon=image_data)
            return True
        except TypeError:
            try:
                await role.edit(display_icon=image_data)
                return True
            except TypeError:
                try:
                    await role.edit(**{"icon": image_data})
                    return True
                except:
                    try:
                        await role.edit(**{"display_icon": image_data})
                        return True
                    except Exception as e:
                        logger.error(f"Не удалось установить значок: {e}")
                        return False
    except Exception as e:
        logger.error(f"Ошибка при установке значка: {e}")
        return False


class V2Mixin:
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
                container.add_item(row_items)

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
            return await interaction.followup.send(view=view, ephemeral=ephemeral, wait=True, allowed_mentions=discord.AllowedMentions.none())
        return await interaction.response.send_message(view=view, ephemeral=ephemeral, allowed_mentions=discord.AllowedMentions.none())

    async def edit_original(self, interaction, view):
        return await interaction.edit_original_response(view=view)


class PersonalRoles(commands.Cog, V2Mixin):
    role = app_commands.Group(
        name="role",
        description="Управление личными ролями",
        guild_ids=[guild_id_cmd],
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database()

        try:
            settings_path = Path(__file__).with_name("settings.json")
            if not settings_path.exists():
                settings_path = Path("./assets/settings.json")

            with open(settings_path, "r", encoding="utf8") as settings:
                data = json.load(settings)

            self.settings_roles = data.get("roles") or {}
            self.settings_prices = data.get("prices") or {}

            self.cost_role_create = self.settings_prices.get("role_create")
            self.cost_role_change_name = self.settings_prices.get("role_change_name")
            self.cost_role_change_color = self.settings_prices.get("role_change_color")
            self.cost_role_rent = self.settings_prices.get("role_rent", 500)

            self.personal_role_category_id = (
                self.settings_roles.get("personal_role_category")
                or self.settings_roles.get("personal_roles_sort")
                or DEFAULT_PERSONAL_ROLE_CATEGORY_ID
            )

            self.personal_roles_category_id = self.settings_roles.get("personal_roles_category")

            logger.info(f"Настройки загружены. personal_role_category ID: {self.personal_role_category_id}")
        except Exception as exc:
            logger.error(f"Не можем загрузить настройки: {exc}")
            raise

        self.guild = None
        self.personal_roles_sort = None
        self.rental_task = None
        self.waiting_for_icon = {}
        self.icon_timeout_tasks = {}

    @commands.Cog.listener()
    async def on_ready(self):
        self.guild = discord.utils.get(self.bot.guilds, id=guild_id_cmd)
        if not self.guild:
            logger.error("Гильдия для личных ролей не найдена.")
            return

        self.personal_roles_sort = discord.utils.get(
            self.guild.roles,
            id=int(self.personal_role_category_id),
        )

        if self.personal_roles_sort is None:
            logger.error(f"❌ Роль personal_role_category с ID {self.personal_role_category_id} НЕ НАЙДЕНА!")
            logger.warning("Личные роли будут создаваться внизу списка")
        else:
            logger.info(f"✅ Роль personal_role_category найдена: {self.personal_roles_sort.name} (ID: {self.personal_roles_sort.id})")
            logger.info(f"📊 Позиция роли: {self.personal_roles_sort.position}")

        logger.info("/role create - start")
        logger.info("/role manage - start")
        logger.info("/role sell - start")
        logger.info("/role unsell - start")
        logger.info("/role auto_rent - start")

        if self.rental_task is None or self.rental_task.done():
            self.rental_task = self.bot.loop.create_task(self.check_role_rentals())

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Слушатель для обработки файлов значка"""
        if message.author.bot:
            return
            
        if message.author.id in self.waiting_for_icon:
            data = self.waiting_for_icon[message.author.id]
            role_id = data["role_id"]
            root_interaction = data["root_interaction"]
            
            if not message.attachments:
                await message.delete()
                await message.channel.send(
                    view=self.build_view(
                        "Ошибка",
                        "Файл не найден! Отправьте изображение."
                    ),
                    delete_after=10,
                    allowed_mentions=discord.AllowedMentions.none()
                )
                return
            
            attachment = message.attachments[0]
            
            if not attachment.content_type or not attachment.content_type.startswith("image/"):
                await message.delete()
                await message.channel.send(
                    view=self.build_view(
                        "Ошибка",
                        "Это не изображение! Отправьте файл изображения (PNG, JPG, GIF и т.д.)."
                    ),
                    delete_after=10,
                    allowed_mentions=discord.AllowedMentions.none()
                )
                return
            
            try:
                image_data = await download_image(attachment.url)
                role = discord.utils.get(self.guild.roles, id=role_id)
                
                if role:
                    success = await set_role_icon(role, image_data)
                    if success:
                        await maybe_await(self.db.set_role_icon(role_id, attachment.url))
                    else:
                        await maybe_await(self.db.set_role_icon(role_id, attachment.url))
                        logger.warning(f"Значок не установлен на роль, но URL сохранен в базу")
                    
                try:
                    await message.delete()
                except Exception:
                    pass
                
                if message.author.id in self.icon_timeout_tasks:
                    self.icon_timeout_tasks[message.author.id].cancel()
                    del self.icon_timeout_tasks[message.author.id]
                
                del self.waiting_for_icon[message.author.id]
                
                if role:
                    role_created_at = f"{role.created_at.day:02}.{role.created_at.month:02}.{role.created_at.year}"
                    await self.edit_original(
                        root_interaction,
                        await self.role_manage_view(root_interaction, role, role_created_at)
                    )
                    
                    await message.channel.send(
                        view=self.build_view(
                            "Значок установлен",
                            f"Значок для роли {role.mention} успешно установлен!"
                        ),
                        delete_after=10,
                        allowed_mentions=discord.AllowedMentions.none()
                    )
            except Exception as e:
                logger.error(f"Ошибка при установке значка: {e}")
                await message.channel.send(
                    view=self.build_view(
                        "Ошибка",
                        f"Не удалось установить значок: {str(e)}"
                    ),
                    delete_after=10,
                    allowed_mentions=discord.AllowedMentions.none()
                )

    def cog_unload(self):
        if self.rental_task:
            self.rental_task.cancel()
        close = getattr(self.db, "close", None)
        if close:
            close()

    async def get_role_position(self, guild: discord.Guild | None = None):
        """Получает позицию прямо под ролью-сортировкой личных ролей."""
        guild = guild or self.guild
        if not guild:
            return None

        sort_role = guild.get_role(int(self.personal_role_category_id))
        if sort_role is None:
            logger.warning(f"Роль для сортировки личных ролей {self.personal_role_category_id} не найдена")
            return None

        self.personal_roles_sort = sort_role
        return max(sort_role.position - 1, 1)

    async def move_role_under_sort_role(self, guild: discord.Guild, role: discord.Role) -> bool:
        """Перемещает личную роль прямо под роль-сортировку."""
        position = await self.get_role_position(guild)
        if position is None:
            logger.warning("Не удалось определить позицию для роли")
            return False

        try:
            await guild.edit_role_positions(positions={role: position})
            logger.info(f"✅ Роль {role.name} установлена на позицию {position} (под ролью-сортировкой)")
            return True
        except (AttributeError, TypeError):
            try:
                await role.edit(position=position)
                logger.info(f"✅ Роль {role.name} установлена на позицию {position} через role.edit")
                return True
            except Exception as exc:
                logger.error(f"Ошибка при установке позиции роли через role.edit: {exc}")
                return False
        except Exception as exc:
            logger.error(f"Ошибка при установке позиции роли через edit_role_positions: {exc}")
            return False

    async def check_role_rentals(self):
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            try:
                expired_rentals = await maybe_await(self.db.get_expired_role_rentals())

                for rental in expired_rentals:
                    role_id = rental[0] if isinstance(rental, tuple) else rental.get("role_id")
                    buyer_id = rental[1] if isinstance(rental, tuple) else rental.get("buyer_id")
                    auto_renew = rental[2] if isinstance(rental, tuple) else rental.get("auto_renew", True)

                    role = discord.utils.get(self.guild.roles, id=role_id)
                    buyer = self.guild.get_member(buyer_id)

                    if not role or not buyer or role not in buyer.roles:
                        continue

                    balance = await maybe_await(self.db.get_balance(buyer_id))
                    if auto_renew and balance >= self.cost_role_rent:
                        await maybe_await(self.db.take_money(buyer_id, self.cost_role_rent))
                        await maybe_await(self.db.extend_role_rental(role_id, buyer_id))
                        await maybe_await(
                            self.db.write_new_transactions(
                                buyer,
                                f"Продление аренды роли {role.name}",
                                -self.cost_role_rent,
                            )
                        )
                        logger.info(f"Автоматически продлена аренда роли {role.name} для {buyer.name}")
                    else:
                        await buyer.remove_roles(role)
                        await maybe_await(self.db.remove_role_rental(role_id, buyer_id))
                        logger.info(f"Снята роль {role.name} у {buyer.name} за неуплату")

                        try:
                            await buyer.send(
                                view=self.build_view(
                                    "Аренда роли истекла",
                                    f"У вас истёк срок аренды роли {role.mention}. Для продления пополните баланс.",
                                ),
                                allowed_mentions=discord.AllowedMentions.none()
                            )
                        except Exception:
                            pass

                await asyncio.sleep(86400)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(f"Ошибка при проверке аренды ролей: {exc}")
                await asyncio.sleep(3600)

    async def get_user(self, user_id):
        user = self.bot.get_user(user_id)
        if user is None:
            return f"Пользователь {user_id}"
        return user.mention

    def no_access_view(self):
        return self.build_view("Ошибка", "Эта кнопка не для вас.")

    async def role_manage_view(self, interaction, selected_role, role_created_at):
        time_create = datetime.fromtimestamp(await maybe_await(self.db.get_time_to_pay(selected_role)))
        time_pay = time_create + timedelta(days=30)
        in_shop = await maybe_await(self.db.is_role_in_shop(selected_role.id))
        shop_status = "Выставлена" if in_shop else "Не выставлена"
        
        shop_price = await maybe_await(self.db.get_role_shop_price(selected_role.id))
        price_text = f"**{shop_price}** {COIN}" if shop_price else "Не выставлена"

        return self.build_view(
            "Управление личной ролью",
            f"**Выберите** операцию для **взаимодействия** с **личной ролью** {selected_role.mention}\n\n"
            f"До оплаты — **{(time_pay - time_create).days}** дней\n"
            f"Статус в магазине: {shop_status}\n"
            f"Цена в магазине: {price_text}",
            footer=f"Создана {role_created_at}",
            rows=await self.role_manage_rows(interaction, selected_role, role_created_at),
        )

    async def role_manage_rows(self, root_interaction, selected_role, role_created_at):
        async def change_name(button_interaction):
            if button_interaction.user.id != root_interaction.user.id:
                return await self.respond(button_interaction, self.no_access_view(), ephemeral=True)
            await button_interaction.response.send_modal(
                ChangeRoleNameModal(self, root_interaction, selected_role, role_created_at)
            )

        async def change_color(button_interaction):
            if button_interaction.user.id != root_interaction.user.id:
                return await self.respond(button_interaction, self.no_access_view(), ephemeral=True)
            await button_interaction.response.send_modal(
                ChangeRoleColorModal(self, root_interaction, selected_role, role_created_at)
            )

        async def change_icon(button_interaction):
            if button_interaction.user.id != root_interaction.user.id:
                return await self.respond(button_interaction, self.no_access_view(), ephemeral=True)
            
            self.waiting_for_icon[button_interaction.user.id] = {
                "role_id": selected_role.id,
                "root_interaction": root_interaction
            }
            
            await button_interaction.response.send_message(
                view=self.build_view(
                    "Установка значка",
                    "**Отправьте файл изображения** в этот чат для установки значка роли.\n\n"
                    "Поддерживаются форматы: PNG, JPG, GIF, WEBP\n"
                    "-# Для отмены просто не отправляйте файл в течение 60 секунд."
                ),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none()
            )
            
            async def timeout_icon_wait(user_id):
                await asyncio.sleep(60)
                if user_id in self.waiting_for_icon:
                    del self.waiting_for_icon[user_id]
                    if user_id in self.icon_timeout_tasks:
                        del self.icon_timeout_tasks[user_id]
            
            if button_interaction.user.id in self.icon_timeout_tasks:
                self.icon_timeout_tasks[button_interaction.user.id].cancel()
            
            task = asyncio.create_task(timeout_icon_wait(button_interaction.user.id))
            self.icon_timeout_tasks[button_interaction.user.id] = task

        async def change_price(button_interaction):
            if button_interaction.user.id != root_interaction.user.id:
                return await self.respond(button_interaction, self.no_access_view(), ephemeral=True)
            
            if not await maybe_await(self.db.is_role_in_shop(selected_role.id)):
                return await self.respond(
                    button_interaction,
                    self.build_view("Ошибка", "Роль не выставлена на продажу!"),
                    ephemeral=True,
                )
            
            await button_interaction.response.send_modal(
                ChangeRolePriceModal(self, root_interaction, selected_role, role_created_at)
            )

        async def add_members(button_interaction):
            if button_interaction.user.id != root_interaction.user.id:
                return await self.respond(button_interaction, self.no_access_view(), ephemeral=True)
            
            await button_interaction.response.send_modal(
                AddMembersModal(self, root_interaction, selected_role, role_created_at, add=True)
            )

        async def remove_members(button_interaction):
            if button_interaction.user.id != root_interaction.user.id:
                return await self.respond(button_interaction, self.no_access_view(), ephemeral=True)
            
            await button_interaction.response.send_modal(
                RemoveMembersModal(self, root_interaction, selected_role, role_created_at, add=False)
            )

        async def sell_role(button_interaction):
            if button_interaction.user.id != root_interaction.user.id:
                return await self.respond(button_interaction, self.no_access_view(), ephemeral=True)

            if await maybe_await(self.db.is_role_in_shop(selected_role.id)):
                await button_interaction.response.send_modal(
                    ChangeRolePriceModal(self, root_interaction, selected_role, role_created_at)
                )
            else:
                await button_interaction.response.send_modal(
                    SellRoleModal(self, root_interaction, selected_role, role_created_at)
                )

        async def unsell_role(button_interaction):
            await button_interaction.response.defer()
            if button_interaction.user.id != root_interaction.user.id:
                return

            if not await maybe_await(self.db.is_role_in_shop(selected_role.id)):
                return await self.edit_original(
                    root_interaction,
                    self.back_to_role_settings_view(
                        root_interaction,
                        selected_role,
                        role_created_at,
                        "Ошибка",
                        "Эта роль не выставлена на продажу!",
                    ),
                )

            await maybe_await(self.db.remove_role_from_shop(selected_role.id))
            await self.edit_original(
                root_interaction,
                self.back_to_role_settings_view(
                    root_interaction,
                    selected_role,
                    role_created_at,
                    "Роль снята с продажи",
                    f"Роль {selected_role.mention} снята с продажи.",
                ),
            )

        async def delete_role(button_interaction):
            await button_interaction.response.defer()
            if button_interaction.user.id != root_interaction.user.id:
                return
            await self.edit_original(
                root_interaction,
                self.confirm_delete_role_view(root_interaction, selected_role),
            )

        async def back_to_select(button_interaction):
            await button_interaction.response.defer()
            if button_interaction.user.id != root_interaction.user.id:
                return
            await self.show_personal_role_select(root_interaction)

        return [
            self.row(
                self.button("Изменить название", callback=change_name),
                self.button("Изменить цвет", callback=change_color),
            ),
            self.row(
                self.button("Изменить значок", style=discord.ButtonStyle.secondary, callback=change_icon),
                self.button("Изменить цену", style=discord.ButtonStyle.secondary, callback=change_price),
            ),
            self.row(
                self.button("Выдать пользователям", callback=add_members),
                self.button("Забрать у пользователей", callback=remove_members),
            ),
            self.row(
                self.button("Выставить на продажу", callback=sell_role),
                self.button("Снять с продажи", callback=unsell_role),
            ),
            self.row(
                self.button("Удалить личную роль", callback=delete_role),
                self.button("Назад к выбору роли", callback=back_to_select),
            ),
        ]

    def back_to_role_settings_view(self, root_interaction, selected_role, role_created_at, title, description):
        async def back(button_interaction):
            await button_interaction.response.defer()
            if button_interaction.user.id == root_interaction.user.id:
                await self.edit_original(
                    root_interaction,
                    await self.role_manage_view(root_interaction, selected_role, role_created_at),
                )

        return self.build_view(
            title,
            description,
            rows=[self.row(self.button("Вернуться к настройке роли", callback=back))],
        )

    def confirm_delete_role_view(self, root_interaction, selected_role):
        async def yes(button_interaction):
            await button_interaction.response.defer()
            if button_interaction.user.id != root_interaction.user.id:
                return

            if await maybe_await(self.db.is_role_in_shop(selected_role.id)):
                await maybe_await(self.db.remove_role_from_shop(selected_role.id))

            await maybe_await(self.db.delete_role(selected_role))
            await selected_role.delete()

            async def close(close_interaction):
                await close_interaction.response.defer()
                if close_interaction.user.id == root_interaction.user.id:
                    await root_interaction.delete_original_response()

            await self.edit_original(
                root_interaction,
                self.build_view(
                    "Удалить личную роль",
                    "**Вы** успешно **удалили** вашу **личную роль**.",
                    rows=[self.row(self.button("Закрыть", callback=close))],
                ),
            )

        async def no(button_interaction):
            await button_interaction.response.defer()
            if button_interaction.user.id == root_interaction.user.id:
                role_created_at = f"{selected_role.created_at.day:02}.{selected_role.created_at.month:02}.{selected_role.created_at.year}"
                await self.edit_original(
                    root_interaction,
                    await self.role_manage_view(root_interaction, selected_role, role_created_at),
                )

        return self.build_view(
            "Удалить личную роль",
            f"**Вы уверены** что хотите **удалить** вашу **личную роль** {selected_role.mention} ?",
            rows=[self.row(self.button("Да", callback=yes), self.button("Нет", callback=no))],
        )

    @role.command(name="create", description="Создание личной роли с градиентом.")
    @app_commands.describe(
        name="Введите название роли",
        gradient="Введите градиент в формате #FFFFFF-#000000 (минимум 2 цвета)",
        icon="Загрузите изображение для значка роли"
    )
    @app_commands.rename(name="название", gradient="градиент", icon="значок")
    async def create(self, interaction: discord.Interaction, name: str, gradient: str, icon: discord.Attachment = None):
        balance = await maybe_await(self.db.get_balance(interaction.user.id))
        if balance < self.cost_role_create:
            return await self.respond(
                interaction,
                self.build_view(
                    "Создание роли",
                    f"{interaction.user.mention}, у Вас **недостаточно средств**.",
                ),
                ephemeral=True,
            )

        if icon and not icon.content_type.startswith("image/"):
            return await self.respond(
                interaction,
                self.build_view(
                    "Создание роли",
                    "Загруженный файл должен быть изображением!"
                ),
                ephemeral=True,
            )

        try:
            gradient_colors = parse_gradient(gradient)
            gradient_hexes = parse_gradient_hex(gradient)
        except Exception:
            return await self.respond(
                interaction,
                self.build_view(
                    "Создание роли",
                    "Введите **градиент** в корректном **HEX** формате.\nНапример: **#FFFFFF-#000000** (минимум 2 цвета)",
                ),
                ephemeral=True,
            )

        await interaction.response.defer()

        root_interaction = interaction
        icon_url = icon.url if icon else None
        icon_data = None
        
        if icon_url:
            try:
                icon_data = await download_image(icon_url)
            except Exception as e:
                return await self.respond(
                    interaction,
                    self.build_view(
                        "Создание роли",
                        f"Не удалось загрузить изображение: {str(e)}"
                    ),
                    ephemeral=True,
                )

        class ConfirmCreateView(discord.ui.LayoutView):
            def __init__(inner_self):
                super().__init__(timeout=None)
                container = discord.ui.Container()
                
                icon_text = f"\nЗначок: [Загружен]" if icon else "\nЗначок: Не установлен"
                gradient_text = " → ".join(gradient_hexes)
                
                container.add_item(discord.ui.TextDisplay(
                    content=clamp_text(
                        "## Создание роли\n\n"
                        f"**Вы** уверены что хотите создать роль **{name}** за **{self.cost_role_create}** {COIN}?\n"
                        f"Градиент: {gradient_text}\n"
                        f"{icon_text}\n\n"
                        "-# Роли создаются сроком на 30 дней после чего их необходимо оплатить."
                    )
                ))

                async def yes(button_interaction):
                    await button_interaction.response.defer()
                    if button_interaction.user.id != root_interaction.user.id:
                        return

                    try:
                        role = await root_interaction.guild.create_role(name=name)
                        
                        kwargs = {}
                        kwargs["colour"] = gradient_colors[0]
                        if len(gradient_colors) > 1:
                            kwargs["secondary_colour"] = gradient_colors[1]
                        if len(gradient_colors) > 2:
                            kwargs["tertiary_colour"] = gradient_colors[2]
                        
                        await role.edit(**kwargs)
                        
                        if icon_data:
                            try:
                                success = await set_role_icon(role, icon_data)
                                if not success:
                                    logger.warning(f"Не удалось установить значок для роли {role.name}, но роль создана")
                            except Exception as e:
                                logger.error(f"Ошибка при установке значка: {e}")
                        
                        gradient_hex_str = "-".join(gradient_hexes)
                        await maybe_await(self.db.set_role_gradient(role.id, gradient_hex_str))
                        
                        if icon_url:
                            await maybe_await(self.db.set_role_icon(role.id, icon_url))
                        
                        await self.move_role_under_sort_role(root_interaction.guild, role)

                        await root_interaction.user.add_roles(role)
                        await maybe_await(self.db.write_new_role(root_interaction.user, role))
                        await maybe_await(self.db.take_money(root_interaction.user.id, self.cost_role_create))
                        await maybe_await(
                            self.db.write_new_transactions(
                                root_interaction.user,
                                "Создание личной роли",
                                -self.cost_role_create,
                            )
                        )

                        inner_self.stop()
                        await self.edit_original(
                            root_interaction,
                            self.build_view(
                                "Создание роли",
                                f"**Вы** успешно создали свою **личную роль** {role.mention}\n"
                                f"Градиент: {gradient_text}\n"
                                f"{icon_text}\n"
                                f"Для управления ролью **/role manage**",
                            ),
                        )
                    except Exception as e:
                        logger.error(f"Ошибка при создании роли: {e}")
                        await self.edit_original(
                            root_interaction,
                            self.build_view(
                                "Ошибка",
                                f"Не удалось создать роль: {str(e)}"
                            ),
                        )

                async def no(button_interaction):
                    await button_interaction.response.defer()
                    if button_interaction.user.id == root_interaction.user.id:
                        inner_self.stop()
                        await root_interaction.delete_original_response()

                row = discord.ui.ActionRow()
                row.add_item(self.button("Да", callback=yes))
                row.add_item(self.button("Нет", callback=no))
                container.add_item(discord.ui.Separator())
                container.add_item(row)
                inner_self.add_item(container)

            async def on_timeout(inner_self):
                await self.edit_original(
                    root_interaction,
                    self.build_view(
                        "Создание роли",
                        "Время ожидания истекло!",
                    ),
                )

        await interaction.edit_original_response(view=ConfirmCreateView())

    @role.command(name="sell", description="Выставить личную роль на продажу.")
    @app_commands.describe(role="Выберите личную роль", price="Укажите цену")
    @app_commands.rename(role="роль", price="цена")
    async def sell(self, interaction: discord.Interaction, role: discord.Role, price: app_commands.Range[int, 1, None]):
        if not await maybe_await(self.db.is_owner_role(interaction.user, role)):
            return await self.respond(
                interaction,
                self.build_view("Ошибка", "Эта роль не принадлежит вам!"),
                ephemeral=True,
            )

        if await maybe_await(self.db.is_role_in_shop(role.id)):
            await maybe_await(self.db.update_role_shop_price(role.id, price))
            await self.respond(
                interaction,
                self.build_view(
                    "Цена обновлена",
                    f"Цена роли {role.mention} обновлена на **{price}** {COIN}",
                ),
            )
        else:
            if await maybe_await(self.db.is_personal_role(role.id)):
                await maybe_await(self.db.add_role_to_shop(interaction.user.id, role.id, price))
                await self.respond(
                    interaction,
                    self.build_view(
                        "Роль выставлена на продажу",
                        f"Роль {role.mention} выставлена в магазин за **{price}** {COIN}",
                    ),
                )
            else:
                await maybe_await(self.db.write_new_role(interaction.user, role))
                await maybe_await(self.db.add_role_to_shop(interaction.user.id, role.id, price))
                await self.respond(
                    interaction,
                    self.build_view(
                        "Роль выставлена на продажу",
                        f"Роль {role.mention} выставлена в магазин за **{price}** {COIN}",
                    ),
                )

    @role.command(name="unsell", description="Снять личную роль с продажи.")
    @app_commands.describe(role="Выберите личную роль")
    @app_commands.rename(role="роль")
    async def unsell(self, interaction: discord.Interaction, role: discord.Role):
        if not await maybe_await(self.db.is_owner_role(interaction.user, role)):
            return await self.respond(
                interaction,
                self.build_view("Ошибка", "Эта роль не принадлежит вам!"),
                ephemeral=True,
            )

        if not await maybe_await(self.db.is_role_in_shop(role.id)):
            return await self.respond(
                interaction,
                self.build_view("Ошибка", "Эта роль не выставлена на продажу!"),
                ephemeral=True,
            )

        await maybe_await(self.db.remove_role_from_shop(role.id))
        await self.respond(
            interaction,
            self.build_view(
                "Роль снята с продажи",
                f"Роль {role.mention} снята с продажи.",
            ),
        )

    @role.command(name="auto_rent", description="Настройка автоматического продления аренды роли.")
    @app_commands.describe(role="Выберите роль", enabled="Включить или выключить автопродление")
    @app_commands.rename(role="роль", enabled="включить")
    @app_commands.choices(enabled=[
        app_commands.Choice(name="Включить", value="Включить"),
        app_commands.Choice(name="Выключить", value="Выключить"),
    ])
    async def auto_rent(self, interaction: discord.Interaction, role: discord.Role, enabled: str):
        if not await maybe_await(self.db.is_role_rented_by_user(role.id, interaction.user.id)):
            return await self.respond(
                interaction,
                self.build_view("Ошибка", "Вы не арендовали эту роль!"),
                ephemeral=True,
            )

        is_enabled = enabled == "Включить"
        await maybe_await(self.db.set_auto_renew_role(role.id, interaction.user.id, is_enabled))

        status = "включено" if is_enabled else "отключено"
        await self.respond(
            interaction,
            self.build_view(
                "Настройка автопродления",
                f"Автоматическое продление аренды роли {role.mention} **{status}**.",
            ),
        )

    @role.command(name="renew", description="Продлить аренду роли вручную.")
    @app_commands.describe(role="Выберите роль")
    @app_commands.rename(role="роль")
    async def renew(self, interaction: discord.Interaction, role: discord.Role):
        if not await maybe_await(self.db.is_role_rented_by_user(role.id, interaction.user.id)):
            return await self.respond(
                interaction,
                self.build_view("Ошибка", "Вы не арендовали эту роль!"),
                ephemeral=True,
            )

        rental_info = await maybe_await(self.db.get_role_rental_info(role.id, interaction.user.id))
        days_left = rental_info.get("days_left", 0) if rental_info else 0

        if days_left > 25:
            return await self.respond(
                interaction,
                self.build_view(
                    "Ошибка",
                    f"До окончания аренды осталось **{days_left}** дней. Продление доступно за **7** дней до окончания.",
                ),
                ephemeral=True,
            )

        if await maybe_await(self.db.get_balance(interaction.user.id)) >= self.cost_role_rent:
            await maybe_await(self.db.take_money(interaction.user.id, self.cost_role_rent))
            await maybe_await(self.db.extend_role_rental(role.id, interaction.user.id))
            await maybe_await(
                self.db.write_new_transactions(
                    interaction.user,
                    f"Продление аренды роли {role.name}",
                    -self.cost_role_rent,
                )
            )
            view = self.build_view(
                "Аренда продлена",
                f"Вы успешно продлили аренду роли {role.mention} на **30** дней.",
            )
        else:
            view = self.build_view(
                "Ошибка",
                "У вас недостаточно средств для продления аренды!",
            )

        await self.respond(interaction, view, ephemeral=True)

    @role.command(name="manage", description="Управление личной ролью.")
    async def manage(self, interaction: discord.Interaction):
        has_personal_roles = await maybe_await(self.db.is_exists_role(interaction.user))
        rented_roles = await maybe_await(self.db.get_user_active_rentals(interaction.user.id))
        inventory_roles = await maybe_await(self.db.get_user_inventory(interaction.user.id))
        has_other_roles = len(rented_roles) > 0 or len(inventory_roles) > 0

        if not has_personal_roles and not has_other_roles:
            return await self.respond(
                interaction,
                self.build_view("Управление ролями", "У вас нет личных или купленных ролей!"),
                ephemeral=True,
            )

        await interaction.response.defer()

        user_roles = []
        personal_role_ids = await maybe_await(self.db.get_all_roles(interaction.user))

        for role_id in personal_role_ids:
            role = discord.utils.get(self.guild.roles, id=int(role_id))
            if role:
                user_roles.append(role)

        for rental in rented_roles:
            role_id = rental[0]
            role = discord.utils.get(self.guild.roles, id=role_id)
            if role and role not in user_roles:
                user_roles.append(role)

        for inv_role in inventory_roles:
            role_id = inv_role["role_id"]
            role = discord.utils.get(self.guild.roles, id=role_id)
            if role and role not in user_roles:
                user_roles.append(role)

        if not user_roles:
            return await interaction.edit_original_response(
                view=self.build_view("Управление ролями", "У вас нет доступных ролей!")
            )

        self._manage_state = {
            interaction.id: {
                "personal_role_ids": personal_role_ids,
                "user_roles": user_roles,
                "has_personal_roles": has_personal_roles,
            }
        }

        await interaction.edit_original_response(
            view=self.main_manage_view(interaction, has_personal_roles, user_roles)
        )

    def main_manage_view(self, root_interaction, has_personal_roles, user_roles):
        select = discord.ui.Select(placeholder="Выберите действие")

        if has_personal_roles:
            select.add_option(
                label="Управление личными ролями",
                value="personal",
                description="Изменить название, цвет, удалить",
            )

        if user_roles:
            select.add_option(
                label="Управление видимостью ролей",
                value="visibility",
                description="Скрыть или показать роли",
            )

        async def select_callback(select_interaction):
            await select_interaction.response.defer()
            if select_interaction.user.id != root_interaction.user.id:
                return

            if select.values[0] == "personal":
                await self.show_personal_role_select(root_interaction)
            elif select.values[0] == "visibility":
                await self.show_visibility(root_interaction, user_roles)

        async def close(close_interaction):
            await close_interaction.response.defer()
            if close_interaction.user.id == root_interaction.user.id:
                await root_interaction.delete_original_response()

        select.callback = select_callback

        return self.build_view(
            "Управление ролями",
            "**Выберите** действие",
            rows=[
                self.row(select),
                self.row(self.button("Закрыть", callback=close)),
            ],
        )

    async def show_personal_role_select(self, root_interaction):
        personal_role_ids = await maybe_await(self.db.get_all_roles(root_interaction.user))
        role_select = discord.ui.Select(placeholder="Выберите личную роль")

        added = 0
        for role_id in personal_role_ids:
            role = discord.utils.get(self.guild.roles, id=int(role_id))
            if role is not None and added < 25:
                role_select.add_option(label=role.name[:100], value=str(role.id))
                added += 1

        if added == 0:
            return await self.edit_original(
                root_interaction,
                self.build_view("Личные роли", "У вас нет доступных личных ролей."),
            )

        async def role_callback(role_interaction):
            await role_interaction.response.defer()
            if role_interaction.user.id != root_interaction.user.id:
                return

            selected_role = discord.utils.get(self.guild.roles, id=int(role_select.values[0]))
            if selected_role is None:
                return await role_interaction.followup.send("Роль не найдена!", ephemeral=True)

            role_created_at = f"{selected_role.created_at.day:02}.{selected_role.created_at.month:02}.{selected_role.created_at.year}"
            await self.edit_original(
                root_interaction,
                await self.role_manage_view(root_interaction, selected_role, role_created_at),
            )

        role_select.callback = role_callback

        async def back_to_main(button_interaction):
            await button_interaction.response.defer()
            if button_interaction.user.id == root_interaction.user.id:
                has_personal_roles = await maybe_await(self.db.is_exists_role(root_interaction.user))
                user_roles = self._manage_state.get(root_interaction.id, {}).get("user_roles", [])
                await self.edit_original(
                    root_interaction,
                    self.main_manage_view(root_interaction, has_personal_roles, user_roles),
                )

        await self.edit_original(
            root_interaction,
            self.build_view(
                "Личные роли",
                "**Выберите** роль для **взаимодействия**",
                rows=[
                    self.row(role_select),
                    self.row(self.button("Назад", callback=back_to_main)),
                ],
            ),
        )

    async def show_visibility(self, root_interaction, user_roles):
        if not user_roles:
            return await self.edit_original(
                root_interaction,
                self.build_view(
                    "Управление видимостью ролей",
                    "У вас нет ролей для управления видимостью!",
                ),
            )

        user_roles_sorted = sorted(user_roles, key=lambda role: role.name)
        hide_select = discord.ui.Select(placeholder="Скрыть роль", min_values=1, max_values=1)
        show_select = discord.ui.Select(placeholder="Показать роль", min_values=1, max_values=1)

        hide_count = 0
        show_count = 0
        for role in user_roles_sorted:
            has_role = role in root_interaction.user.roles
            if has_role and hide_count < 25:
                hide_select.add_option(label=role.name[:100], value=str(role.id), description="Есть сейчас - можно снять")
                hide_count += 1
            elif not has_role:
                is_hidden = await maybe_await(self.db.is_role_hidden(root_interaction.user.id, role.id))
                if is_hidden and show_count < 25:
                    show_select.add_option(label=role.name[:100], value=str(role.id), description="Скрыта сейчас - можно выдать")
                    show_count += 1

        for role in user_roles_sorted:
            has_role = role in root_interaction.user.roles
            is_hidden = await maybe_await(self.db.is_role_hidden(root_interaction.user.id, role.id))
            if not has_role and not is_hidden and show_count < 25:
                show_select.add_option(label=role.name[:100], value=str(role.id), description="Не выдана - можно выдать")
                show_count += 1

        if hide_count == 0:
            hide_select.add_option(label="Нет ролей для скрытия", value="none", default=True)
            hide_select.disabled = True

        if show_count == 0:
            show_select.add_option(label="Нет ролей для показа", value="none", default=True)
            show_select.disabled = True

        async def hide_callback(select_interaction):
            await select_interaction.response.defer()
            if select_interaction.user.id != root_interaction.user.id:
                return
            if select_interaction.data["values"][0] == "none":
                return

            role_id = int(select_interaction.data["values"][0])
            role = discord.utils.get(self.guild.roles, id=role_id)
            if role:
                await root_interaction.user.remove_roles(role)
                await maybe_await(self.db.toggle_role_visibility(root_interaction.user.id, role_id, True))
                await select_interaction.followup.send(
                    view=self.build_view(
                        "Роль скрыта",
                        f"Роль {role.mention} **снята** с вас. Чтобы получить обратно, используйте 'Показать роль'.",
                    ),
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions.none()
                )
                await self.show_visibility(root_interaction, user_roles)

        async def show_callback(select_interaction):
            await select_interaction.response.defer()
            if select_interaction.user.id != root_interaction.user.id:
                return
            if select_interaction.data["values"][0] == "none":
                return

            role_id = int(select_interaction.data["values"][0])
            role = discord.utils.get(self.guild.roles, id=role_id)
            if role:
                await root_interaction.user.add_roles(role)
                await maybe_await(self.db.toggle_role_visibility(root_interaction.user.id, role_id, False))
                await select_interaction.followup.send(
                    view=self.build_view(
                        "Роль показана",
                        f"Роль {role.mention} **выдана** вам обратно.",
                    ),
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions.none()
                )
                await self.show_visibility(root_interaction, user_roles)

        async def back(back_interaction):
            await back_interaction.response.defer()
            if back_interaction.user.id == root_interaction.user.id:
                has_personal_roles = await maybe_await(self.db.is_exists_role(root_interaction.user))
                await self.edit_original(
                    root_interaction,
                    self.main_manage_view(root_interaction, has_personal_roles, user_roles),
                )

        hide_select.callback = hide_callback
        show_select.callback = show_callback

        await self.edit_original(
            root_interaction,
            self.build_view(
                "Управление видимостью ролей",
                "Скрытие/Показ ролей\n\nВерхнее меню - скрыть роль\nНижнее меню - показать роль",
                rows=[
                    self.row(hide_select),
                    self.row(show_select),
                    self.row(self.button("Назад", callback=back)),
                ],
            ),
        )


class ChangeRoleNameModal(discord.ui.Modal):
    def __init__(self, cog, root_interaction, role, role_created_at):
        super().__init__(title="Изменение названия роли")
        self.cog = cog
        self.root_interaction = root_interaction
        self.role = role
        self.role_created_at = role_created_at
        self.name_input = discord.ui.TextInput(
            label="Новое название",
            placeholder="Введите новое название роли",
            required=True,
            max_length=100,
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        name = str(self.name_input.value).strip()

        async def yes(button_interaction):
            await button_interaction.response.defer()
            if button_interaction.user.id != self.root_interaction.user.id:
                return

            if await maybe_await(self.cog.db.get_balance(self.root_interaction.user.id)) >= self.cog.cost_role_change_name:
                await maybe_await(self.cog.db.take_money(self.root_interaction.user.id, self.cog.cost_role_change_name))
                await maybe_await(
                    self.cog.db.write_new_transactions(
                        self.root_interaction.user,
                        "Личная роль",
                        -self.cog.cost_role_change_name,
                    )
                )
                await self.role.edit(name=name)
                await self.cog.edit_original(
                    self.root_interaction,
                    self.cog.back_to_role_settings_view(
                        self.root_interaction,
                        self.role,
                        self.role_created_at,
                        "Изменение названия роли",
                        f"**Вы** успешно изменили **название** роли {self.role.mention}",
                    ),
                )
            else:
                await self.cog.edit_original(
                    self.root_interaction,
                    self.cog.back_to_role_settings_view(
                        self.root_interaction,
                        self.role,
                        self.role_created_at,
                        "Изменение названия роли",
                        "у **Вас** недостаточно **средств** для **изменения названия роли**",
                    ),
                )

        async def no(button_interaction):
            await button_interaction.response.defer()
            if button_interaction.user.id == self.root_interaction.user.id:
                await self.cog.edit_original(
                    self.root_interaction,
                    await self.cog.role_manage_view(self.root_interaction, self.role, self.role_created_at),
                )

        await self.cog.edit_original(
            self.root_interaction,
            self.cog.build_view(
                "Изменение названия роли",
                f"{self.root_interaction.user.mention}, **Вы уверены** что хотите изменить **название** роли на **{name}** за **{self.cog.cost_role_change_name}** {COIN}?",
                rows=[self.cog.row(self.cog.button("Да", callback=yes), self.cog.button("Нет", callback=no))],
            ),
        )


class ChangeRoleColorModal(discord.ui.Modal):
    def __init__(self, cog, root_interaction, role, role_created_at):
        super().__init__(title="Изменение цвета роли")
        self.cog = cog
        self.root_interaction = root_interaction
        self.role = role
        self.role_created_at = role_created_at
        self.color_input = discord.ui.TextInput(
            label="Новый градиент",
            placeholder="#FFFFFF-#000000 (минимум 2 цвета)",
            required=True,
            max_length=50,
        )
        self.add_item(self.color_input)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        raw_gradient = str(self.color_input.value).strip()

        try:
            gradient_colors = parse_gradient(raw_gradient)
            gradient_hexes = parse_gradient_hex(raw_gradient)
        except Exception:
            await interaction.followup.send(
                view=self.cog.build_view(
                    "Ошибка",
                    "Введите градиент в формате: #FFFFFF-#000000 (минимум 2 цвета)",
                ),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none()
            )
            return

        async def yes(button_interaction):
            await button_interaction.response.defer()
            if button_interaction.user.id != self.root_interaction.user.id:
                return

            if await maybe_await(self.cog.db.get_balance(self.root_interaction.user.id)) >= self.cog.cost_role_change_color:
                await maybe_await(self.cog.db.take_money(self.root_interaction.user.id, self.cog.cost_role_change_color))
                await maybe_await(
                    self.cog.db.write_new_transactions(
                        self.root_interaction.user,
                        "Личная роль",
                        -self.cog.cost_role_change_color,
                    )
                )
                
                kwargs = {}
                kwargs["colour"] = gradient_colors[0]
                if len(gradient_colors) > 1:
                    kwargs["secondary_colour"] = gradient_colors[1]
                if len(gradient_colors) > 2:
                    kwargs["tertiary_colour"] = gradient_colors[2]
                
                await self.role.edit(**kwargs)
                
                gradient_hex_str = "-".join(gradient_hexes)
                await maybe_await(self.cog.db.set_role_gradient(self.role.id, gradient_hex_str))
                
                gradient_text = " → ".join(gradient_hexes)
                await self.cog.edit_original(
                    self.root_interaction,
                    self.cog.back_to_role_settings_view(
                        self.root_interaction,
                        self.role,
                        self.role_created_at,
                        "Изменение цвета роли",
                        f"**Вы** успешно изменили **цвет** роли {self.role.mention} на градиент {gradient_text}",
                    ),
                )
            else:
                await self.cog.edit_original(
                    self.root_interaction,
                    self.cog.back_to_role_settings_view(
                        self.root_interaction,
                        self.role,
                        self.role_created_at,
                        "Изменение цвета роли",
                        "у **Вас** недостаточно **средств** для **изменения цвета роли**",
                    ),
                )

        async def no(button_interaction):
            await button_interaction.response.defer()
            if button_interaction.user.id == self.root_interaction.user.id:
                await self.cog.edit_original(
                    self.root_interaction,
                    await self.cog.role_manage_view(self.root_interaction, self.role, self.role_created_at),
                )

        gradient_text = " → ".join(gradient_hexes)
        await self.cog.edit_original(
            self.root_interaction,
            self.cog.build_view(
                "Изменение цвета роли",
                f"**Вы уверены** что хотите изменить **цвет** роли на градиент **{gradient_text}** за **{self.cog.cost_role_change_color}** {COIN}?",
                rows=[self.cog.row(self.cog.button("Да", callback=yes), self.cog.button("Нет", callback=no))],
            ),
        )


class ChangeRolePriceModal(discord.ui.Modal):
    def __init__(self, cog, root_interaction, role, role_created_at):
        super().__init__(title="Изменение цены роли")
        self.cog = cog
        self.root_interaction = root_interaction
        self.role = role
        self.role_created_at = role_created_at
        self.price_input = discord.ui.TextInput(
            label="Новая цена",
            placeholder="Введите новую цену",
            required=True,
            min_length=1,
            max_length=10,
        )
        self.add_item(self.price_input)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            price = int(str(self.price_input.value).strip())
            if price <= 0:
                raise ValueError
        except Exception:
            return await interaction.followup.send(
                view=self.cog.build_view("Ошибка", "Введите корректную цену!"),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none()
            )

        await maybe_await(self.cog.db.update_role_shop_price(self.role.id, price))
            
        await self.cog.edit_original(
            self.root_interaction,
            self.cog.back_to_role_settings_view(
                self.root_interaction,
                self.role,
                self.role_created_at,
                "Изменение цены роли",
                f"**Вы** успешно изменили цену роли {self.role.mention} на **{price}** {COIN}",
            ),
        )
        await interaction.followup.send(
            view=self.cog.build_view(
                "Цена обновлена",
                f"Новая цена роли {self.role.mention}: **{price}** {COIN}",
            ),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none()
        )


class SellRoleModal(discord.ui.Modal):
    def __init__(self, cog, root_interaction, role, role_created_at):
        super().__init__(title="Установка цены")
        self.cog = cog
        self.root_interaction = root_interaction
        self.role = role
        self.role_created_at = role_created_at
        self.price_input = discord.ui.TextInput(
            label="Цена продажи",
            placeholder="Введите цену",
            required=True,
            min_length=1,
            max_length=10,
        )
        self.add_item(self.price_input)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            price = int(str(self.price_input.value).strip())
            if price <= 0:
                raise ValueError
        except Exception:
            return await interaction.followup.send(
                view=self.cog.build_view("Ошибка", "Введите корректную цену!"),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none()
            )

        if await maybe_await(self.cog.db.is_role_in_shop(self.role.id)):
            await maybe_await(self.cog.db.update_role_shop_price(self.role.id, price))
            await self.cog.edit_original(
                self.root_interaction,
                await self.cog.role_manage_view(self.root_interaction, self.role, self.role_created_at),
            )
            await interaction.followup.send(
                view=self.cog.build_view(
                    "Цена обновлена",
                    f"Цена роли {self.role.mention} обновлена на **{price}** {COIN}",
                ),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none()
            )
        else:
            if await maybe_await(self.cog.db.is_personal_role(self.role.id)):
                await maybe_await(self.cog.db.add_role_to_shop(self.root_interaction.user.id, self.role.id, price))
            else:
                await maybe_await(self.cog.db.write_new_role(self.root_interaction.user, self.role))
                await maybe_await(self.cog.db.add_role_to_shop(self.root_interaction.user.id, self.role.id, price))
            
            await self.cog.edit_original(
                self.root_interaction,
                await self.cog.role_manage_view(self.root_interaction, self.role, self.role_created_at),
            )
            await interaction.followup.send(
                view=self.cog.build_view(
                    "Роль выставлена на продажу",
                    f"Роль {self.role.mention} выставлена в магазин за **{price}** {COIN}",
                ),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none()
            )


class AddMembersModal(discord.ui.Modal):
    def __init__(self, cog, root_interaction, selected_role, role_created_at, add=True):
        super().__init__(title="Выдать роль пользователям")
        self.cog = cog
        self.root_interaction = root_interaction
        self.selected_role = selected_role
        self.role_created_at = role_created_at
        self.add = add
        
        self.user_input = discord.ui.TextInput(
            label="Пользователи (юзернейм или ID)",
            placeholder="Введите юзернейм или ID",
            required=True,
            max_length=2000,
            style=discord.TextStyle.paragraph
        )
        self.add_item(self.user_input)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        
        input_text = self.user_input.value
        members = []
        
        parts = input_text.replace(",", " ").replace("\n", " ").split()
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
            
            target_user = None
            
            try:
                user_id = int(part)
                target_user = interaction.guild.get_member(user_id)
            except ValueError:
                if part.startswith("<@") and part.endswith(">"):
                    try:
                        user_id = int(part.strip("<@!>"))
                        target_user = interaction.guild.get_member(user_id)
                    except ValueError:
                        pass
                
                if not target_user:
                    clean_input = part.lower()
                    for member in interaction.guild.members:
                        if member.name.lower() == clean_input or member.display_name.lower() == clean_input:
                            target_user = member
                            break
                        if str(member).lower() == clean_input:
                            target_user = member
                            break
            
            if target_user and target_user.id != interaction.user.id and not target_user.bot:
                members.append(target_user)
        
        if not members:
            return await interaction.followup.send(
                view=self.cog.build_view(
                    "Ошибка",
                    "Не найдено ни одного пользователя! Убедитесь, что вы правильно ввели ID, юзернейм или упоминание."
                ),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none()
            )
        
        mention_members = " ".join(member.mention for member in members)
        
        for member in members:
            await member.add_roles(self.selected_role)
        
        await self.cog.edit_original(
            self.root_interaction,
            self.cog.back_to_role_settings_view(
                self.root_interaction,
                self.selected_role,
                self.role_created_at,
                "Выдача роли",
                f"**Вы** успешно **выдали** вашу роль пользователям: {mention_members}",
            ),
        )
        
        await interaction.followup.send(
            view=self.cog.build_view(
                "Готово",
                f"Роль {self.selected_role.mention} выдана {len(members)} пользователям."
            ),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none()
        )


class RemoveMembersModal(discord.ui.Modal):
    def __init__(self, cog, root_interaction, selected_role, role_created_at, add=False):
        super().__init__(title="Забрать роль у пользователей")
        self.cog = cog
        self.root_interaction = root_interaction
        self.selected_role = selected_role
        self.role_created_at = role_created_at
        self.add = add
        
        self.user_input = discord.ui.TextInput(
            label="Пользователи (юзернейм или ID)",
            placeholder="Введите юзернейм или ID",
            required=True,
            max_length=2000,
            style=discord.TextStyle.paragraph
        )
        self.add_item(self.user_input)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        
        input_text = self.user_input.value
        members = []
        
        parts = input_text.replace(",", " ").replace("\n", " ").split()
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
            
            target_user = None
            
            try:
                user_id = int(part)
                target_user = interaction.guild.get_member(user_id)
            except ValueError:
                if part.startswith("<@") and part.endswith(">"):
                    try:
                        user_id = int(part.strip("<@!>"))
                        target_user = interaction.guild.get_member(user_id)
                    except ValueError:
                        pass
                
                if not target_user:
                    clean_input = part.lower()
                    for member in interaction.guild.members:
                        if member.name.lower() == clean_input or member.display_name.lower() == clean_input:
                            target_user = member
                            break
                        if str(member).lower() == clean_input:
                            target_user = member
                            break
            
            if target_user and target_user.id != interaction.user.id and not target_user.bot:
                members.append(target_user)
        
        if not members:
            return await interaction.followup.send(
                view=self.cog.build_view(
                    "Ошибка",
                    "Не найдено ни одного пользователя! Убедитесь, что вы правильно ввели ID, юзернейм или упоминание."
                ),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none()
            )
        
        mention_members = " ".join(member.mention for member in members)
        
        for member in members:
            await member.remove_roles(self.selected_role)
        
        await self.cog.edit_original(
            self.root_interaction,
            self.cog.back_to_role_settings_view(
                self.root_interaction,
                self.selected_role,
                self.role_created_at,
                "Забрать роль",
                f"**Вы** успешно **забрали** вашу роль у пользователей: {mention_members}",
            ),
        )
        
        await interaction.followup.send(
            view=self.cog.build_view(
                "Готово",
                f"Роль {self.selected_role.mention} забрана у {len(members)} пользователей."
            ),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none()
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(PersonalRoles(bot))