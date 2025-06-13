import os
from dotenv import load_dotenv

load_dotenv()  # .env 파일에서 환경변수 불러오기

TOKEN = os.getenv("DISCORD_TOKEN")