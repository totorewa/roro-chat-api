import logging
import os.path
import re
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.params import Depends
from fastapi.responses import PlainTextResponse, Response

from leaderboard import LeaderboardCommandHandler

load_dotenv()
DISABLE_CHANNEL_CHECK = os.getenv("DISABLE_CHANNEL_CHECK", "false").lower() == "true"

logging.basicConfig(level=logging.INFO)
logging.info(f"DISABLE_CHANNEL_CHECK: {DISABLE_CHANNEL_CHECK}")

def extract_nightbot_header_value(request: Request, header_name: str, key: str = "name") -> Optional[str]:
    header = request.headers.get(header_name)
    if not header:
        return None
    header_parts = header.split("&")
    header_dict = {}
    for part in header_parts:
        if "=" not in part:
            continue
        k, value = part.split("=")
        header_dict[k] = value
    return header_dict.get(key, "").lower()


def validate_channel(request: Request, b: str = None) -> Optional[str]:
    if DISABLE_CHANNEL_CHECK:
        return "test_channel"
    bot_type = "nb" if not b else b.lower()
    if bot_type == "nb":
        name = extract_nightbot_header_value(request, "Nightbot-Channel")
        if not name:
            raise HTTPException(status_code=401, detail="")
        return name
    elif bot_type == "fb":
        fb_header = request.headers.get("x-fossabot-channellogin")
        if not fb_header:
            raise HTTPException(status_code=401, detail="")
        return fb_header.lower()
    raise HTTPException(status_code=401, detail="")


def get_twitch_user(request: Request, b: str = None) -> Optional[str]:
    bot_type = "nb" if not b else b.lower()
    name: Optional[str] = None
    if bot_type == "nb":
        name = extract_nightbot_header_value(request, "Nightbot-User")
    elif bot_type == "fb":
        fb_header = request.headers.get("x-fossabot-message-userlogin")
        if fb_header:
            name = fb_header.lower()
    return name

def http_exception_handler(_: Request, exc: Exception) -> Response:
    exc = exc if isinstance(exc, HTTPException) else HTTPException(status_code=500, detail=str(exc))
    if exc.status_code == 401 or exc.status_code == 403:
        return PlainTextResponse(content=f"{exc.status_code}. That's not a rank, that's a status code. kek", status_code=exc.status_code)
    return PlainTextResponse(content="Erm something went wrong", status_code=exc.status_code)


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
    """
    Checks if a given Twitch channel is whitelisted.
    This is very rudimentary because it pulls the channel from an easily fakeable header.
    Unfortunately, Nightbot does not have a proper way to validate messages are actually coming it.
    Args:
        twitch_channel (str): The name of the Twitch channel to check.
    Returns:
        bool: True if the channel is whitelisted or if the channel check is disabled,
              False otherwise.
    """

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


leaderboard = LeaderboardCommandHandler()
app = FastAPI(title="Roro Chat API", version="0.2.0")
app.add_exception_handler(HTTPException, http_exception_handler)


@app.get("/api/twitch/leaderboard", response_class=PlainTextResponse)
@app.get("/api/twitch/aalb", response_class=PlainTextResponse) # Legacy
async def query_leaderboard(search: str = None, cat: str = "aa", cmd: str = None, channel: str = None,
                            twitch_channel: str = Depends(validate_channel),
                            twitch_user: str = Depends(get_twitch_user)):
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
