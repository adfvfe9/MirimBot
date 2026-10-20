"""봇 객체(client)를 만드는 곳.

features/ 안의 모든 파일이 `from bot import client` 로 같은 봇을 가져다 쓴다.
"""
import base64
import os
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

# .env 는 항상 이 파일과 같은 폴더의 것을 읽는다.
# override=True: 호스팅 쪽에 같은 이름의 환경변수가 이미 있어도 .env 값을 우선한다.
ENV_PATH = Path(__file__).resolve().parent / ".env"
_preset_token = "DISCORD_TOKEN" in os.environ
_env_loaded = load_dotenv(ENV_PATH, override=True)

# Bot 선언
intents = discord.Intents.default()
intents.messages = True
intents.members = True # 멤버 정보 접근을 위해 필요
intents.message_content = True  # 필수! 안 켜면 on_message나 command 둘 다 안 먹음

client = commands.Bot(command_prefix='%', intents=intents)


def get_token() -> str:
    """DISCORD_TOKEN 을 읽어서 앞뒤 공백/따옴표를 떼고, 토큰 자체는 숨긴 채 진단 정보를 출력한다."""
    raw = os.environ.get("DISCORD_TOKEN", "")
    token = raw.strip().strip('"').strip("'").strip()

    print(f"[설정] .env 파일: {ENV_PATH} ({'읽음' if _env_loaded else '없음 또는 비어 있음'})")
    if _preset_token:
        print("[설정] 호스팅에 DISCORD_TOKEN 환경변수가 이미 있었지만 .env 값을 우선 사용합니다.")
    if token != raw:
        print("[설정] 토큰 앞뒤의 공백/따옴표를 제거했습니다.")

    if not token:
        raise SystemExit("[설정] ❌ DISCORD_TOKEN 이 비어 있습니다. .env 를 확인하세요.")

    # 토큰 첫 부분은 봇 ID 를 base64 로 적은 것 (봇 ID 는 공개 정보라 출력해도 안전)
    parts = token.split(".")
    try:
        first = parts[0] + "=" * (-len(parts[0]) % 4)
        bot_id = base64.urlsafe_b64decode(first).decode()
        assert bot_id.isdigit() and len(parts) == 3
    except Exception:
        bot_id = None

    if bot_id:
        print(f"[설정] 토큰 길이 {len(token)}자, 봇 ID {bot_id} "
              "(개발자 페이지의 Application ID 와 같아야 합니다)")
    else:
        print(f"[설정] ⚠️ 토큰 형식이 이상합니다 (길이 {len(token)}자). 잘못 복사했을 수 있어요.")
    return token
