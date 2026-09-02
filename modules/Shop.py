import inspect
import math
import sqlite3

import discord
from discord import app_commands
from discord.ext import commands

from modules.Database import Database
from modules.Logger import *
from modules.Utils import Utils


guild_id_cmd = Utils.get_guild_id()
COIN = "<:coin:1515637898735652924>"
ACCENT = 0x2F3136
SHOP_IMAGE = "https://cdn.discordapp.com/attachments/992883178362642453/1029462389130792970/-1.png"
NO_MENTIONS = discord.AllowedMentions.none()


async def maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def normalize_role_data(role_data):
    if len(role_data) >= 5:
        owner_id, role_id, cost, count, days_left = role_data[:5]
    else:
        owner_id, role_id, cost, days_left = role_data[:4]
        count = 0

    return int(owner_id), int(role_id), int(cost), int(count or 0), int(days_left or 30)


def unique_shop_roles(roles):
    unique_roles = []
    seen_role_ids = set()

    for role_data in roles or []:
        try:
            _owner_id, role_id, _cost, _count, _days_left = normalize_role_data(role_data)
        except (TypeError, ValueError):
            continue

        if role_id in seen_role_ids:
            continue

        seen_role_ids.add(role_id)
        unique_roles.append(role_data)

    return unique_roles


def clamp_text(value, limit=3800):
    value = "" if value is None else str(value)
    return value if len(value) <= limit else value[: limit - 3] + "..."


