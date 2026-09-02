import discord
from discord.ext import commands
from discord import app_commands
import json
import math
from datetime import datetime
import inspect

from modules.Database import Database


# =====================================================
# EMOJIS (твои кастомные)
# =====================================================
LEFT_EMOJI = discord.PartialEmoji(name="left", id=1515638771071324250)
RIGHT_EMOJI = discord.PartialEmoji(name="right", id=1515638675931795626)
DELETE_EMOJI = discord.PartialEmoji(name="del", id=1515639124256751676)
REFRESH_EMOJI = discord.PartialEmoji(name="res", id=1515640889782046800)
NO_MENTIONS = discord.AllowedMentions.none()


# =====================================================
# UTILS
# =====================================================
async def maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


# =====================================================
# COG
# =====================================================
class Inventory(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database()
        self.guild = None

        with open("./assets/settings.json", "r", encoding="utf8") as f:
            data = json.load(f)

        self.guild_id = data.get("guild_id")

    # =====================================================
    # READY
    # =====================================================
    @commands.Cog.listener()
    async def on_ready(self):
        self.guild = discord.utils.get(self.bot.guilds, id=self.guild_id)

    def cog_unload(self):
        if hasattr(self.db, "close"):
            self.db.close()

    # =====================================================
    # VIEW BUILDER (V2)
    # =====================================================
    def build_view(self, title, description, *, footer=None, rows=None):
        view = discord.ui.LayoutView(timeout=None)
        container = discord.ui.Container()

        container.add_item(discord.ui.TextDisplay(content=f"## {title}"))

        if description:
            container.add_item(discord.ui.TextDisplay(content=description))

        if footer:
            container.add_item(discord.ui.TextDisplay(content=f"-# {footer}"))

        if rows:
            container.add_item(discord.ui.Separator())

            for row_items in rows:
                row = discord.ui.ActionRow()
                for item in row_items:
                    row.add_item(item)
                container.add_item(row)

        view.add_item(container)
        return view

    # =====================================================
    # FORMAT DATA
    # =====================================================
    def format_date(self, value):
        try:
            if isinstance(value, str):
                value = datetime.fromisoformat(value)
            return value.strftime("%d.%m.%Y")
        except:
            return "Неизвестно"

    async def clean_inventory(self, user_id: int, guild: discord.Guild):
        """Удаляет из инвентаря роли, которые больше не существуют на сервере"""
        if guild is None:
            return 0

        items = await maybe_await(self.db.get_user_inventory(user_id))
        deleted_count = 0
        
        for item in items:
            role_id = item.get("role_id")
            role = guild.get_role(role_id)
            
            # Если роль не найдена на сервере - удаляем из инвентаря
            if role is None:
                await maybe_await(self.db.remove_role_from_inventory(user_id, role_id))
                deleted_count += 1
        
        return deleted_count

    async def build_inventory_text(self, page, items, guild, user_id):
        # Сначала очищаем инвентарь от несуществующих ролей
        await self.clean_inventory(user_id, guild)
        
        # Заново получаем инвентарь после очистки
        items = await maybe_await(self.db.get_user_inventory(user_id))
        
        if not items:
            return "У вас нет купленных ролей."

        page_items = items[(page - 1) * 5:page * 5]

        if not page_items:
            return "У вас нет купленных ролей."

        lines = []

        for i, item in enumerate(page_items):
            role = guild.get_role(item.get("role_id"))
            role_name = item.get("role_name", "Неизвестно")

            mention = role.mention if role else f"~~{role_name}~~ (удалена)"
            days = int(item.get("days_left", 0) or 0)

            status = "Активна" if days > 0 else "Истекла"
            days_text = f"{days} дн." if days > 0 else "Срок истёк"

            number = (page - 1) * 5 + i + 1

            # Если роль удалена - показываем с зачёркиванием
            if role is None:
                lines.append(
                    f"**{number}.** ~~{role_name}~~ **(удалена)**\n"
                    f"> Название: **~~{role_name}~~**\n"
                    f"> Куплена: **{self.format_date(item.get('purchase_date'))}**\n"
                    f"> Осталось: **{days_text}**\n"
                    f"> Статус: Роль удалена"
                )
            else:
                lines.append(
                    f"**{number}.** {mention}\n"
                    f"> Название: **{role_name}**\n"
                    f"> Куплена: **{self.format_date(item.get('purchase_date'))}**\n"
                    f"> Осталось: **{days_text}**\n"
                    f"> Статус: {status}"
                )

        return "\n\n".join(lines)

    # =====================================================
    # PAGINATION VIEW
    # =====================================================
    async def build_page(self, root, page, total_pages, items, guild):

        # Очищаем инвентарь от несуществующих ролей перед показом
        await self.clean_inventory(root.user.id, guild)
        
        # Заново получаем инвентарь после очистки
        items = await maybe_await(self.db.get_user_inventory(root.user.id))
        
        if not items:
            return self.build_view(
                f"Инвентарь — {root.user.display_name}",
                "У вас нет купленных ролей."
            )

        # Пересчитываем страницы
        new_total_pages = math.ceil(len(items) / 5)
        if page > new_total_pages:
            page = new_total_pages

        description = await self.build_inventory_text(page, items, guild, root.user.id)

        # =====================================================
        # КНОПКИ (все серые, в одной строке)
        # =====================================================
        back_btn = discord.ui.Button(
            emoji=LEFT_EMOJI,
            style=discord.ButtonStyle.secondary,
            disabled=(page <= 1)
        )

        refresh_btn = discord.ui.Button(
            emoji=REFRESH_EMOJI,
            style=discord.ButtonStyle.secondary
        )

        close_btn = discord.ui.Button(
            emoji=DELETE_EMOJI,
            style=discord.ButtonStyle.secondary
        )

        next_btn = discord.ui.Button(
            emoji=RIGHT_EMOJI,
            style=discord.ButtonStyle.secondary,
            disabled=(page >= new_total_pages)
        )

        # =====================================================
        # CALLBACKS
        # =====================================================
        async def back(i: discord.Interaction):
            await i.response.defer()
            if i.user.id != root.user.id:
                return
            new_page = max(page - 1, 1)
            await i.message.edit(
                view=await self.build_page(root, new_page, new_total_pages, items, guild),
                allowed_mentions=NO_MENTIONS,
            )

        async def next_page(i: discord.Interaction):
            await i.response.defer()
            if i.user.id != root.user.id:
                return
            new_page = min(page + 1, new_total_pages)
            await i.message.edit(
                view=await self.build_page(root, new_page, new_total_pages, items, guild),
                allowed_mentions=NO_MENTIONS,
            )

        async def close(i: discord.Interaction):
            await i.response.defer()
            if i.user.id != root.user.id:
                return
            await i.message.delete()

        async def refresh(i: discord.Interaction):
            await i.response.defer()
            if i.user.id != root.user.id:
                return

            # Очищаем инвентарь и обновляем
            await self.clean_inventory(root.user.id, guild)
            new_items = await maybe_await(self.db.get_user_inventory(root.user.id))

            if not new_items:
                await i.message.edit(
                    view=self.build_view(
                        "Инвентарь",
                        "Инвентарь пуст."
                    ),
                    allowed_mentions=NO_MENTIONS,
                )
                return

            new_total = math.ceil(len(new_items) / 5)

            await i.message.edit(
                view=await self.build_page(
                    root,
                    min(page, new_total),
                    new_total,
                    new_items,
                    guild
                ),
                allowed_mentions=NO_MENTIONS,
            )

        # Назначаем callbacks
        back_btn.callback = back
        next_btn.callback = next_page
        close_btn.callback = close
        refresh_btn.callback = refresh

        # =====================================================
        # ОДНА СТРОКА со всеми кнопками
        # =====================================================
        rows = [
            [back_btn, refresh_btn, close_btn, next_btn]
        ]

        return self.build_view(
            f"Инвентарь — {root.user.display_name}",
            description,
            footer=f"Страница {page}/{new_total_pages}",
            rows=rows
        )

    # =====================================================
    # COMMAND
    # =====================================================
    @app_commands.command(name="inventory", description="Показать инвентарь")
    async def inventory(self, interaction: discord.Interaction):

        await interaction.response.defer()

        # Очищаем инвентарь от несуществующих ролей
        await self.clean_inventory(interaction.user.id, interaction.guild)

        items = await maybe_await(self.db.get_user_inventory(interaction.user.id))

        if not items:
            return await interaction.edit_original_response(
                view=self.build_view(
                    f"Инвентарь — {interaction.user.display_name}",
                    "У вас нет купленных ролей."
                ),
                allowed_mentions=NO_MENTIONS,
            )

        total_pages = math.ceil(len(items) / 5)

        await interaction.edit_original_response(
            view=await self.build_page(
                interaction,
                1,
                total_pages,
                items,
                interaction.guild
            ),
            allowed_mentions=NO_MENTIONS,
        )


# =====================================================
# SETUP
# =====================================================
async def setup(bot: commands.Bot):
    await bot.add_cog(Inventory(bot))