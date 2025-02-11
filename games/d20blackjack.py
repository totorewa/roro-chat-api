import random
from enum import Enum
from typing import Optional

from db.player import PlayerRepository, Player


class GameState(Enum):
    WAITING = "waiting"
    PLAYING = "playing"


class RollResult(Enum):
    INVALID_STATE = "invalid_state"
    INVALID_FACE = "invalid_face"
    ROLLED = "rolled"
    BLACKJACK = "blackjack"
    BUST = "bust"


class D20Blackjack:
    _ID = 'd20blackjack'
    BLACKJACK = 21

    def __init__(self, player_repo: PlayerRepository):
        self.player_repo = player_repo

    def get_player(self, provider: str, player_id: str, name: str) -> Player:
        return self.player_repo.get_player(provider, player_id, name)

    def get_player_by_name(self, provider: str, name: str) -> Optional[Player]:
        return self.player_repo.get_player_by_name(provider, name)

    def get_game_state(self, player: Player) -> dict:
        game = player.get_game(self._ID)
        if not game:
            game = {
                'game_id': self._ID,
                'state': GameState.WAITING.value,
                'channel': '',
                'dice': [],
            }
        return game

    def get_stats(self, player: Player) -> dict:
        stats = player.get_data(self._ID)
        if not stats:
            stats = {
                'rolls': 0,
                'rerolls': 0,
                'blackjacks': 0,
                'busts': 0,
                'accumulated_value': 0,
            }
        return stats

    def set_stats(self, player: Player, stats: dict) -> None:
        player.set_data(self._ID, stats)

    def set_game_state(self, player: Player, game_state: dict) -> None:
        player.set_game(self._ID, game_state)

    def roll_dice(self, channel: str, player: Player) -> tuple[Optional[list[int]], RollResult]:
        game = self.get_game_state(player)
        dice = [random.randint(1, 20), random.randint(1, 20)]
        result = self._calculate_roll_result(dice)
        game['dice'] = dice
        game['state'] = GameState.PLAYING.value if result == RollResult.ROLLED else GameState.WAITING.value
        game['channel'] = channel
        self.set_game_state(player, game)

        stats = self.get_stats(player)
        stats['rolls'] += 1
        self._commit_roll_to_stats(stats, dice)
        self.set_stats(player, stats)
        return game['dice'], result

    def reroll_dice(self, channel: str, player: Player, face_value: int) -> tuple[Optional[list[int]], RollResult]:
        game = self.get_game_state(player)
        print("reroll_dice", game)
        if game['state'] != GameState.PLAYING.value or game['channel'] != channel:
            return None, RollResult.INVALID_STATE

        dice = game['dice']
        if face_value not in dice:
            return None, RollResult.INVALID_FACE

        stats = self.get_stats(player)
        self._remove_roll_from_stats(stats, dice)
        dice.remove(face_value)
        dice.append(random.randint(1, 20))
        game['dice'] = dice
        game['state'] = GameState.WAITING.value
        self.set_game_state(player, game)
        result = self._calculate_roll_result(dice)
        stats['rerolls'] += 1
        self._commit_roll_to_stats(stats, dice)
        self.set_stats(player, stats)
        return game['dice'], result

    def get_dice(self, player: Player):
        dice = self.get_game_state(player)['dice']
        return dice if dice else None

    @staticmethod
    def _commit_roll_to_stats(stats: dict, dice: list[int]):
        roll = sum(dice)
        stats['accumulated_value'] += roll
        if roll == D20Blackjack.BLACKJACK:
            stats['blackjacks'] += 1
        elif roll >= D20Blackjack.BLACKJACK:
            stats['busts'] += 1

    @staticmethod
    def _remove_roll_from_stats(stats: dict, dice: list[int]):
        roll = sum(dice)
        stats['accumulated_value'] -= roll
        # Below shouldn't happen due to game resetting if blackjack or bust
        if roll == D20Blackjack.BLACKJACK:
            stats['blackjacks'] -= 1
        elif roll >= D20Blackjack.BLACKJACK:
            stats['busts'] -= 1

    @staticmethod
    def _calculate_roll_result(dice: [int]) -> RollResult:
        if len(dice) != 2:
            return RollResult.INVALID_STATE

        total = sum(dice)
        if total == D20Blackjack.BLACKJACK:
            return RollResult.BLACKJACK

        if sum(dice) > D20Blackjack.BLACKJACK:
            return RollResult.BUST

        return RollResult.ROLLED


