import asyncio
import inspect
import random

import discord
from discord import app_commands
from discord.ext import commands

from modules.Database import Database
from modules.Logger import *
from modules.Utils import Utils


guild_id_cmd = Utils.get_guild_id()

COIN = "<:coin:1515637898735652924>"
ACCENT = 0x2F3136
ERROR_IMAGE = "https://cdn.discordapp.com/attachments/992883178362642453/1029462389130792970/-1.png"
FLIP_HEADS_GIF = "https://media.discordapp.net/attachments/1505184234808016946/1520103755775742022/animation_2.gif?ex=6a3ffa71&is=6a3ea8f1&hm=d989ceb358e58dabc751b9dfcdd0bea6b14e66bb3dd09ee05b5f046ccbfe4fd9&=&width=1109&height=625"
FLIP_TAILS_GIF = "https://media.discordapp.net/attachments/1505184234808016946/1520102691081158656/orel.gif?ex=6a3ff973&is=6a3ea7f3&hm=5864e1e5ee5712ea0365b1f72feff1b3dd5029f97f5d2b9c4d23791e81c04ba9&=&width=1024&height=578"
FLIP_VALUES = ("Орёл", "Решка")

# BlackJack константы
CARD_SUITS = ["♠", "♥", "♦", "♣"]
CARD_RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
CARD_VALUES = {
    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9, "10": 10,
    "J": 10, "Q": 10, "K": 10, "A": 11
}

# Кастомные эмодзи для BlackJack
PLUS_EMOJI = "<:plus:1519444454149198005>"
DEL_EMOJI = "<:del:1515639124256751676>"


async def maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def clamp_text(value, limit=3800):
    value = "" if value is None else str(value)
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


