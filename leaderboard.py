from enum import Enum

import aiohttp
import logging
import os
import time
from typing import List, Dict, Optional

CATEGORIES = ["any", "aa"]


class RoroMcsrConfig:
    def __init__(self):
        self.base_url = os.getenv("RORO_MCSR_BASE_URL")
        self.client_id = os.getenv("RORO_MCSR_CLIENT_ID")
        self.client_secret = os.getenv("RORO_MCSR_CLIENT_SECRET")


class SearchType(Enum):
    RANGE = "range"
    TOP = "top"
    NAME = "name"
    LTE_TIME = "lte_time"
    GTE_TIME = "gte_time"
    PLACE = "place"


class LeaderboardAPI:
    def __init__(self, config: RoroMcsrConfig):
        self.base_url = f"{config.base_url}/api/leaderboard"
        self.auth = (config.client_id, config.client_secret)

    async def get_boards(self, category: str) -> List[Dict]:
        url = f"{self.base_url}/boards"
        params = {"cat": category}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, auth=aiohttp.BasicAuth(*self.auth)) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def search(self, category: str, board: str, params: Dict) -> List[Dict]:
        url = f"{self.base_url}/search"
        params.update({"cat": category, "board": board})
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, auth=aiohttp.BasicAuth(*self.auth)) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data.get("results", [])

    async def get_total_records(self, category: str, board: str) -> int:
        url = f"{self.base_url}/all"
        params = {"cat": category, "board": board}
        async with aiohttp.ClientSession() as session:
            async with session.head(url, params=params, auth=aiohttp.BasicAuth(*self.auth)) as resp:
                resp.raise_for_status()
                return int(resp.headers.get("x-total-count", 0))


class BoardsCache:
    _CACHE_EXPIRY = 3600

    def __init__(self, api: LeaderboardAPI):
        self.api = api
        self.boards_by_category = {}
        self.last_update = 0

    async def get_valid_boards(self, category: str) -> List[str]:
        await self._ensure_updated()
        return self._get_board_names(category)

    async def get_board_display_name(self, category: str, name: str) -> str | None:
        await self._ensure_updated()
        for board in self.boards_by_category.get(category, []):
            if board["name"] == name:
                return board["displayName"]
        return None

    def clear_cache(self):
        self.last_update = 0

    async def _ensure_updated(self):
        if time.time() - self.last_update > self._CACHE_EXPIRY:
            for category in CATEGORIES:
                self.boards_by_category[category] = sorted(await self.api.get_boards(category),
                                                           key=lambda b: not b.get("isDefault", False))
                logging.info(f"Updated {category} boards cache: {', '.join(self._get_board_names(category))}")
            self.last_update = time.time()

    def _get_board_names(self, category: str) -> List[str]:
        return [b["name"] for b in self.boards_by_category.get(category, [])]


class QueryParser:
    def __init__(self, channel, category: str, args: List[str]):
        self.args = args
        self.channel = channel
        self.category = category
        self.search_type = None
        self.search_term = None
        self.params = {}

    def parse(self) -> tuple[Dict, SearchType, str]:
        if not self.args:
            self.params["name"] = self.channel
            self.search_type = SearchType.NAME
            self.search_term = self.channel
            return self.params, self.search_type, self.search_term

        method_name = f"_parse_as_{self.args[0]}"
        if hasattr(self, method_name):
            getattr(self, method_name)()
        else:
            self._parse_general()
        return self.params, self.search_type, self.search_term

    def _parse_as_range(self):
        if len(self.args) < 3:
            raise ValueError("User provided range without start and end values")
        try:
            start = int(self.args[1])
            end = int(self.args[2])
        except ValueError:
            raise ValueError("User provided invalid range values")
        if start < 1 or end < start:
            raise ValueError("User provided invalid range values")
        self.search_type = SearchType.RANGE
        self.search_term = f"{start} - {end}"
        self.params.update({"place": start, "take": end - start + 1})

    def _parse_as_top(self):
        if len(self.args) < 2:
            raise ValueError("User provided top without a value")
        try:
            n = int(self.args[1])
        except ValueError:
            raise ValueError("User provided invalid top value")
        self.search_type = SearchType.TOP
        self.search_term = f"top {n}"
        self.params.update({"place": 1, "take": n})

    def _parse_general(self):
        arg = self.args[0]
        if ":" in arg:
            self._parse_time(arg)
        elif arg.isdigit():
            self.search_type = SearchType.PLACE
            self.search_term = arg
            self.params.update({"place": int(arg)})
        else:
            self.search_type = SearchType.NAME
            self.search_term = " ".join(self.args)
            self.params["name"] = self.search_term

    def _parse_time(self, arg: str):
        if arg[0] in ("<", ">"):
            operator = arg[0]
            time_str = arg[1:]
        else:
            operator = ">"
            time_str = arg
        time_val = self._parse_time_string(time_str)
        self.search_term = time_val
        if operator == "<":
            self.search_type = SearchType.LTE_TIME
            self.params["ltetime"] = time_val
        else:
            self.search_type = SearchType.GTE_TIME
            self.params["gtetime"] = time_val

    def _parse_time_string(self, time_str: str) -> str:
        parts = list(map(int, time_str.split(":")))
        if len(parts) == 1:
            if self.category == "aa":
                h, m, s = parts[0], 0, 0
            else:
                h, m, s = 0, parts[0], 0
        elif len(parts) == 2:
            if self.category == "aa":
                h, m, s = parts[0], parts[1], 0
            else:
                h, m, s = 0, parts[0], parts[1]
        else:
            h, m, s = parts
        return f"{h:02d}:{m:02d}:{s:02d}"


