"""미림봇 실행 파일.

    python main.py

봇 객체는 bot.py, 명령어는 features/ 폴더에 기능별로 나뉘어 있다.
  features/general.py      시간, 패치노트, 급식, 도움말, 청소 등
  features/economy.py      머니, 송금, 머니랭킹, 위로금, 기초수급, 파산
  features/enhance.py      강화
  features/stocks.py       주식
  features/futures.py      레버리지 (롱/숏)
  features/news.py         주식 뉴스 (30~90분마다 랜덤 뉴스)
  features/assets.py       순자산, 자산랭킹
  features/gamble.py       도박, 가위바위보
  features/wordchain.py    끝말잇기 (1대1 / 다같이 / 랭킹, 스레드에서. 단어 목록: kkwords.txt)
  features/quiz.py         선착순 퀴즈 (1~2시간마다 퀴즈 채널에, 문제: quiz_math.py / quiz_gen.py / quiz_bank.py)
  features/bank.py         은행 (대출/상환/적금/출금)
  features/tokens.py       토큰, 상점
  features/crypto.py       비트코인 (토큰으로 거래)
  features/mining.py       코인 채굴 (1시간마다 블록)
  features/moderation.py   경고
  features/suggestions.py  건의
  features/admin.py        전체 초기화
  features/renewal.py      서버 연장 알림 (봇 주인에게 DM)
데이터 저장은 database.py (테이블 구조는 schema.sql).
"""
import asyncio

import discord

import database as db
import instance
from bot import client, get_token

# import 하는 순간 각 파일의 명령어가 봇에 등록된다.
from features import (  # noqa: F401
    abilities,
    admin,
    crypto,
    assets,
    bank,
    economy,
    enhance,
    gamble,
    general,
    market,
    mining,
    moderation,
    news,
    quiz,
    renewal,
    stocks,
    futures,
    suggestions,
    tokens,
    wordchain,
)


@client.event
async def setup_hook():
    """봇이 디스코드에 접속하기 전에 한 번만 실행된다."""
    await db.connect()

    # 다른 곳에서 봇이 이미 돌고 있으면 꺼질 때까지 기다린다. (중복 실행 방지, instance.py)
    await instance.wait_until_only_one()
    asyncio.create_task(instance.heartbeat(client))

    await stocks.load_market_state()
    await stocks.load_stock_prices()
    await abilities.sync_all()   # 능력 슬롯 레벨이 바뀌었으면 기존 아이템의 빈 슬롯을 채운다
    await crypto.load()
    await mining.load()

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


client.run(get_token())