class Games(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database()
        self.utils = Utils()
        self.blackjack_games = {}  # user_id -> BlackJackGame

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("/games - start")

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

            for row_items in rows:
                container.add_item(row_items)

        view.add_item(container)
        return view

    def row(self, *items):
        row = discord.ui.ActionRow()
        for item in items:
            row.add_item(item)
        return row

    def button(self, label=None, *, emoji=None, callback=None, custom_id=None, style=discord.ButtonStyle.secondary, disabled=False):
        # Убираем timeout=None, так как у Button нет этого параметра
        button = discord.ui.Button(
            label=label,
            emoji=emoji,
            custom_id=custom_id,
            style=style,
            disabled=disabled
        )

        if callback is not None:
            button.callback = callback

        return button

    async def respond(self, interaction, view, *, ephemeral=False):
        if interaction.response.is_done():
            return await interaction.followup.send(view=view, ephemeral=ephemeral, wait=True)

        return await interaction.response.send_message(view=view, ephemeral=ephemeral)

    async def edit_original(self, interaction, view):
        return await interaction.edit_original_response(view=view)

    def error_view(self, title, description, user=None, image=False):
        return self.build_view(
            title,
            description,
            thumbnail_url=str(user.display_avatar.url) if user else None,
            image_url=ERROR_IMAGE if image else None,
        )

    async def send_not_owner(self, interaction: discord.Interaction):
        await interaction.followup.send(
            view=self.error_view(
                "Ошибка",
                "Эта кнопка доступна только игроку, который запустил игру.",
                interaction.user,
            ),
            ephemeral=True,
        )

    async def ensure_balance(self, interaction: discord.Interaction, amount: int) -> bool:
        balance = await maybe_await(self.db.get_balance(interaction.user.id))
        if balance >= amount:
            return True

        await interaction.response.send_message(
            view=self.error_view(
                "Упс...",
                "У вас недостаточно средств! Для начала пополните свой баланс.",
                interaction.user,
                image=True,
            ),
            ephemeral=True,
        )
        return False

    def result_with_repeat_view(self, interaction, game_name, description, *, footer=None, repeat_callback=None):
        async def default_repeat(button_interaction: discord.Interaction):
            await button_interaction.response.defer()

        return self.build_view(
            f"{game_name} — {interaction.user.display_name}",
            description,
            footer=footer,
            rows=[
                self.row(
                    self.button(
                        "Сыграть с той же ставкой",
                        custom_id="button_repeat_game",
                        callback=repeat_callback or default_repeat,
                    )
                )
            ],
            thumbnail_url=str(interaction.user.display_avatar.url),
        )

    # ============ ОРЁЛ ИЛИ РЕШКА ============
    @app_commands.command(name="coinflip", description="Подбросить монетку на валюту.")
    @app_commands.describe(ставка="Ставка для игры (минимум 50 монет).")
    @app_commands.guilds(discord.Object(id=guild_id_cmd))
    async def coinflip(
        self,
        interaction: discord.Interaction,
        ставка: app_commands.Range[int, 50, 999999],
    ):
        if self.utils.is_active_game(interaction.user.id):
            await interaction.response.send_message(
                view=self.error_view(
                    f"Орёл или Решка — {interaction.user.display_name}",
                    "У вас уже **есть** активная игра!",
                    interaction.user,
                ),
                ephemeral=True,
            )
            return

        if not await self.ensure_balance(interaction, ставка):
            return

        await self.handle_flip_game(interaction, ставка)

    async def handle_flip_game(self, interaction: discord.Interaction, amount: int):
        self.utils.start_game(interaction.user.id)
        await interaction.response.send_message(
            view=self.flip_choice_view(interaction, amount)
        )

    def flip_choice_view(self, interaction: discord.Interaction, amount: int):
        state = {"resolved": False}

        async def choose_side(button_interaction: discord.Interaction, selected_side: str):
            await button_interaction.response.defer()

            if button_interaction.user.id != interaction.user.id:
                await self.send_not_owner(button_interaction)
                return

            if state["resolved"]:
                return

            state["resolved"] = True
            await self.resolve_flip(interaction, button_interaction, amount, selected_side)

        async def heads_callback(button_interaction: discord.Interaction):
            await choose_side(button_interaction, "Орёл")

        async def tails_callback(button_interaction: discord.Interaction):
            await choose_side(button_interaction, "Решка")

        class FlipChoiceView(discord.ui.LayoutView):
            async def on_timeout(self):
                if state["resolved"]:
                    return

                state["resolved"] = True
                self.utils.stop_game(interaction.user.id)
                await interaction.edit_original_response(
                    view=self.error_view(
                        f"Орёл или Решка — {interaction.user.display_name}",
                        "Время ожидания истекло!",
                        interaction.user,
                    )
                )

        view = FlipChoiceView(timeout=None)
        container = discord.ui.Container()

        content = f"## Орёл или Решка — {interaction.user.display_name}\n\n{interaction.user.mention}, выберите сторону на которую **хотите** поставить **{amount}** {COIN}"
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(content=clamp_text(content)),
                accessory=discord.ui.Thumbnail(str(interaction.user.display_avatar.url)),
            )
        )
        container.add_item(discord.ui.Separator())
        
        row = discord.ui.ActionRow()
        row.add_item(self.button("Орёл", custom_id="button_orel", callback=heads_callback))
        row.add_item(self.button("Решка", custom_id="button_reshka", callback=tails_callback))
        container.add_item(row)
        
        view.add_item(container)
        return view

    async def resolve_flip(
        self,
        interaction: discord.Interaction,
        button_interaction: discord.Interaction,
        amount: int,
        selected_side: str,
    ):
        await maybe_await(self.db.take_money(button_interaction.user.id, amount))

        random_win = random.choice(FLIP_VALUES)
        image_url = FLIP_HEADS_GIF if random_win == "Орёл" else FLIP_TAILS_GIF

        await interaction.edit_original_response(
            view=self.build_view(
                f"Орёл или Решка — {interaction.user.display_name}",
                f"**Ставка:** {amount} {COIN}\n**Выбранная сторона:** {selected_side}",
                image_url=image_url,
            )
        )

        await asyncio.sleep(4)

        did_win = random_win == selected_side
        verb = "выпала" if random_win == "Решка" else "выпал"

        if did_win:
            await maybe_await(self.db.give_money(interaction.user.id, amount * 2))
            await maybe_await(self.db.write_new_transactions(interaction.user, "Победа в игре", amount))
            result_text = (
                f"{button_interaction.user.mention}, {verb} **{random_win}**, "
                f"**Вы** выиграли **{amount}** {COIN}"
            )
        else:
            await maybe_await(self.db.write_new_transactions(interaction.user, "Поражение в игре", -amount))
            result_text = (
                f"{button_interaction.user.mention}, {verb} **{random_win}**, "
                f"**Вы** проиграли **{amount}** {COIN}"
            )

        new_balance = await maybe_await(self.db.get_balance(interaction.user.id))
        self.utils.stop_game(interaction.user.id)

        await interaction.edit_original_response(
            view=self.result_with_repeat_view(
                interaction,
                "Орёл или Решка",
                result_text,
                footer=f"Ваш баланс — {new_balance}",
                repeat_callback=lambda repeat_interaction: self.repeat_flip(
                    interaction,
                    repeat_interaction,
                    amount,
                ),
            )
        )

    async def repeat_flip(
        self,
        root_interaction: discord.Interaction,
        button_interaction: discord.Interaction,
        amount: int,
    ):
        await button_interaction.response.defer()

        if button_interaction.user.id != root_interaction.user.id:
            await self.send_not_owner(button_interaction)
            return

        if self.utils.is_active_game(root_interaction.user.id):
            await root_interaction.edit_original_response(
                view=self.error_view(
                    f"Орёл или Решка — {root_interaction.user.display_name}",
                    "У вас уже **есть** активная игра!",
                    root_interaction.user,
                )
            )
            return

        current_balance = await maybe_await(self.db.get_balance(root_interaction.user.id))
        if current_balance < amount:
            await button_interaction.followup.send(
                view=self.error_view(
                    "Упс...",
                    "У вас недостаточно средств! Для начала пополните свой баланс.",
                    root_interaction.user,
                    image=True,
                ),
                ephemeral=True,
            )
            return

        self.utils.start_game(root_interaction.user.id)
        await root_interaction.edit_original_response(
            view=self.flip_choice_view(root_interaction, amount)
        )

    # ============ КАЗИНО ============
    @app_commands.command(name="casino", description="Сыграть в казино на валюту.")
    @app_commands.describe(ставка="Ставка для игры (минимум 50 монет).")
    @app_commands.guilds(discord.Object(id=guild_id_cmd))
    async def casino(
        self,
        interaction: discord.Interaction,
        ставка: app_commands.Range[int, 50, 999999],
    ):
        if self.utils.is_active_game(interaction.user.id):
            await interaction.response.send_message(
                view=self.error_view(
                    f"Казино — {interaction.user.display_name}",
                    "У вас уже **есть** активная игра!",
                    interaction.user,
                ),
                ephemeral=True,
            )
            return

        if not await self.ensure_balance(interaction, ставка):
            return

        await self.handle_casino_game(interaction, ставка)

    async def handle_casino_game(self, interaction: discord.Interaction, amount: int):
        await interaction.response.send_message(
            view=await self.casino_result_view(interaction, amount)
        )

    async def casino_result_view(self, interaction: discord.Interaction, amount: int):
        random_number = random.randint(1, 100)

        if random_number % 2 == 0:
            await maybe_await(self.db.take_money(interaction.user.id, amount))
            await maybe_await(self.db.write_new_transactions(interaction.user, "Поражение в игре", -amount))
            result_line = f"> **Ты проиграл**\n```{amount}``` {COIN}"
        else:
            await maybe_await(self.db.give_money(interaction.user.id, amount))
            await maybe_await(self.db.write_new_transactions(interaction.user, "Победа в игре", amount))
            result_line = f"> **Ты выиграл**\n```{amount}``` {COIN}"

        new_balance = await maybe_await(self.db.get_balance(interaction.user.id))
        description = (
            f"> **Ставка**\n```{amount}``` {COIN}\n"
            f"> **Выпавшее число**\n```{random_number}```\n"
            f"{result_line}"
        )

        async def repeat_callback(button_interaction: discord.Interaction):
            await button_interaction.response.defer()

            if button_interaction.user.id != interaction.user.id:
                await self.send_not_owner(button_interaction)
                return

            if self.utils.is_active_game(interaction.user.id):
                await interaction.edit_original_response(
                    view=self.error_view(
                        f"Казино — {interaction.user.display_name}",
                        "У вас уже **есть** активная игра!",
                        interaction.user,
                    )
                )
                return

            current_balance = await maybe_await(self.db.get_balance(interaction.user.id))
            if current_balance < amount:
                await button_interaction.followup.send(
                    view=self.error_view(
                        "Упс...",
                        "У вас недостаточно средств! Для начала пополните свой баланс.",
                        interaction.user,
                        image=True,
                    ),
                    ephemeral=True,
                )
                return

            await interaction.edit_original_response(
                view=await self.casino_result_view(interaction, amount)
            )

        return self.result_with_repeat_view(
            interaction,
            "Казино",
            description,
            footer=f"Ваш баланс — {new_balance}",
            repeat_callback=repeat_callback,
        )

    # ============ БЛЭК ДЖЕК ============
    class BlackJackGame:
        def __init__(self, user_id: int, amount: int):
            self.user_id = user_id
            self.amount = amount
            self.deck = []
            self.player_hand = []
            self.dealer_hand = []
            self.game_over = False
            self._create_deck()
            self._shuffle_deck()
            
        def _create_deck(self):
            self.deck = []
            for suit in CARD_SUITS:
                for rank in CARD_RANKS:
                    self.deck.append({"rank": rank, "suit": suit})
                    
        def _shuffle_deck(self):
            random.shuffle(self.deck)
            
        def _card_value(self, card):
            return CARD_VALUES[card["rank"]]
            
        def _hand_value(self, hand):
            value = sum(self._card_value(card) for card in hand)
            # Пересчет тузов (A может быть 11 или 1)
            aces = sum(1 for card in hand if card["rank"] == "A")
            while value > 21 and aces > 0:
                value -= 10
                aces -= 1
            return value
            
        def _card_str(self, card):
            return f"{card['rank']}{card['suit']}"
            
        def _hand_str(self, hand, hide_first=False):
            if hide_first and hand:
                if len(hand) <= 1:
                    return "??"
                # Показываем только первую карту как ??, остальные показываем
                return f"?? " + " ".join(self._card_str(card) for card in hand[1:])
            return " ".join(self._card_str(card) for card in hand)
            
        def deal_initial(self):
            self.player_hand = [self.deck.pop(), self.deck.pop()]
            self.dealer_hand = [self.deck.pop(), self.deck.pop()]
            
        def hit(self):
            if self.game_over:
                return False
            self.player_hand.append(self.deck.pop())
            if self._hand_value(self.player_hand) > 21:
                self.game_over = True
                return False
            return True
            
        def stand(self):
            self.game_over = True
            while self._hand_value(self.dealer_hand) < 17:
                self.dealer_hand.append(self.deck.pop())
                
        def is_bust(self, hand=None):
            if hand is None:
                hand = self.player_hand
            return self._hand_value(hand) > 21
            
        def get_player_value(self):
            return self._hand_value(self.player_hand)
            
        def get_dealer_value(self):
            return self._hand_value(self.dealer_hand)
            
        def get_player_hand_str(self):
            return self._hand_str(self.player_hand)
            
        def get_dealer_hand_str(self, hide=False):
            return self._hand_str(self.dealer_hand, hide)
            
        def get_result(self):
            player_val = self.get_player_value()
            dealer_val = self.get_dealer_value()
            
            if player_val > 21:
                return "lose"
            if dealer_val > 21:
                return "win"
            if player_val > dealer_val:
                return "win"
            if player_val < dealer_val:
                return "lose"
            return "push"

    @app_commands.command(name="blackjack", description="Сыграть в Блэк Джек на валюту.")
    @app_commands.describe(ставка="Ставка для игры (минимум 50 монет).")
    @app_commands.guilds(discord.Object(id=guild_id_cmd))
    async def blackjack(
        self,
        interaction: discord.Interaction,
        ставка: app_commands.Range[int, 50, 999999],
    ):
        if self.utils.is_active_game(interaction.user.id):
            await interaction.response.send_message(
                view=self.error_view(
                    f"Блэк Джек — {interaction.user.display_name}",
                    "У вас уже **есть** активная игра!",
                    interaction.user,
                ),
                ephemeral=True,
            )
            return

        if not await self.ensure_balance(interaction, ставка):
            return

        await self.handle_blackjack_game(interaction, ставка)

    async def handle_blackjack_game(self, interaction: discord.Interaction, amount: int):
        game = self.BlackJackGame(interaction.user.id, amount)
        game.deal_initial()
        self.blackjack_games[interaction.user.id] = game
        self.utils.start_game(interaction.user.id)
        
        await interaction.response.send_message(
            view=await self.blackjack_view(interaction, game, amount)
        )

    async def blackjack_view(self, interaction: discord.Interaction, game, amount: int, initial: bool = True):
        if initial:
            await maybe_await(self.db.take_money(interaction.user.id, amount))
            
        state = {"resolved": False}
        cog = self  # сохраняем ссылку на экземпляр Games, чтобы использовать внутри View

        async def hit_callback(button_interaction: discord.Interaction):
            await button_interaction.response.defer()
            
            if button_interaction.user.id != interaction.user.id:
                await self.send_not_owner(button_interaction)
                return
                
            if state["resolved"] or game.game_over:
                return
                
            game.hit()
            
            if game.is_bust():
                state["resolved"] = True
                await self.finish_blackjack(interaction, game, amount)
            else:
                await interaction.edit_original_response(
                    view=await self.blackjack_view(interaction, game, amount, False)
                )

        async def stand_callback(button_interaction: discord.Interaction):
            await button_interaction.response.defer()
            
            if button_interaction.user.id != interaction.user.id:
                await self.send_not_owner(button_interaction)
                return
                
            if state["resolved"] or game.game_over:
                return
                
            state["resolved"] = True
            game.stand()
            await self.finish_blackjack(interaction, game, amount)

        class BlackJackView(discord.ui.LayoutView):
            async def on_timeout(self):
                if state["resolved"] or game.game_over:
                    return
                    
                state["resolved"] = True
                game.game_over = True

                # Убираем игру из списка активных (используем cog, а не self)
                cog.utils.stop_game(interaction.user.id)
                if interaction.user.id in cog.blackjack_games:
                    del cog.blackjack_games[interaction.user.id]

                # Ставка НЕ возвращается — записываем поражение
                await maybe_await(cog.db.write_new_transactions(
                    interaction.user,
                    "Поражение в Блэк Джек (таймаут)",
                    -amount
                ))

                await interaction.edit_original_response(
                    view=cog.error_view(
                        f"Блэк Джек — {interaction.user.display_name}",
                        "Время ожидания истекло! Ставка потеряна.",
                        interaction.user,
                    )
                )

        view = BlackJackView(timeout=600)  # 10 минут = 600 секунд
        container = discord.ui.Container()

        dealer_hand = game.get_dealer_hand_str(hide=initial)
        player_hand = game.get_player_hand_str()
        player_val = game.get_player_value() if not game.is_bust() else "Перебор"

        content = (
            f"## Блэк Джек — {interaction.user.display_name}\n\n"
            f"**Ставка:** {amount} {COIN}\n"
            f"**Баланс:** {await maybe_await(self.db.get_balance(interaction.user.id))}\n\n"
            f"**Дилер:** {dealer_hand}\n"
            f"**Вы:** {player_hand} (Очки: {player_val})\n"
        )

        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(content=clamp_text(content)),
                accessory=discord.ui.Thumbnail(str(interaction.user.display_avatar.url)),
            )
        )
        container.add_item(discord.ui.Separator())

        row = discord.ui.ActionRow()
        # Используем кастомные эмодзи
        hit_button = self.button("Взять", emoji=PLUS_EMOJI, callback=hit_callback, style=discord.ButtonStyle.primary)
        stand_button = self.button("Остановиться", emoji=DEL_EMOJI, callback=stand_callback, style=discord.ButtonStyle.secondary)
        
        if game.game_over or game.is_bust():
            hit_button.disabled = True
            stand_button.disabled = True
            
        row.add_item(hit_button)
        row.add_item(stand_button)
        container.add_item(row)

        view.add_item(container)
        return view

    async def finish_blackjack(self, interaction: discord.Interaction, game, amount: int):
        self.utils.stop_game(interaction.user.id)
        if interaction.user.id in self.blackjack_games:
            del self.blackjack_games[interaction.user.id]
            
        result = game.get_result()
        player_val = game.get_player_value()
        dealer_val = game.get_dealer_value()
        
        if result == "win":
            winnings = amount * 2
            await maybe_await(self.db.give_money(interaction.user.id, winnings))
            await maybe_await(self.db.write_new_transactions(interaction.user, "Победа в Блэк Джек", amount))
            result_text = f"**Вы выиграли!** +{amount} {COIN}"
        elif result == "push":
            await maybe_await(self.db.give_money(interaction.user.id, amount))
            result_text = f"**Ничья!** Ставка возвращена."
        else:
            await maybe_await(self.db.write_new_transactions(interaction.user, "Поражение в Блэк Джек", -amount))
            result_text = f"**Вы проиграли!** -{amount} {COIN}"

        new_balance = await maybe_await(self.db.get_balance(interaction.user.id))
        
        description = (
            f"**Ставка:** {amount} {COIN}\n"
            f"**Дилер:** {game.get_dealer_hand_str()} (Очки: {dealer_val})\n"
            f"**Вы:** {game.get_player_hand_str()} (Очки: {player_val})\n\n"
            f"{result_text}"
        )

        async def repeat_callback(button_interaction: discord.Interaction):
            await button_interaction.response.defer()
            
            if button_interaction.user.id != interaction.user.id:
                await self.send_not_owner(button_interaction)
                return
                
            if self.utils.is_active_game(interaction.user.id):
                await interaction.edit_original_response(
                    view=self.error_view(
                        f"Блэк Джек — {interaction.user.display_name}",
                        "У вас уже **есть** активная игра!",
                        interaction.user,
                    )
                )
                return
                
            current_balance = await maybe_await(self.db.get_balance(interaction.user.id))
            if current_balance < amount:
                await button_interaction.followup.send(
                    view=self.error_view(
                        "Упс...",
                        "У вас недостаточно средств! Для начала пополните свой баланс.",
                        interaction.user,
                        image=True,
                    ),
                    ephemeral=True,
                )
                return
                
            game_new = self.BlackJackGame(interaction.user.id, amount)
            game_new.deal_initial()
            self.blackjack_games[interaction.user.id] = game_new
            self.utils.start_game(interaction.user.id)
            
            await interaction.edit_original_response(
                view=await self.blackjack_view(interaction, game_new, amount)
            )

        await interaction.edit_original_response(
            view=self.result_with_repeat_view(
                interaction,
                "Блэк Джек",
                description,
                footer=f"Ваш баланс — {new_balance}",
                repeat_callback=repeat_callback,
            )
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Games(bot))