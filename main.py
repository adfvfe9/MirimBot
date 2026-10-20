"""미림봇 실행 파일.

    python main.py

봇 객체는 bot.py, 명령어는 features/ 폴더에 기능별로 나뉘어 있다.
  features/general.py      시간, 패치노트, 급식, 도움말, 청소 등
  features/economy.py      머니, 송금, 머니랭킹, 위로금, 기초수급, 파산
  features/enhance.py      강화
  features/stocks.py       주식
  features/gamble.py       도박, 가위바위보
  features/bank.py         은행 (대출/상환/적금/출금)
  features/tokens.py       토큰, 상점
  features/moderation.py   경고
  features/suggestions.py  건의
  features/admin.py        전체 초기화
  features/renewal.py      서버 연장 알림 (봇 주인에게 DM)
데이터 저장은 database.py (테이블 구조는 schema.sql).
"""
import asyncio
import os

import discord

import database as db
from bot import client

# import 하는 순간 각 파일의 명령어가 봇에 등록된다.
from features import (  # noqa: F401
    admin,
    bank,
    economy,
    enhance,
    gamble,
    general,
    moderation,
    renewal,
    stocks,
    suggestions,
    tokens,
)


@client.event
async def setup_hook():
    """봇이 디스코드에 접속하기 전에 한 번만 실행된다."""
    await db.connect()
    await stocks.load_market_state()
    await stocks.load_stock_prices()

    # 봇을 재시작해도 예전에 보낸 연장 알림 DM 의 [연장 완료] 버튼이 동작하게 등록
    client.add_view(renewal.RenewView())

    # 백그라운드 작업 (on_ready 는 재접속할 때마다 다시 불리므로 여기서 한 번만 시작)
    asyncio.create_task(stocks.market_cycle())
    asyncio.create_task(moderation.auto_remove_expired_roles())


# on_message는 커맨드와 충돌 방지 필요 → process_commands 사용
@client.event
async def on_message(message):
    if message.author.bot:
        return  # 봇의 메시지 무시

    # message.content.startswith()는 해당 문자로 시작하는 단어에 대해서
    # if message.content.startswith('테스트'):
        # await message.channel.send(f"{message.author} | {message.author.mention}, 안녕!")

    # if message.content == '안녕':
        # await message.channel.send(f"{message.author} | {message.author.mention}, 어서오세요!")

    # 개인 메시지로 전송
    # await message.author.send(f"{message.author} | {message.author.mention} 테스트")

    # 반드시 명령어 처리를 호출해줘야 commands.Bot의 @client.command가 작동함!
    await client.process_commands(message)


@client.event
async def on_ready():
    print(f'{client.user}에 로그인하였습니다.')

    await client.change_presence(
        status=discord.Status.online,
        activity=discord.Game('\'%도움말\'을 입력해보세요')
    )

    if not stocks.auto_update_stocks.is_running():
        stocks.auto_update_stocks.start()
        print("✅ 주식 자동 갱신 루프 시작됨")


client.run(os.environ["DISCORD_TOKEN"])
