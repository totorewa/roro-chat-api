import logging
import os.path
import re
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.params import Depends
from fastapi.responses import PlainTextResponse, Response

from db.player import PlayerRepository
from games.d20blackjack import D20BlackjackCommandHandler, D20Blackjack
from leaderboard import LeaderboardCommandHandler
from source_verify import NightbotVerifier

load_dotenv()
DISABLE_CHANNEL_CHECK = os.getenv("DISABLE_CHANNEL_CHECK", "false").lower() == "true"

logging.basicConfig(level=logging.INFO)
logging.info(f"DISABLE_CHANNEL_CHECK: {DISABLE_CHANNEL_CHECK}")


def construct_nightbot_header_dict(request: Request, header_name: str) -> dict:
    header = request.headers.get(header_name)
    if not header:
        return {}
    header_parts = header.split("&")
    header_dict = {}
    for part in header_parts:
        if "=" not in part:
            continue
        k, value = part.split("=")
        header_dict[k] = value
    return header_dict


def validate_nightbot_channel(request: Request) -> Optional[str]:
    if DISABLE_CHANNEL_CHECK:
        return "test_channel"
    header_dict = construct_nightbot_header_dict(request, "Nightbot-Channel")
    name = header_dict.get("name", None)
    if not name or header_dict.get("provider", "").lower() != "twitch":
        raise HTTPException(status_code=401, detail="")
    return name


def validate_fossabot_channel(request: Request) -> Optional[str]:
    if DISABLE_CHANNEL_CHECK:
        return "test_channel"
    fb_header = request.headers.get("x-fossabot-channellogin")
    if not fb_header:
        raise HTTPException(status_code=401, detail="")
    return fb_header.lower()


def get_nightbot_user(request: Request) -> tuple[Optional[str], Optional[str], Optional[str]]:
    if DISABLE_CHANNEL_CHECK:
        return "test_user", "test_provider", "test_id"
    header_dict = construct_nightbot_header_dict(request, "Nightbot-User")
    return header_dict.get("name", None), header_dict.get("provider", None), header_dict.get("providerId", None)


def get_fossabot_user(request: Request) -> Optional[str]:
    fb_header = request.headers.get("x-fossabot-message-userlogin")
    return fb_header.lower() if fb_header else None


def http_exception_handler(_: Request, exc: Exception) -> Response:
    exc = exc if isinstance(exc, HTTPException) else HTTPException(status_code=500, detail=str(exc))
    # Return a 200 status code so that the bot displays the message
    if exc.status_code == 401 or exc.status_code == 403:
        return PlainTextResponse(content=f"{exc.status_code}. That's not a rank, that's a status code. kek",
                                 status_code=200)
    logging.error(exc.detail)
    return PlainTextResponse(content="Erm something went wrong", status_code=200)


def create_response(response: str) -> PlainTextResponse:
    return PlainTextResponse(content=response, media_type="text/plain")


users_cache = None
users_expiry = 0


def get_user_specific_suffix(user: str) -> Optional[str]:
    global users_cache
    global users_expiry
    import json
    import time
    if users_cache is None or users_expiry <= time.time():
        try:
            with open(os.path.join('config', 'users.json'), 'r') as file:
                users_cache = json.load(file)
        except FileNotFoundError:
            users_cache = {}
        users_expiry = time.time() + 3600
    return users_cache.get(user, {}).get("suffix", None)


channels_cache = None
channels_expiry = 0


def is_channel_whitelisted(twitch_channel: str) -> bool:
    global channels_cache
    global channels_expiry
    if DISABLE_CHANNEL_CHECK:
        return True
    import time
    if channels_cache is None or channels_expiry <= time.time():
        import json
        try:
            with open(os.path.join('config', 'channels.json'), 'r') as file:
                channels_cache = json.load(file)
        except FileNotFoundError:
            channels_cache = []
        channels_expiry = time.time() + 3600
    return twitch_channel in channels_cache


nightbot_verifier = NightbotVerifier()

player_repo = PlayerRepository()
leaderboard = LeaderboardCommandHandler()
d20blackjack = D20BlackjackCommandHandler(player_repo)
app = FastAPI(title="Roro Chat API", version="0.2.0")
app.add_exception_handler(HTTPException, http_exception_handler)


@app.get("/api/nightbot/leaderboard", response_class=PlainTextResponse)
@app.get("/api/nightbot/roro", response_class=PlainTextResponse) # For remapping to other commands
@app.get("/api/twitch/aalb", response_class=PlainTextResponse)  # Legacy
async def nightbot_leaderboard(request: Request, search: str = None, cat: str = "aa", cmd: str = None,
                               channel: str = None,
                               twitch_channel: str = Depends(validate_nightbot_channel)):
    if not nightbot_verifier.verify(request):
        raise HTTPException(status_code=401, detail="")
    twitch_user, _, _ = get_nightbot_user(request)
    return await _query_leaderboard(search, cat, cmd, channel, twitch_channel, twitch_user)


@app.get("/api/fossabot/leaderboard", response_class=PlainTextResponse)
async def fossabot_leaderboard(search: str = None, cat: str = "aa", cmd: str = None, channel: str = None,
                               twitch_channel: str = Depends(validate_fossabot_channel),
                               twitch_user: str = Depends(get_fossabot_user)):
    raise HTTPException(status_code=401)  # Fossabot not supported yet until verifier is implemented
    # return await _query_leaderboard(search, cat, cmd, channel, twitch_channel, twitch_user)

@app.get("/api/nightbot/d20blackjack", response_class=PlainTextResponse)
@app.get("/api/nightbot/roro2", response_class=PlainTextResponse) # For remapping to other commands
async def nightbot_d20blackjack(request: Request,
                                cmd: str = None,
                                twitch_channel: str = Depends(validate_nightbot_channel),
                                args: str = None):
    if not nightbot_verifier.verify(request):
        raise HTTPException(status_code=401, detail="")
    args = (args or "").strip().lower()
    if args == "help":
        cmd = cmd or "!<command>"
        return create_response(f"Roll 2 d20 to get {D20Blackjack.BLACKJACK}! If you go over, you bust! You can re-roll one die ONCE using {cmd} <face value>.")
    twitch_user, twitch_user_id, provider = get_nightbot_user(request)
    args = args.split(" ") if args else []
    return d20blackjack.handle(provider, twitch_channel, twitch_user_id, twitch_user, args)


async def _query_leaderboard(search: Optional[str], cat: str, cmd: Optional[str], channel: Optional[str],
                             twitch_channel: str,
                             twitch_user: str):
    if search == "help":
        command_name = cmd if cmd else "!<command>"
        return create_response(
            f"Usage: {command_name} [board] (<name> | <rank> | <<time> | [>]<time> | top <number> | range <from> <to> | count)")
    channel = channel or twitch_channel
    search = search or ""
    logging.info(f"[{twitch_channel}] {twitch_user} ({cat}) -> {search}")
    args = re.sub(r"[^a-zA-Z0-9 !.:<>_]", "", search.strip()).split(" ")
    if args and not args[0]:
        args = []
    suffix = get_user_specific_suffix(twitch_user)
    output = await leaderboard.handle(channel=channel, category=cat, args=args, suffix=suffix)
    return create_response(output)
