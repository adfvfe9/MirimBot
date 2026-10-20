"""봇 객체(client)를 만드는 곳.

features/ 안의 모든 파일이 `from bot import client` 로 같은 봇을 가져다 쓴다.
"""
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()  # .env 에서 DISCORD_TOKEN, DATABASE_URL 불러오기

# Bot 선언
intents = discord.Intents.default()
intents.messages = True
intents.members = True # 멤버 정보 접근을 위해 필요
intents.message_content = True  # 필수! 안 켜면 on_message나 command 둘 다 안 먹음

client = commands.Bot(command_prefix='%', intents=intents)