class Shop(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database()
        self.guild = None
        self.active_purchases = set()

    def fix_shop_duplicates(self):
        """Удаляет дубликаты из таблицы shop"""
        try:
            db_name = Utils.get_patch_db("main")
            conn = sqlite3.connect(db_name)
            cursor = conn.cursor()
            
            # Проверяем наличие дубликатов
            cursor.execute("""
                SELECT role, COUNT(*) as count 
                FROM shop 
                GROUP BY role 
                HAVING COUNT(*) > 1
            """)
            duplicates = cursor.fetchall()
            
            if duplicates:
                logger.warning(f"Найдено дубликатов в магазине: {len(duplicates)}")
                for dup in duplicates:
                    logger.warning(f"Роль {dup[0]} имеет {dup[1]} дубликатов")

                cursor.execute("""
                    UPDATE shop
                    SET count = COALESCE((
                        SELECT MAX(COALESCE(s2.count, 0))
                        FROM shop s2
                        WHERE s2.role = shop.role
                    ), COALESCE(count, 0))
                    WHERE role IN (
                        SELECT role
                        FROM shop
                        GROUP BY role
                        HAVING COUNT(*) > 1
                    )
                """)
                
                # Удаляем дубликаты, оставляя только самую старую запись
                cursor.execute("""
                    DELETE FROM shop 
                    WHERE id NOT IN (
                        SELECT MIN(id) 
                        FROM shop 
                        GROUP BY role
                    )
                """)
                conn.commit()
                deleted_count = cursor.rowcount
                logger.info(f"Удалено {deleted_count} дубликатов из магазина")
            else:
                logger.info("Дубликатов в магазине не найдено")
            
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Ошибка при удалении дубликатов из магазина: {e}")
            return False

    @commands.Cog.listener()
    async def on_ready(self):
        self.guild = discord.utils.get(self.bot.guilds, id=guild_id_cmd)
        logger.info("/shop - start")
        # Удаляем дубликаты при загрузке
        self.fix_shop_duplicates()

    def build_view(self, title, description=None, *, footer=None, rows=None, image_url=None, thumbnail_url=None, timeout=None):
        view = discord.ui.LayoutView(timeout=timeout or None)
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
            for row_items in rows:
                container.add_item(row_items)

        view.add_item(container)
        return view

    def row(self, *items):
        row = discord.ui.ActionRow()
        for item in items:
            row.add_item(item)
        return row

    def button(self, *, label=None, emoji=None, custom_id=None, callback=None, disabled=False):
        button = discord.ui.Button(
            label=label,
            emoji=emoji,
            custom_id=custom_id,
            style=discord.ButtonStyle.secondary,
            disabled=disabled
        )
        if callback is not None:
            button.callback = callback
        return button

    async def get_user(self, user_id):
        user = self.bot.get_user(int(user_id))
        if user is None:
            return f"Пользователь {user_id}"
        return user.mention

    async def make_shop_view(self, page, total_pages, roles, *, rows=None, thumbnail_url=None):
        roles = unique_shop_roles(roles)
        page_roles = roles[(page - 1) * 5:page * 5]
        
        container_items = []
        
        content = (
            "## Магазин личных ролей\n"
            "Хочешь создать свою личную роль?\n"
            "Тогда используй команду `/role create`"
        )
        
        if thumbnail_url:
            container_items.append(
                discord.ui.Section(
                    discord.ui.TextDisplay(content=clamp_text(content)),
                    accessory=discord.ui.Thumbnail(thumbnail_url),
                )
            )
        else:
            container_items.append(discord.ui.TextDisplay(content=clamp_text(content)))
        
        container_items.append(discord.ui.Separator())
        container_items.append(discord.ui.MediaGallery(discord.MediaGalleryItem(SHOP_IMAGE)))
        
        for index, role_data in enumerate(page_roles):
            owner_id, role_id, cost, count, _days_left = normalize_role_data(role_data)
            owner = await self.get_user(owner_id)
            role = discord.utils.get(self.guild.roles, id=role_id) if self.guild else None

            if role is None:
                continue

            if index > 0:
                container_items.append(discord.ui.Separator())

            item_num = (page - 1) * 5 + index + 1
            block = (
                f"**{item_num}.** {role.mention}\n"
                f"* Продавец: {owner}\n"
                f"* Стоимость: **{cost}** {COIN}\n"
                f"* Срок покупки: **30** дней\n"
                f"* Куплена раз: **{count}**"
            )
            
            container_items.append(discord.ui.TextDisplay(content=clamp_text(block)))
        
        container_items.append(discord.ui.Separator())
        container_items.append(discord.ui.TextDisplay(content=f"-# Страница {page} из {total_pages}"))
        
        if rows:
            for row_items in rows:
                container_items.append(row_items)
        
        view = discord.ui.LayoutView(timeout=None)
        container = discord.ui.Container()
        
        for item in container_items:
            container.add_item(item)
        
        view.add_item(container)
        return view

    async def shop_page_view(self, root_interaction, roles, page, total_pages, thumbnail_url):
        # Удаляем дубликаты перед показом
        self.fix_shop_duplicates()
        
        # Заново получаем роли после удаления дубликатов
        roles = unique_shop_roles(await maybe_await(self.db.get_shop_roles()))
        
        if not roles:
            return self.build_view(
                "Магазин личных ролей",
                "В магазине пока нет ролей!\n\nХочешь создать свою личную роль?\nТогда используй команду `/role create`",
                thumbnail_url=thumbnail_url
            )
        
        total_pages = math.ceil(len(roles) / 5)
        if page > total_pages:
            page = total_pages
        
        page_roles = roles[(page - 1) * 5:page * 5]
        buy_buttons = []

        for index, _role_data in enumerate(page_roles):
            button_num = (page - 1) * 5 + index + 1

            async def buy_callback(btn_interaction, role_index=button_num - 1):
                await btn_interaction.response.defer()
                if btn_interaction.user.id != root_interaction.user.id:
                    return
                await self.try_buy_role(root_interaction, btn_interaction, roles, role_index)

            buy_buttons.append(
                self.button(
                    label=str(button_num),
                    custom_id=f"shop_buy_{button_num}",
                    callback=buy_callback,
                )
            )

        async def back_callback(btn_interaction):
            await btn_interaction.response.defer()
            if btn_interaction.user.id != root_interaction.user.id:
                return
            if page > 1:
                await btn_interaction.message.edit(
                    view=await self.shop_page_view(root_interaction, roles, page - 1, total_pages, thumbnail_url),
                    allowed_mentions=NO_MENTIONS,
                )

        async def delete_callback(btn_interaction):
            await btn_interaction.response.defer()
            if btn_interaction.user.id == root_interaction.user.id:
                await btn_interaction.message.delete()

        async def next_callback(btn_interaction):
            await btn_interaction.response.defer()
            if btn_interaction.user.id != root_interaction.user.id:
                return
            if page < total_pages:
                await btn_interaction.message.edit(
                    view=await self.shop_page_view(root_interaction, roles, page + 1, total_pages, thumbnail_url),
                    allowed_mentions=NO_MENTIONS,
                )

        rows = []
        
        if buy_buttons:
            rows.append(self.row(*buy_buttons))
            rows.append(discord.ui.Separator())

        nav_row = self.row(
            self.button(
                emoji=discord.PartialEmoji(name="left", id=1515638771071324250),
                custom_id="shop_back",
                callback=back_callback,
                disabled=(page <= 1),
            ),
            self.button(
                emoji=discord.PartialEmoji(name="del", id=1515639124256751676),
                custom_id="shop_delete",
                callback=delete_callback,
            ),
            self.button(
                emoji=discord.PartialEmoji(name="right", id=1515638675931795626),
                custom_id="shop_next",
                callback=next_callback,
                disabled=(page >= total_pages),
            ),
        )
        rows.append(nav_row)

        return await self.make_shop_view(page, total_pages, roles, rows=rows, thumbnail_url=thumbnail_url)

    async def try_buy_role(self, root_interaction, btn_interaction, roles, role_index):
        roles = unique_shop_roles(roles)

        if role_index < 0 or role_index >= len(roles):
            await btn_interaction.followup.send(
                view=self.build_view("Ошибка", "Товар не найден!"),
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )
            return

        owner_id, role_id, cost, _count, _days_left = normalize_role_data(roles[role_index])
        role = discord.utils.get(self.guild.roles, id=role_id) if self.guild else None
        seller = self.guild.get_member(owner_id) if self.guild else None
        buyer = root_interaction.user
        bot_member = self.guild.me if self.guild else None

        if role is None:
            await btn_interaction.followup.send(
                view=self.build_view("Ошибка", "Эта роль больше не существует!"),
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )
            return

        if owner_id == buyer.id:
            await btn_interaction.followup.send(
                view=self.build_view(
                    "Магазин личных ролей",
                    "Нельзя купить свою личную роль.",
                    image_url=SHOP_IMAGE,
                ),
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )
            return

        if bot_member is not None and role >= bot_member.top_role:
            await btn_interaction.followup.send(
                view=self.build_view(
                    "Ошибка",
                    "Бот не может выдать эту роль, потому что она стоит выше роли бота.",
                    image_url=SHOP_IMAGE,
                ),
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )
            return

        if role in buyer.roles:
            await btn_interaction.followup.send(
                view=self.build_view(
                    "Магазин личных ролей",
                    f"У вас уже есть роль {role.mention}",
                    image_url=SHOP_IMAGE,
                ),
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )
            return

        if await maybe_await(self.db.is_role_rented_by_user(role.id, buyer.id)):
            await btn_interaction.followup.send(
                view=self.build_view(
                    "Магазин личных ролей",
                    f"У вас уже активна покупка роли {role.mention}",
                    image_url=SHOP_IMAGE,
                ),
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )
            return

        balance = await maybe_await(self.db.get_balance(buyer.id))
        if balance < cost:
            await btn_interaction.followup.send(
                view=self.build_view(
                    "Упс...",
                    "У вас недостаточно средств! Для начала пополните свой баланс.",
                    image_url=SHOP_IMAGE,
                ),
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )
            return

        purchase_key = (buyer.id, role.id)
        confirm_message = None

        async def yes_callback(verify_interaction):
            await verify_interaction.response.defer()
            if verify_interaction.user.id != buyer.id:
                return

            if purchase_key in self.active_purchases:
                await verify_interaction.followup.send(
                    view=self.build_view("Магазин личных ролей", "Покупка уже обрабатывается."),
                    ephemeral=True,
                    allowed_mentions=NO_MENTIONS,
                )
                return

            self.active_purchases.add(purchase_key)
            try:
                # Проверяем все заново прямо перед оплатой.
                if not await maybe_await(self.db.is_role_in_shop(role.id)):
                    await verify_interaction.followup.send(
                        view=self.build_view(
                            "Ошибка",
                            "Эта роль больше не продается!",
                            image_url=SHOP_IMAGE,
                        ),
                        ephemeral=True,
                        allowed_mentions=NO_MENTIONS,
                    )
                    if confirm_message:
                        await confirm_message.delete()
                    return

                if role in buyer.roles:
                    await verify_interaction.followup.send(
                        view=self.build_view(
                            "Магазин личных ролей",
                            f"У вас уже есть роль {role.mention}",
                            image_url=SHOP_IMAGE,
                        ),
                        ephemeral=True,
                        allowed_mentions=NO_MENTIONS,
                    )
                    return

                if await maybe_await(self.db.is_role_rented_by_user(role.id, buyer.id)):
                    await verify_interaction.followup.send(
                        view=self.build_view(
                            "Магазин личных ролей",
                            f"У вас уже активна покупка роли {role.mention}",
                            image_url=SHOP_IMAGE,
                        ),
                        ephemeral=True,
                        allowed_mentions=NO_MENTIONS,
                    )
                    return

                if bot_member is not None and role >= bot_member.top_role:
                    await verify_interaction.followup.send(
                        view=self.build_view(
                            "Ошибка",
                            "Бот не может выдать эту роль, потому что она стоит выше роли бота.",
                            image_url=SHOP_IMAGE,
                        ),
                        ephemeral=True,
                        allowed_mentions=NO_MENTIONS,
                    )
                    return

                current_balance = await maybe_await(self.db.get_balance(buyer.id))
                if current_balance < cost:
                    await verify_interaction.followup.send(
                        view=self.build_view(
                            "Упс...",
                            "У вас недостаточно средств! Для начала пополните свой баланс.",
                            image_url=SHOP_IMAGE,
                        ),
                        ephemeral=True,
                        allowed_mentions=NO_MENTIONS,
                    )
                    return

                await buyer.add_roles(role)
                money_taken = await maybe_await(self.db.take_money(buyer.id, cost))
                if not money_taken:
                    try:
                        await buyer.remove_roles(role)
                    except Exception:
                        pass
                    raise RuntimeError("Не удалось списать средства за роль")

                if seller:
                    await maybe_await(self.db.give_money(seller.id, cost))
                    await maybe_await(self.db.write_new_transactions(seller, f"Продажа роли {role.name}", cost))

                await maybe_await(self.db.write_new_transactions(buyer, f"Покупка роли {role.name}", -cost))
                await maybe_await(self.db.add_role_rental(role.id, buyer.id, 30))
                await maybe_await(self.db.add_role_to_inventory(buyer.id, role.id, role.name, 30))
                await maybe_await(self.db.increment_role_purchase(role.id))

                seller_name = seller.mention if seller else f"Пользователь {owner_id}"
                success_view = self.build_view(
                    "Магазин личных ролей",
                    f"Вы успешно купили роль {role.mention} у {seller_name}\n\n"
                    f"Роль выдана на **30 дней**",
                    image_url=SHOP_IMAGE,
                )

                if confirm_message:
                    await confirm_message.edit(view=success_view, allowed_mentions=NO_MENTIONS)
            except Exception as e:
                logger.error(f"Ошибка при покупке роли: {e}")
                await verify_interaction.followup.send(
                    view=self.build_view(
                        "Ошибка",
                        f"Произошла ошибка при покупке: {str(e)}",
                        image_url=SHOP_IMAGE,
                    ),
                    ephemeral=True,
                    allowed_mentions=NO_MENTIONS,
                )
            finally:
                self.active_purchases.discard(purchase_key)

        async def no_callback(verify_interaction):
            await verify_interaction.response.defer()
            if verify_interaction.user.id == root_interaction.user.id and confirm_message:
                await confirm_message.delete()

        class VerifyView(discord.ui.LayoutView):
            async def on_timeout(self):
                if confirm_message:
                    try:
                        await confirm_message.delete()
                    except Exception:
                        pass

        verify_view = VerifyView(timeout=None)
        container = discord.ui.Container()

        content = (
            f"## Магазин личных ролей\n\n"
            f"Вы уверены что хотите купить роль {role.mention} за **{cost}** {COIN}\n\n"
            "Роль будет выдана на **30 дней**"
        )
        container.add_item(discord.ui.TextDisplay(content=clamp_text(content)))

        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(SHOP_IMAGE)))

        container.add_item(discord.ui.Separator())
        row = discord.ui.ActionRow()
        row.add_item(self.button(label="Да", callback=yes_callback))
        row.add_item(self.button(label="Нет", callback=no_callback))
        container.add_item(row)

        verify_view.add_item(container)

        confirm_message = await btn_interaction.followup.send(
            view=verify_view,
            ephemeral=True,
            allowed_mentions=NO_MENTIONS,
            wait=True,
        )

    @app_commands.command(name="shop", description="Магазин личных ролей.")
    @app_commands.guilds(discord.Object(id=guild_id_cmd))
    async def shop(self, interaction: discord.Interaction):
        await interaction.response.defer()

        if self.guild is None:
            self.guild = interaction.guild

        server_avatar_url = str(self.guild.icon.url) if self.guild and self.guild.icon else None

        # Удаляем дубликаты перед показом
        self.fix_shop_duplicates()
        
        roles = unique_shop_roles(await maybe_await(self.db.get_shop_roles()))

        if not roles:
            await interaction.edit_original_response(
                view=self.build_view(
                    "Магазин личных ролей", 
                    "В магазине пока нет ролей!\n\nХочешь создать свою личную роль?\nТогда используй команду `/role create`",
                    thumbnail_url=server_avatar_url
                ),
                allowed_mentions=NO_MENTIONS,
            )
            return

        total_pages = math.ceil(len(roles) / 5)
        await interaction.edit_original_response(
            view=await self.shop_page_view(interaction, roles, 1, total_pages, server_avatar_url),
            allowed_mentions=NO_MENTIONS,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Shop(bot))