import time
from datetime import timedelta
from typing import Optional

from tinydb import Query

from db.storage import open_store

class Player:
    def __init__(self, provider: str, player_id: str, name: str, lifespan: timedelta, db_stats):
        self.provider = provider
        self.player_id = player_id
        self.name = name
        self._db_stats = db_stats
        self._db_gamestates = open_store(f'data/gamestates/{self.key}.json')
        self._lifespan = lifespan
        self._update_ttl()
        self.games = {}

        player_stats = self._db_stats.search(Query().player_id == self.key)
        if player_stats:
            self.data = player_stats[0]
            self.data['name'] = self.name
        else:
            self.data = {
                'player_id': self.key,
                'name': self.name,
            }
            self._db_stats.insert(self.data)

    @property
    def key(self):
        return self.get_player_id(self.provider, self.player_id)

    def get_game(self, game_id):
        if game_id not in self.games:
            game = self._db_gamestates.search(Query().game_id == game_id)
            if game:
                self.games[game_id] = game[0]
            else:
                self.games[game_id] = {}
        return self.games[game_id]

    def set_game(self, game_id, game_data):
        self.games[game_id] = game_data
        self._db_gamestates.upsert(game_data, Query().game_id == game_id)

    def get_data(self, key):
        return self.data.get(key, None)

    def set_data(self, key, value):
        self.data[key] = value
        self._db_stats.update(self.data, Query().player_id == self.key)

    def has_ttl_expired(self):
        return time.time() > self._ttl

    def _update_ttl(self):
        self._ttl = time.time() + self._lifespan.total_seconds()

    @staticmethod
    def get_player_id(provider, player_id):
        return f"{provider}_{player_id}"

class PlayerRepository:
    def __init__(self, db_players='data/players.json'):
        self._db_players = open_store(db_players)
        self.cache = {}
        self.cache_ttl = timedelta(hours=1)

    def get_player(self, provider, player_id, name):
        key = Player.get_player_id(provider, player_id)
        if key in self.cache:
            player = self.cache[key]
            if player.has_ttl_expired():
                del self.cache[key]
            else:
                return player

        player = Player(provider, player_id, name, self.cache_ttl, self._db_players)
        self.cache[key] = player
        return player

    def cleanup(self):
        for key in list(self.cache.keys()):
            if self.cache[key].has_ttl_expired():
                del self.cache[key]

    def get_player_by_name(self, provider, name) -> Optional[Player]:
        match = next((player.player_id for player in self.cache.values() if player.provider == provider and player.name == name), None)
        if match:
            return self.get_player(provider, match, name)
        query = Query()
        match = self._db_players.search((query.name == name) & (query.provider == provider))
        if match:
            return self.get_player(provider, match[0]['player_id'], name)
        return None
