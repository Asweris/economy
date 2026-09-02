from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from modules.Database import Database
from modules.Logger import *
from modules.Utils import Utils


guild_id_cmd = Utils.get_guild_id()
NO_MENTIONS = discord.AllowedMentions.none()
COIN = "<:coin:1515637898735652924>"

WIN_SCORE = 3
MIN_BET = 50
TIMEOUT_SECONDS = 300

CHOICES = {
    "rock": "Камень",
    "scissors": "Ножницы",
    "paper": "Бумага",
}

BEATS = {
    "rock": "scissors",
    "scissors": "paper",
    "paper": "rock",
}


def clamp_text(value, limit=3800):
    value = "" if value is None else str(value)
    return value if len(value) <= limit else value[: limit - 3] + "..."


def notice_view(title: str, description: str):
    view = discord.ui.LayoutView(timeout=60)
    container = discord.ui.Container()
    container.add_item(discord.ui.TextDisplay(content=clamp_text(f"## {title}\n\n{description}")))
    view.add_item(container)
    return view


class RpsSession:
    def __init__(self, cog: RockPaperScissors, challenger: discord.Member, opponent: discord.Member, amount: int):
        self.cog = cog
        self.challenger = challenger
        self.opponent = opponent
        self.amount = amount
        self.pot = amount * 2
        self.pot_paid = False
        self.scores = {
            challenger.id: 0,
            opponent.id: 0,
        }
        self.choices = {}
        self.round_number = 1
        self.state = "invite"
        self.last_result = f"{opponent.mention}, подтвердите участие в матче."
        self.message: discord.Message | None = None
        self.timeout_task: asyncio.Task | None = None

    @property
    def players(self):
        return self.challenger, self.opponent

    @property
    def is_over(self):
        return self.state in {"finished", "cancelled"}

    def is_player(self, user: discord.abc.User) -> bool:
        return user.id in self.scores

    def other_player(self, user: discord.abc.User) -> discord.Member:
        return self.opponent if user.id == self.challenger.id else self.challenger

    def reset_timeout(self):
        if self.timeout_task and not self.timeout_task.done():
            self.timeout_task.cancel()
        self.timeout_task = self.cog.bot.loop.create_task(self.expire_after())

    async def expire_after(self):
        try:
            await asyncio.sleep(TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            return

        if self.is_over:
            return

        if self.pot_paid:
            await self.refund_bets("Возврат ставки в rps")
            self.last_result = "Матч завершен из-за бездействия. Ставки возвращены игрокам."
        else:
            self.last_result = "Вызов завершен из-за бездействия."

        self.state = "cancelled"
        self.close_session(cancel_timeout=False)

        if self.message:
            try:
                await self.message.edit(view=self.build_view(), allowed_mentions=NO_MENTIONS)
            except Exception as exc:
                logger.error(f"Не удалось обновить завершенный матч rps: {exc}")

    def close_session(self, *, cancel_timeout=True):
        if cancel_timeout and self.timeout_task and not self.timeout_task.done():
            self.timeout_task.cancel()
        self.cog.release_session(self)

    def score_text(self):
        return (
            f"{self.challenger.mention}: **{self.scores[self.challenger.id]}**\n"
            f"{self.opponent.mention}: **{self.scores[self.opponent.id]}**"
        )

    async def player_balance(self, member: discord.Member):
        return await self.cog.maybe_await(self.cog.db.get_balance(member.id))

    async def take_bets(self):
        for player in self.players:
            balance = await self.player_balance(player)
            if balance < self.amount:
                return False, f"У {player.mention} недостаточно средств для ставки **{self.amount}** {COIN}."

        paid_players = []
        for player in self.players:
            paid = await self.cog.maybe_await(self.cog.db.take_money(player.id, self.amount))
            if not paid:
                for paid_player in paid_players:
                    await self.cog.maybe_await(self.cog.db.give_money(paid_player.id, self.amount))
                return False, "Не удалось списать ставку. Попробуйте начать матч заново."
            paid_players.append(player)

        for player in self.players:
            await self.cog.maybe_await(self.cog.db.write_new_transactions(player, "Ставка в rps", -self.amount))

        self.pot_paid = True
        return True, None

    async def refund_bets(self, reason: str):
        if not self.pot_paid:
            return

        for player in self.players:
            await self.cog.maybe_await(self.cog.db.give_money(player.id, self.amount))
            await self.cog.maybe_await(self.cog.db.write_new_transactions(player, reason, self.amount))

        self.pot_paid = False

    async def pay_winner(self, winner: discord.Member):
        if not self.pot_paid:
            return

        await self.cog.maybe_await(self.cog.db.give_money(winner.id, self.pot))
        await self.cog.maybe_await(self.cog.db.write_new_transactions(winner, "Победа в rps", self.amount))
        self.pot_paid = False

    def choice_status(self, member: discord.Member):
        if member.id in self.choices:
            return "**выбор сделан**"
        return "ожидает выбор"

    def status_text(self):
        if self.state == "invite":
            return (
                "**Формат:** до **3** побед\n"
                f"**Ставка:** **{self.amount}** {COIN} с каждого\n"
                f"**Банк:** **{self.pot}** {COIN}\n"
                f"**Вызов:** {self.challenger.mention} против {self.opponent.mention}\n"
                f"**Статус:** {self.last_result}"
            )

        if self.state == "playing":
            return (
                f"**Раунд:** {self.round_number}\n"
                f"**Последний итог:** {self.last_result}\n\n"
                "**Выбор игроков:**\n"
                f"{self.challenger.mention}: {self.choice_status(self.challenger)}\n"
                f"{self.opponent.mention}: {self.choice_status(self.opponent)}"
            )

        return self.last_result

    def make_button(self, label, callback, *, style=discord.ButtonStyle.secondary):
        button = discord.ui.Button(label=label, style=style)
        button.callback = callback
        return button

    def build_view(self):
        view = discord.ui.LayoutView(timeout=TIMEOUT_SECONDS)
        container = discord.ui.Container()

        container.add_item(discord.ui.TextDisplay(content="## Камень, ножницы, бумага"))
        container.add_item(discord.ui.Separator())
        container.add_item(
            discord.ui.TextDisplay(
                content=clamp_text(
                    f"**Счет матча**\n{self.score_text()}\n\n"
                    f"**Ставка:** {self.amount} {COIN}\n"
                    f"**Банк:** {self.pot} {COIN}"
                )
            )
        )
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(content=clamp_text(self.status_text())))

        rows = self.build_rows()
        if rows:
            container.add_item(discord.ui.Separator())
            for row in rows:
                container.add_item(row)

        container.add_item(discord.ui.Separator())
        container.add_item(
            discord.ui.TextDisplay(
                content="-# Выбор раскрывается только после хода обоих игроков."
            )
        )

        view.add_item(container)
        return view

    def build_rows(self):
        if self.state == "invite":
            return [
                self.cog.row(
                    self.make_button("Принять", self.accept, style=discord.ButtonStyle.secondary),
                    self.make_button("Отказаться", self.decline, style=discord.ButtonStyle.secondary),
                )
            ]

        if self.state == "playing":
            return [
                self.cog.row(
                    self.make_button("Камень", lambda i: self.choose(i, "rock")),
                    self.make_button("Ножницы", lambda i: self.choose(i, "scissors")),
                    self.make_button("Бумага", lambda i: self.choose(i, "paper")),
                ),
                self.cog.row(
                    self.make_button("Сдаться", self.surrender),
                ),
            ]

        return [
            self.cog.row(
                self.make_button("Закрыть", self.close_message),
            )
        ]

    async def send_private(self, interaction: discord.Interaction, title: str, description: str):
        if interaction.response.is_done():
            return await interaction.followup.send(
                view=notice_view(title, description),
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )
        return await interaction.response.send_message(
            view=notice_view(title, description),
            ephemeral=True,
            allowed_mentions=NO_MENTIONS,
        )

    async def accept(self, interaction: discord.Interaction):
        if interaction.user.id != self.opponent.id:
            return await self.send_private(interaction, "Матч", "Принять вызов может только приглашенный игрок.")
        if self.state != "invite":
            return await self.send_private(interaction, "Матч", "Этот вызов уже обработан.")

        self.state = "accepting"

        try:
            success, error_text = await self.take_bets()
        except Exception as exc:
            logger.error(f"Не удалось принять rps матч: {exc}")
            success = False
            error_text = "Не удалось списать ставку. Попробуйте начать матч заново."

        if not success:
            self.state = "cancelled"
            self.last_result = error_text
            self.close_session()
            await interaction.response.defer()
            await interaction.message.edit(view=self.build_view(), allowed_mentions=NO_MENTIONS)
            return

        self.state = "playing"
        self.last_result = f"Матч начался. Банк **{self.pot}** {COIN}. Оба игрока выбирают ход."
        self.reset_timeout()

        await interaction.response.defer()
        await interaction.message.edit(view=self.build_view(), allowed_mentions=NO_MENTIONS)

    async def decline(self, interaction: discord.Interaction):
        if interaction.user.id not in {self.challenger.id, self.opponent.id}:
            return await self.send_private(interaction, "Матч", "Эта кнопка доступна только участникам матча.")
        if self.state != "invite":
            return await self.send_private(interaction, "Матч", "Этот вызов уже обработан.")

        self.state = "cancelled"
        self.last_result = "Вызов отменен." if interaction.user.id == self.challenger.id else "Вызов отклонен."
        self.close_session()

        await interaction.response.defer()
        await interaction.message.edit(view=self.build_view(), allowed_mentions=NO_MENTIONS)

    async def choose(self, interaction: discord.Interaction, choice: str):
        if not self.is_player(interaction.user):
            return await self.send_private(interaction, "Матч", "Эта кнопка доступна только участникам матча.")
        if self.state != "playing":
            return await self.send_private(interaction, "Матч", "Сейчас выбор недоступен.")
        if interaction.user.id in self.choices:
            return await self.send_private(interaction, "Матч", "Вы уже сделали ход в этом раунде.")

        selected = CHOICES[choice]
        self.choices[interaction.user.id] = choice

        if len(self.choices) == 2:
            await self.resolve_round()
        else:
            self.last_result = f"Раунд {self.round_number}. Ожидаем второй ход."

        if self.is_over:
            self.close_session()
        else:
            self.reset_timeout()

        await interaction.response.defer(ephemeral=True)
        await interaction.message.edit(view=self.build_view(), allowed_mentions=NO_MENTIONS)
        await interaction.followup.send(
            view=notice_view("Ход принят", f"Ваш выбор: **{selected}**"),
            ephemeral=True,
            allowed_mentions=NO_MENTIONS,
        )

    async def resolve_round(self):
        first_choice = self.choices[self.challenger.id]
        second_choice = self.choices[self.opponent.id]
        current_round = self.round_number

        if first_choice == second_choice:
            self.last_result = (
                f"Раунд {current_round}: оба выбрали **{CHOICES[first_choice]}**. "
                "Ничья, очко не начислено."
            )
        else:
            winner = self.challenger if BEATS[first_choice] == second_choice else self.opponent
            self.scores[winner.id] += 1
            self.last_result = (
                f"Раунд {current_round}: {self.challenger.mention} - **{CHOICES[first_choice]}**, "
                f"{self.opponent.mention} - **{CHOICES[second_choice]}**. "
                f"Очко получает {winner.mention}."
            )

            if self.scores[winner.id] >= WIN_SCORE:
                self.state = "finished"
                self.last_result += f"\n\nПобедитель матча: {winner.mention}. Выигрыш: **{self.pot}** {COIN}."
                await self.pay_winner(winner)
                return

        self.round_number += 1
        self.choices.clear()

    async def surrender(self, interaction: discord.Interaction):
        if not self.is_player(interaction.user):
            return await self.send_private(interaction, "Матч", "Эта кнопка доступна только участникам матча.")
        if self.state != "playing":
            return await self.send_private(interaction, "Матч", "Сейчас это действие недоступно.")

        winner = self.other_player(interaction.user)
        self.scores[winner.id] = WIN_SCORE
        self.state = "finished"
        self.last_result = f"{interaction.user.mention} сдался. Победитель матча: {winner.mention}. Выигрыш: **{self.pot}** {COIN}."
        await self.pay_winner(winner)
        self.close_session()

        await interaction.response.defer()
        await interaction.message.edit(view=self.build_view(), allowed_mentions=NO_MENTIONS)

    async def close_message(self, interaction: discord.Interaction):
        if not self.is_player(interaction.user):
            return await self.send_private(interaction, "Матч", "Закрыть матч могут только его участники.")

        await interaction.response.defer()
        try:
            await interaction.message.delete()
        except Exception:
            pass