class ResponseFormatter:
    MAX_LENGTH = 250

    def __init__(self, results: List[Dict], board: str, search_type: SearchType, search_term: str,
                 multiple: bool = False):
        self.results = results
        self.board = board
        self.search_type = search_type
        self.search_term = search_term or "ERROR"
        self.multiple = multiple

    def format(self, suffix: Optional[str] = None) -> str:
        if not self.results:
            return self._format_empty() + suffix
        prefix = f"{self.board} "
        formatted = prefix + self._format_entries(show_time=True) + suffix
        if len(formatted) <= self.MAX_LENGTH:
            return formatted

        formatted = prefix + self._format_entries(show_time=False) + suffix
        return formatted if len(formatted) <= self.MAX_LENGTH else "That's too many players. smh"

    def _format_empty(self) -> str:
        if self.search_type == SearchType.RANGE:
            return f"I can't find any players in the range {self.search_term}. Hmmge"
        if self.search_type == SearchType.LTE_TIME:
            return f"I can't find a player with a time less than {self.search_term}. Erm"
        if self.search_type == SearchType.GTE_TIME:
            return f"I can't find a player with a time greater than {self.search_term}. Erm"
        if self.search_type == SearchType.PLACE:
            return f"I can't find a player at #{self.search_term}. Hmmge"
        if self.search_type == SearchType.TOP:
            return f"There's no one in the top {self.search_term}. Susge"
        if self.search_type == SearchType.NAME:
            return f"Sorry, I don't know who {self.search_term} is. smh"
        return f"Something went wrong. smh"

    def _format_entries(self, show_time: bool) -> str:
        entries = []
        for i, result in enumerate(self.results):
            if not self.multiple and i != 0:
                break
            run = result["run"]
            entry = self._format_entry(run, show_time, show_place=i == 0)
            entries.append(entry)
        return " | ".join(entries)

    def _format_entry(self, run: Dict, show_time: bool, show_place: bool) -> str:
        place = f"#{run['place']}: " if show_place else ""
        players = self._format_players(run["players"])
        time = f" ({run['completionTime']})" if show_time else ""
        return f"{place}{players}{time}"

    @staticmethod
    def _format_players(players: List[str]) -> str:
        if not players:
            return "Unknown"
        if len(players) == 1:
            return players[0]
        return ", ".join(players[:-1]) + " & " + players[-1]


class LeaderboardCommandHandler:
    def __init__(self, api: LeaderboardAPI = None, cache: BoardsCache = None):
        self._api = api or LeaderboardAPI(RoroMcsrConfig())
        self._boards = cache or BoardsCache(self._api)

    async def handle(self, channel: str, category: str, args: List[str], suffix: Optional[str] = None) -> str | None:
        if not suffix:
            suffix = ""
        try:
            boards = await self._boards.get_valid_boards(category)
            board, query_args = self._parse_board(args, boards)
            board_name = await self._boards.get_board_display_name(category, board) or board
        except Exception as e:
            logging.error(f"Error getting boards: {e}")
            return "I wasn't able to get the leaderboards. smh"

        if query_args and query_args[0] == "boards":
            return f"Available boards: {', '.join([b if i != 0 else f'{b} (default)' for i, b in enumerate(boards)])}"

        try:
            if query_args and query_args[0] == "count":
                count = await self._api.get_total_records(category, board)
                return f"There are {count} entries in the {board_name} leaderboard." if count \
                    else f"I can't find any entries for the {board_name} leaderboard."
        except Exception as e:
            logging.error(f"Error getting total records: {e}")
            return f"Oh I wasn't able to count the number of entries in the {board_name} leaderboard."

        try:
            params, search_type, search_term = QueryParser(channel, category, query_args).parse()
        except ValueError as e:
            logging.error(f"Error parsing query: {e}")
            return "Your query is invalid. ReallyGun"

        try:
            results = await self._api.search(category, board, params)
            return ResponseFormatter(results, board_name, search_type, search_term, "take" in params).format(suffix)
        except Exception as e:
            logging.error(f"Error querying leaderboards: {e}")
            return f"I wasn't able to query the {board_name} leaderboard. smh"

    @staticmethod
    def _parse_board(args: List[str], valid_boards: List[str]) -> tuple:
        if args and args[0] in valid_boards:
            return args[0], args[1:]
        if valid_boards:
            return valid_boards[0], args
        return "rsg", args