class D20BlackjackCommandHandler:
    def __init__(self, d20blackjack: D20Blackjack | PlayerRepository):
        self.game = d20blackjack if isinstance(d20blackjack, D20Blackjack) else D20Blackjack(d20blackjack)

    def handle(self, provider: str, channel: str, player_id: str, name: str, args: list[str]) -> str:
        if args and args[0] == "stats":
            return self._handle_stats(provider, player_id, name, args)

        player = self.game.get_player(provider, player_id, name)
        if args:
            return self._handle_reroll(channel, player, args[0])
        return self._handle_roll(channel, player)

    def _handle_roll(self, channel: str, player: Player) -> str:
        dice, result = self.game.roll_dice(channel, player)
        if result == RollResult.INVALID_STATE:  # shouldn't be possible
            return "Erm something went wrong. NotLikeThis"
        roll = self._format_dice(dice, result)
        if result == RollResult.BLACKJACK:
            return f"Blackjack! {roll}"
        if result == RollResult.BUST:
            return f"Bust! {roll}"
        return roll

    def _handle_reroll(self, channel: str, player: Player, face_value: str) -> str:
        try:
            face_value = int(face_value)
        except ValueError:
            return "That's not a valid d20 face value. smh"
        dice, result = self.game.reroll_dice(channel, player, face_value)
        if result == RollResult.INVALID_STATE:
            return "You haven't rolled yet. Susge"
        if result == RollResult.INVALID_FACE:
            return "That's not a valid d20 face value. smh"
        roll = self._format_dice(dice, result, reroll=True)
        if result == RollResult.BLACKJACK:
            return f"Blackjack! {roll}"
        if result == RollResult.BUST:
            return f"Bust! {roll}"
        return roll

    def _handle_stats(self, provider: str, player_id: str, name: str, args: list[str]) -> str:
        player = self.game.get_player(provider, player_id, name) if len(args) == 1 else self.game.get_player_by_name(provider, args[1])
        if not player:
            return f"Player {args[1]} not found. smh"
        stats = self.game.get_stats(player)
        if not stats:
            return f"No stats found for {player.name}. NotLikeThis"
        average = round(stats['accumulated_value'] / stats['rolls'], 2) if stats['rolls'] else 0
        percentage_rerolled = round(stats['rerolls'] / stats['rolls'] * 100) if stats['rolls'] else 0
        return f"{player.name} has rolled {stats['rolls']} times, rerolled {stats['rerolls']} times ({percentage_rerolled}%), got {stats['blackjacks']} blackjacks, and busted {stats['busts']} times. They have accumulated a total of {stats['accumulated_value']}, averaging {average} per roll."


    @staticmethod
    def _format_dice(dice: list[int], result: RollResult, reroll: bool = False) -> str:
        verb = "rerolled" if reroll else "rolled"
        total = sum(dice)
        goal = ""
        if result == RollResult.BUST:
            goal = f" You overshot blackjack by {total - D20Blackjack.BLACKJACK}. CatPats"
        elif result == RollResult.ROLLED:
            goal = f" You {'were' if reroll else 'are'} {D20Blackjack.BLACKJACK - total} short of a blackjack. {'CatPats' if reroll else 'Stare'}"
        return f"You {verb} [{dice[0]}] and [{dice[1]}] for {total}.{goal}"