class RockPaperScissors(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database()
        self.active_sessions: dict[int, RpsSession] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("/rps - start")

    def row(self, *items):
        row = discord.ui.ActionRow()
        for item in items:
            row.add_item(item)
        return row

    async def maybe_await(self, value):
        if asyncio.iscoroutine(value) or hasattr(value, "__await__"):
            return await value
        return value

    async def respond(self, interaction, view, *, ephemeral=False):
        if interaction.response.is_done():
            return await interaction.followup.send(
                view=view,
                ephemeral=ephemeral,
                allowed_mentions=NO_MENTIONS,
            )
        return await interaction.response.send_message(
            view=view,
            ephemeral=ephemeral,
            allowed_mentions=NO_MENTIONS,
        )

    def release_session(self, session: RpsSession):
        for player in session.players:
            if self.active_sessions.get(player.id) is session:
                del self.active_sessions[player.id]

    def is_busy(self, member: discord.Member) -> bool:
        session = self.active_sessions.get(member.id)
        return bool(session and not session.is_over)

    @app_commands.command(name="rps", description="Камень, ножницы, бумага до 3 побед.")
    @app_commands.describe(opponent="Выберите соперника", amount="Ставка с каждого игрока.")
    @app_commands.rename(opponent="соперник")
    @app_commands.rename(amount="ставка")
    @app_commands.guilds(discord.Object(id=guild_id_cmd))
    async def rps(
        self,
        interaction: discord.Interaction,
        opponent: discord.Member,
        amount: app_commands.Range[int, MIN_BET, 999999],
    ):
        if opponent.bot:
            return await self.respond(
                interaction,
                notice_view("Матч", "Нельзя вызвать бота."),
                ephemeral=True,
            )

        if opponent.id == interaction.user.id:
            return await self.respond(
                interaction,
                notice_view("Матч", "Нельзя вызвать самого себя."),
                ephemeral=True,
            )

        if self.is_busy(interaction.user) or self.is_busy(opponent):
            return await self.respond(
                interaction,
                notice_view("Матч", "Один из игроков уже участвует в другом матче."),
                ephemeral=True,
            )

        challenger_balance = await self.maybe_await(self.db.get_balance(interaction.user.id))
        if challenger_balance < amount:
            return await self.respond(
                interaction,
                notice_view("Упс...", f"У вас недостаточно средств для ставки **{amount}** {COIN}."),
                ephemeral=True,
            )

        session = RpsSession(self, interaction.user, opponent, amount)
        self.active_sessions[interaction.user.id] = session
        self.active_sessions[opponent.id] = session

        await interaction.response.send_message(
            view=session.build_view(),
            allowed_mentions=NO_MENTIONS,
        )
        session.message = await interaction.original_response()
        session.reset_timeout()


async def setup(bot: commands.Bot):
    await bot.add_cog(RockPaperScissors(bot))