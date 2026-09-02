import asyncio
import importlib
import os
import sys
import traceback
import logging
import types

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        return False

import discord
from discord import app_commands
from discord.ext import commands

# ── Настройка логирования ──
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ── Минимальная версия для discord.py 2.x ──
MIN_DISCORD_VERSION = (2, 0, 0)
if discord.version_info < MIN_DISCORD_VERSION:
    print(
        f"x Нужен discord.py >= {'.'.join(map(str, MIN_DISCORD_VERSION))}, "
        f"установлен {discord.__version__}"
    )
    sys.exit(1)

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
MODULES_DIR = os.path.join(PROJECT_DIR, "modules")

for path in (MODULES_DIR, PROJECT_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

if not os.path.isdir(MODULES_DIR):
    modules_package = types.ModuleType("modules")
    modules_package.__path__ = [PROJECT_DIR]
    sys.modules.setdefault("modules", modules_package)

load_dotenv()

# =============================================
# ===== ОТЛАДОЧНЫЙ ВЫВОД =====
# =============================================
print("=" * 50)
print("🔍 БОТ ЗАПУЩЕН, НАЧИНАЮ ЗАГРУЗКУ...")
print(f"📁 Текущая директория: {os.getcwd()}")
print(f"📁 Файлы в директории: {os.listdir('.')}")
print("=" * 50)
sys.stdout.flush()

GUILD_ID = 1439176098632957955

# Список когов (модулей)
COGS = [
    ("Logger", None),
    ("Economy", "Economy"),
    ("Marry", "Marry"),
    ("Profile", "Profile"),
    ("Pay", "Pay"),
    ("LoveRooms", "LoveRooms"),
    ("Top", "Top"),
    ("LoveProfile", "LoveProfile"),
    ("Timely", "Timely"),
    ("Balance", "Balance"),
    ("Games", "Games"),
    ("RockPaperScissors", "RockPaperScissors"),
    ("MarriesHistory", "Marries"),
    ("PersonalRoles", "PersonalRoles"),
    ("Shop", "Shop"),
    ("Inventory", "Inventory"),
    ("AdminPanel", "AdminPanel"),
    ("Tracker", "Tracker"),
    ("Info", "UserInfo"),
    ("Case", "Cases"),
]


def import_module(module_name: str):
    try:
        return importlib.import_module(f"modules.{module_name}")
    except ImportError:
        return importlib.import_module(module_name)


print("Загрузка модулей бота...")

loaded_modules = {}

for module_name, class_name in COGS:
    try:
        loaded_modules[module_name] = import_module(module_name)
        print(f"  OK импортирован модуль: {module_name}")
    except Exception as e:
        print(f"\n❌ Ошибка импорта модуля: {module_name}")
        print(f"Тип ошибки: {type(e).__name__}")
        print(f"Ошибка: {e}")
        print("\nПолный traceback:")
        traceback.print_exc()
        sys.exit(1)

print("OK Все модули успешно импортированы")


intents = discord.Intents.all()
intents.members = True
intents.message_content = True
intents.guild_messages = True


async def add_cogs_async(target_bot: commands.Bot):
    for module_name, class_name in COGS:
        if class_name is None:
            continue

        try:
            cog_class = getattr(loaded_modules[module_name], class_name)
            await target_bot.add_cog(cog_class(target_bot))
            logging.info(f"Загружен ког: {class_name}")
            print(f"  OK {class_name} загружен")
        except Exception as e:
            logging.error(f"Не удалось загрузить ког {class_name}. Ошибка: {e}")
            print(f"  x Ошибка загрузки {class_name}: {e}")
            traceback.print_exc()


class EconomyBot(commands.Bot):

    async def setup_hook(self):
        await add_cogs_async(self)

        # Синхронизация команд для discord.py 2.x
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        self.tree.clear_commands(guild=None)
        await self.tree.sync()
        print(f"OK Slash-команды синхронизированы: {len(synced)}")


bot = EconomyBot(
    command_prefix="!",
    intents=intents,
    help_command=None,
    case_insensitive=True,
)


@bot.event
async def on_ready():
    print(f"\n{'=' * 50}")
    print("OK Бот успешно запущен!")
    print(f"OK Имя бота: {bot.user.name}")
    print(f"OK ID бота: {bot.user.id}")
    print(f"OK Версия discord.py: {discord.__version__}")
    print(f"{'=' * 50}\n")
    await bot.change_presence(activity=discord.Game(name="3-0-2"))


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ У вас нет прав для использования этой команды!")
        return
    if isinstance(error, commands.BotMissingPermissions):
        await ctx.send("❌ У бота нет прав для выполнения этой команды!")
        return

    print(f"Ошибка в команде {ctx.command}: {error}")
    await ctx.send(f"❌ Произошла ошибка: {str(error)[:100]}")


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    print(f"Ошибка slash-команды: {error}")
    traceback.print_exc()

    msg = f"❌ Произошла ошибка: {str(error)[:100]}"
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")

    if not token:
        print("x ОШИБКА: Токен не найден в файле .env!")
        print("DISCORD_TOKEN=ваш_токен_бота")
        sys.exit(1)

    print("\nЗапуск бота...")

    try:
        bot.run(token)
    except discord.LoginFailure as e:
        print(f"\nx Ошибка авторизации: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nx Непредвиденная ошибка: {e}")
        traceback.print_exc()
        sys.exit(1)
