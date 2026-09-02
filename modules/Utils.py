import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from modules.Logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)


SETTINGS_PATH = Path("./assets/settings.json")


class Utils:

    def __init__(self):
        self.active_games: List[int] = []
        self.messageCount: Dict[int, int] = {}

    def start_game(self, member_id: int) -> None:
        if member_id not in self.active_games:
            self.active_games.append(member_id)

    def stop_game(self, member_id: int) -> None:
        if member_id in self.active_games:
            self.active_games.remove(member_id)

    def is_active_game(self, member_id: int) -> bool:
        return member_id in self.active_games

    @staticmethod
    def _load_settings() -> Dict[str, Any]:
        try:
            with SETTINGS_PATH.open("r", encoding="utf8") as settings:
                return json.load(settings)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"Ошибка загрузки settings.json: {e}")
            return {}

    @staticmethod
    def _save_settings(data: Dict[str, Any]) -> bool:
        try:
            SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            with SETTINGS_PATH.open("w", encoding="utf8") as settings:
                json.dump(data, settings, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения settings.json: {e}")
            return False

    @staticmethod
    def get_guild_id() -> int:
        data = Utils._load_settings()
        return int(data.get("guild_id") or 0)

    @staticmethod
    def get_patch_db(db: str) -> str:
        data = Utils._load_settings()

        if db == "main":
            return data.get("path_main_db") or "main.db"

        if db == "log":
            return data.get("path_log_db") or "log.db"

        return "main.db"

    @staticmethod
    async def get_guild_id_async() -> int:
        return await asyncio.to_thread(Utils.get_guild_id)

    @staticmethod
    async def get_patch_db_async(db: str) -> str:
        return await asyncio.to_thread(Utils.get_patch_db, db)

    @staticmethod
    async def get_settings() -> Dict[str, Any]:
        return await asyncio.to_thread(Utils._load_settings)

    @staticmethod
    async def update_settings(data: Dict[str, Any]) -> bool:
        return await asyncio.to_thread(Utils._save_settings, data)

    def write_message(self, author: int) -> None:
        self.messageCount[author] = self.messageCount.get(author, 0) + 1

    def get_messages(self) -> Dict[int, int]:
        messages = self.messageCount.copy()
        self.messageCount.clear()
        return messages

    @staticmethod
    def format_time(seconds: int) -> str:
        if seconds < 60:
            return f"{seconds} сек."

        if seconds < 3600:
            return f"{seconds // 60} мин."

        hours = seconds // 3600
        minutes = (seconds % 3600) // 60

        if minutes > 0:
            return f"{hours} ч. {minutes} мин."

        return f"{hours} ч."

    @staticmethod
    def format_number(number: int) -> str:
        return f"{number:,}".replace(",", " ")

    @staticmethod
    def parse_color(color_str: str) -> Optional[int]:
        try:
            value = color_str.strip()
            if value.startswith("#"):
                value = value[1:]
            return int(value, 16)
        except (AttributeError, ValueError):
            return None