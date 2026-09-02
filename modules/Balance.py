import math
from datetime import datetime
import inspect

import discord
from discord import app_commands
from discord.ext import commands

from modules.Logger import *
from modules.Database import Database
from modules.Utils import Utils

guild_id_cmd = Utils.get_guild_id()

BANNER_URL = "https://cdn.discordapp.com/attachments/992883178362642453/1029462389130792970/-1.png"
NO_MENTIONS = discord.AllowedMentions.none()

MONTHS = [
    "янв.", "фев.", "мар.", "апр.",
    "май", "июн.", "июл.", "авг.",
    "сен.", "окт.", "ноя.", "дек.",
]


async def maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def clamp_text(value, limit=3800):
    value = "" if value is None else str(value)
    return value if len(value) <= limit else value[: limit - 3] + "..."


class Balance(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database()

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("/balance - start")

    # =====================================================
    # ХЕЛПЕРЫ COMPONENTS V2
    # =====================================================

    def _build_view(self, content: str, *, thumbnail_url: str = None, image_url: str = None, rows=None, timeout=120):
        """Создает LayoutView с поддержкой thumbnail (аватара) в правом верхнем углу"""
        view = discord.ui.LayoutView(timeout=timeout)
        container = discord.ui.Container()

        # Добавляем текст с thumbnail (аватаром) в правом верхнем углу
        if thumbnail_url:
            container.add_item(
                discord.ui.Section(
                    discord.ui.TextDisplay(content=clamp_text(content)),
                    accessory=discord.ui.Thumbnail(thumbnail_url),
                )
            )
        else:
            container.add_item(discord.ui.TextDisplay(content=clamp_text(content)))

        # Добавляем изображение если есть
        if image_url:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(image_url)))

        # Добавляем кнопки если есть
        if rows:
            container.add_item(discord.ui.Separator())
            # rows может быть списком ActionRow или одним ActionRow
            if isinstance(rows, list):
                for row_items in rows:
                    if isinstance(row_items, discord.ui.ActionRow):
                        container.add_item(row_items)
                    else:
                        # Если это список кнопок, создаем ActionRow
                        row = discord.ui.ActionRow()
                        for item in row_items:
                            row.add_item(item)
                        container.add_item(row)
            elif isinstance(rows, discord.ui.ActionRow):
                container.add_item(rows)
            else:
                # Если это просто список кнопок
                row = discord.ui.ActionRow()
                for item in rows:
                    row.add_item(item)
                container.add_item(row)

        view.add_item(container)
        return view

    def _action_row(self, *buttons) -> discord.ui.ActionRow:
        row = discord.ui.ActionRow()
        for btn in buttons:
            row.add_item(btn)
        return row

    def _is_author(self, interaction: discord.Interaction, author_id: int) -> bool:
        return interaction.user.id == author_id

    def _format_transactions(self, page: int, total_pages: int, transactions) -> str:
        """Форматирует транзакции для отображения"""
        page_transactions = transactions[(page - 1) * 10: page * 10]
        lines = ["## История транзакций", ""]

        for member_id, reason, amount, created_at in page_transactions:
            # Проверяем тип created_at и конвертируем если нужно
            if isinstance(created_at, datetime):
                date = created_at
            elif isinstance(created_at, str):
                try:
                    # Пробуем парсить строку как datetime
                    date = datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S')
                except:
                    date = datetime.now()
            else:
                date = datetime.now()
            
            # Определяем знак суммы
            sign = "+" if amount > 0 else ""
            
            lines.append(
                f"<:__:1519299448113463326> {reason} "
                f"**[{date.day:02} {MONTHS[date.month - 1]}, {date.hour:02}:{date.minute:02}]**\n"
                f"Сумма: **{sign}{amount}** <:coin:1515637898735652924>\n"
            )

        lines.append(f"\n*Страница {page} из {total_pages}*")
        return "\n".join(lines)

    def _balance_text(self, member: discord.Member, amount) -> str:
        return (
            f"## Текущий баланс — {member.display_name}\n\n"
            f"> Монеты <:coin:1515637898735652924>\n"
            f"```\n{amount}\n```"
        )

    def _transactions_text(self, member: discord.Member, transactions) -> str:
        if not transactions:
            return f"## История транзакций — {member.display_name}\n\nУ пользователя нет транзакций."
        return f"## История транзакций — {member.display_name}"

    # =====================================================
    # ЭКРАНЫ
    # =====================================================

    def _readonly_balance_view(self, member: discord.Member, amount):
        """Баланс другого пользователя — без кнопок."""
        return self._build_view(
            self._balance_text(member, amount),
            thumbnail_url=str(member.display_avatar.url),
        )

    def _readonly_transactions_view(self, member: discord.Member, transactions, page: int, total_pages: int):
        """Транзакции другого пользователя — только просмотр."""
        cog = self

        async def prev_cb(interaction: discord.Interaction):
            if not cog._is_author(interaction, member.id):
                return
            await interaction.response.defer()
            new_page = max(page - 1, 1)
            await interaction.message.edit(
                view=cog._readonly_transactions_view(
                    member, transactions, new_page, total_pages
                )
            )

        async def next_cb(interaction: discord.Interaction):
            if not cog._is_author(interaction, member.id):
                return
            await interaction.response.defer()
            new_page = min(page + 1, total_pages)
            await interaction.message.edit(
                view=cog._readonly_transactions_view(
                    member, transactions, new_page, total_pages
                )
            )

        async def delete_cb(interaction: discord.Interaction):
            if not cog._is_author(interaction, member.id):
                return
            await interaction.response.defer()
            await interaction.message.delete()

        # Создаем кнопки без timeout
        btn_prev = discord.ui.Button(
            emoji=discord.PartialEmoji(name="left", id=1515638771071324250),
            style=discord.ButtonStyle.secondary,
            disabled=(page <= 1)
        )
        btn_prev.callback = prev_cb

        btn_delete = discord.ui.Button(
            emoji=discord.PartialEmoji(name="del", id=1515639124256751676),
            style=discord.ButtonStyle.secondary
        )
        btn_delete.callback = delete_cb

        btn_next = discord.ui.Button(
            emoji=discord.PartialEmoji(name="right", id=1515638675931795626),
            style=discord.ButtonStyle.secondary,
            disabled=(page >= total_pages)
        )
        btn_next.callback = next_cb

        return self._build_view(
            cog._format_transactions(page, total_pages, transactions),
            thumbnail_url=str(member.display_avatar.url),
            rows=self._action_row(btn_prev, btn_delete, btn_next),
        )

    def _own_balance_view(
        self,
        author: discord.Member,
        panel_message: discord.Message,
    ):
        cog = self
        amount = self.db.get_balance(author.id)

        async def transactions_cb(interaction: discord.Interaction):
            if not cog._is_author(interaction, author.id):
                return
            await interaction.response.defer()

            transactions = cog.db.get_user_transactions(author)
            total_pages = max(1, math.ceil(len(transactions) / 10)) if transactions else 1

            await panel_message.edit(
                view=cog._transactions_view(
                    author, panel_message, transactions, 1, total_pages
                )
            )

        async def delete_cb(interaction: discord.Interaction):
            if not cog._is_author(interaction, author.id):
                return
            await interaction.response.defer()
            await panel_message.delete()

        btn_transactions = discord.ui.Button(
            label="Транзакции",
            style=discord.ButtonStyle.secondary,
            custom_id="button_transactions_balance"
        )
        btn_transactions.callback = transactions_cb

        btn_delete = discord.ui.Button(
            emoji=discord.PartialEmoji(name="del", id=1515639124256751676),
            style=discord.ButtonStyle.secondary,
            custom_id="button_delete_balance"
        )
        btn_delete.callback = delete_cb

        return self._build_view(
            self._balance_text(author, amount),
            thumbnail_url=str(author.display_avatar.url),
            image_url=BANNER_URL,
            rows=self._action_row(btn_transactions, btn_delete),
        )

    def _transactions_view(
        self,
        author: discord.Member,
        panel_message: discord.Message | None,
        transactions,
        page: int,
        total_pages: int,
    ):
        cog = self

        async def back_balance_cb(interaction: discord.Interaction):
            if not cog._is_author(interaction, author.id):
                return
            await interaction.response.defer()
            if panel_message:
                await panel_message.edit(
                    view=cog._own_balance_view(author, panel_message)
                )

        async def prev_cb(interaction: discord.Interaction):
            if not cog._is_author(interaction, author.id):
                return
            await interaction.response.defer()
            new_page = max(page - 1, 1)
            if panel_message:
                await panel_message.edit(
                    view=cog._transactions_view(
                        author, panel_message, transactions, new_page, total_pages
                    )
                )
            else:
                await interaction.message.edit(
                    view=cog._transactions_view(
                        author, None, transactions, new_page, total_pages
                    )
                )

        async def delete_cb(interaction: discord.Interaction):
            if not cog._is_author(interaction, author.id):
                return
            await interaction.response.defer()
            if panel_message:
                await panel_message.delete()
            else:
                await interaction.message.delete()

        async def next_cb(interaction: discord.Interaction):
            if not cog._is_author(interaction, author.id):
                return
            await interaction.response.defer()
            new_page = min(page + 1, total_pages)
            if panel_message:
                await panel_message.edit(
                    view=cog._transactions_view(
                        author, panel_message, transactions, new_page, total_pages
                    )
                )
            else:
                await interaction.message.edit(
                    view=cog._transactions_view(
                        author, None, transactions, new_page, total_pages
                    )
                )

        # Создаем кнопки
        buttons = []
        
        # Кнопка "Назад" только если есть panel_message (вызвано из баланса)
        if panel_message:
            btn_back_balance = discord.ui.Button(
                label="Назад",
                emoji=discord.PartialEmoji(name="left", id=1515638771071324250)
            )
            btn_back_balance.callback = back_balance_cb
            buttons.append(btn_back_balance)

        # Кнопка назад (перелистывание)
        btn_prev = discord.ui.Button(
            emoji=discord.PartialEmoji(name="left", id=1515638771071324250),
            style=discord.ButtonStyle.secondary,
            disabled=(page <= 1)
        )
        btn_prev.callback = prev_cb
        buttons.append(btn_prev)

        # Кнопка удаления
        btn_delete = discord.ui.Button(
            emoji=discord.PartialEmoji(name="del", id=1515639124256751676),
            style=discord.ButtonStyle.secondary
        )
        btn_delete.callback = delete_cb
        buttons.append(btn_delete)

        # Кнопка вперед (перелистывание)
        btn_next = discord.ui.Button(
            emoji=discord.PartialEmoji(name="right", id=1515638675931795626),
            style=discord.ButtonStyle.secondary,
            disabled=(page >= total_pages)
        )
        btn_next.callback = next_cb
        buttons.append(btn_next)

        return self._build_view(
            cog._format_transactions(page, total_pages, transactions),
            thumbnail_url=str(author.display_avatar.url),
            rows=self._action_row(*buttons),
        )

    # =====================================================
    # КОМАНДА /balance
    # =====================================================

    @app_commands.command(name="balance", description="Посмотреть баланс.")
    @app_commands.describe(пользователь="Выберите пользователя")
    @app_commands.guilds(discord.Object(id=guild_id_cmd))
    async def balance(
        self,
        interaction: discord.Interaction,
        пользователь: discord.Member | None = None,
    ):
        await interaction.response.defer()

        target = пользователь or interaction.user

        if пользователь:
            # Чужой баланс — только просмотр
            amount = self.db.get_balance(пользователь.id)
            await interaction.followup.send(
                view=self._readonly_balance_view(пользователь, amount),
                allowed_mentions=NO_MENTIONS,
            )
            return

        # Свой баланс — с кнопками
        panel_message = await interaction.followup.send(
            view=self._build_view(
                self._balance_text(
                    interaction.user,
                    self.db.get_balance(interaction.user.id),
                ),
                thumbnail_url=str(interaction.user.display_avatar.url),
            ),
            allowed_mentions=NO_MENTIONS,
            wait=True,
        )

        await panel_message.edit(
            view=self._own_balance_view(interaction.user, panel_message)
        )

    # =====================================================
    # КОМАНДА /transactions
    # =====================================================

    @app_commands.command(name="transactions", description="Посмотреть историю транзакций.")
    @app_commands.describe(пользователь="Выберите пользователя")
    @app_commands.guilds(discord.Object(id=guild_id_cmd))
    async def transactions(
        self,
        interaction: discord.Interaction,
        пользователь: discord.Member | None = None,
    ):
        await interaction.response.defer()

        target = пользователь or interaction.user
        transactions_list = self.db.get_user_transactions(target)

        # Если транзакций нет
        if not transactions_list:
            await interaction.followup.send(
                view=self._build_view(
                    self._transactions_text(target, transactions_list),
                    thumbnail_url=str(target.display_avatar.url),
                ),
                allowed_mentions=NO_MENTIONS,
            )
            return

        total_pages = max(1, math.ceil(len(transactions_list) / 10))

        if пользователь:
            # Чужие транзакции — только просмотр
            await interaction.followup.send(
                view=self._readonly_transactions_view(
                    target, transactions_list, 1, total_pages
                ),
                allowed_mentions=NO_MENTIONS,
            )
        else:
            # Свои транзакции — без кнопки "Назад"
            await interaction.followup.send(
                view=self._transactions_view(
                    target, None, transactions_list, 1, total_pages
                ),
                allowed_mentions=NO_MENTIONS,
            )

    # =====================================================
    # КОМАНДА /economy-reset
    # =====================================================

    @app_commands.command(name="economy-reset", description="Очистить баланс всех пользователей (0 монет).")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guilds(discord.Object(id=guild_id_cmd))
    async def economy_reset(self, interaction: discord.Interaction):
        """Сбрасывает баланс всех пользователей до 0 монет. Доступно только администраторам."""
        # Проверка прав администратора
        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title="Ошибка",
                description="У вас недостаточно прав для выполнения этой команды.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Запрос подтверждения
        embed_confirm = discord.Embed(
            title="Подтверждение сброса экономики",
            description=(
                "Вы уверены, что хотите очистить баланс всех пользователей до 0 монет?\n\n"
                "Это действие необратимо и затронет всех участников сервера."
            ),
            color=discord.Color.orange()
        )

        # Создаем кнопки подтверждения
        view = discord.ui.View(timeout=60)

        async def confirm_callback(interaction_confirm: discord.Interaction):
            if interaction_confirm.user.id != interaction.user.id:
                await interaction_confirm.response.send_message(
                    "Эта команда не для вас!", 
                    ephemeral=True
                )
                return

            await interaction_confirm.response.defer()
            
            try:
                # Сбрасываем баланс всех пользователей
                reset_count = self.db.reset_all_balances()
                
                # Логируем действие
                logger.info(f"Администратор {interaction.user.name} ({interaction.user.id}) сбросил экономику. Затронуто {reset_count} пользователей.")
                
                embed_success = discord.Embed(
                    title="Экономика сброшена",
                    description=f"Баланс **{reset_count}** пользователей успешно сброшен до 0 монет.",
                    color=discord.Color.green()
                )
                embed_success.set_footer(text=f"Действие выполнено: {interaction.user.name}")
                
                await interaction_confirm.edit_original_response(embed=embed_success, view=None)
                
            except Exception as e:
                logger.error(f"Ошибка при сбросе экономики: {e}")
                embed_error = discord.Embed(
                    title="Ошибка",
                    description="Произошла ошибка при сбросе баланса. Попробуйте позже.",
                    color=discord.Color.red()
                )
                await interaction_confirm.edit_original_response(embed=embed_error, view=None)

        async def cancel_callback(interaction_cancel: discord.Interaction):
            if interaction_cancel.user.id != interaction.user.id:
                await interaction_cancel.response.send_message(
                    "Эта команда не для вас!", 
                    ephemeral=True
                )
                return
            
            embed_cancel = discord.Embed(
                title="Отменено",
                description="Сброс экономики был отменен.",
                color=discord.Color.blue()
            )
            await interaction_cancel.response.edit_message(embed=embed_cancel, view=None)

        confirm_button = discord.ui.Button(
            label="Подтвердить",
            style=discord.ButtonStyle.danger
        )
        confirm_button.callback = confirm_callback

        cancel_button = discord.ui.Button(
            label="Отмена",
            style=discord.ButtonStyle.secondary
        )
        cancel_button.callback = cancel_callback

        view.add_item(confirm_button)
        view.add_item(cancel_button)

        await interaction.response.send_message(embed=embed_confirm, view=view, ephemeral=True)


# =====================================================
# SETUP
# =====================================================
async def setup(bot: commands.Bot):
    await bot.add_cog(Balance(bot))