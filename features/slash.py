"""슬래시 명령어 (/): 기존 %명령어를 그대로 불러 쓰는 얇은 껍데기

- %명령어는 그대로 두고, 같은 이름의 /명령어를 하나 더 만든다. (/주식구매 = %주식구매)
  동작은 %명령어 함수 한 곳에만 있다. 여기서는 입력칸 · 설명 · 자동완성만 정하고 그 함수를 부른다.
- 관리자 명령어는 /관리 아래로 묶었다. (관리자에게만 보이고, 디스코드 한도 100개를 넘지 않게)
- 개발자용 (건의목록 · 건의제거 · 연장 · 연장확인, DM 전용) 과 장난 명령어는 %로만 쓴다.

SlashContext: %명령어 함수가 쓰는 ctx 를 흉내 낸다.
  - 처음에 "생각 중…"으로 먼저 답해 두고(3초 제한), ctx.send 는 그 뒤에 이어서 보낸다.
  - ctx.message.delete() 는 지울 메시지가 없으니 아무것도 안 한다.
  - 명령어가 아무 말도 안 했으면 "생각 중…"을 지운다.
봇이 켜질 때 sync() 로 디스코드에 등록한다. (목록이 바뀌었을 때만)
"""
import asyncio
import contextlib
import hashlib
import json
import traceback

import discord
from discord import app_commands

import database as db
from bot import client
from features import (
    abilities, admin, assets, audit, bank, crypto, economy, enhance, futures, gamble, general, health,
    market, mining, missions, moderation, music, news, orders, quiz, roleshop, school, stocks,
    suggestions, titles, tokens, tts, wordchain,
)

tree = client.tree
SYNC_KEY = "slash_commands_hash"


# ───────────── ctx 흉내 ─────────────

class _Message:
    def __init__(self, interaction, mentions):
        self.id = interaction.id
        self.content = ""
        self.mentions = list(mentions)

    async def delete(self, *args, **kwargs):
        pass


class SlashContext:
    def __init__(self, interaction, mentions=()):
        self.interaction = interaction
        self.author = interaction.user
        self.guild = interaction.guild
        self.channel = interaction.channel
        self.bot = client
        self.message = _Message(interaction, mentions)
        self.command = None
        self.invoked_with = interaction.command.name if interaction.command else None
        self.sent = False

    async def send(self, content=None, *, delete_after=None, **kwargs):
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        message = await self.interaction.followup.send(content, wait=True, **kwargs)
        self.sent = True
        if delete_after:
            async def later():
                await asyncio.sleep(delete_after)
                with contextlib.suppress(discord.HTTPException):
                    await message.delete()
            asyncio.create_task(later())
        return message

    def typing(self):
        return _NoTyping()      # 이미 "생각 중…"으로 답해 둬서 따로 표시할 필요가 없다


class _NoTyping:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


async def run(interaction, command, *args, mentions=(), **kwargs):
    """%명령어 함수(command)를 슬래시로 실행한다."""
    if not interaction.response.is_done():
        await interaction.response.defer(thinking=True)
    ctx = SlashContext(interaction, mentions)
    try:
        await command.callback(ctx, *args, **kwargs)
    except Exception as e:
        print(f"[슬래시 에러] /{ctx.invoked_with} ({interaction.user}): {type(e).__name__} {e}")
        traceback.print_exception(type(e), e, e.__traceback__)
        with contextlib.suppress(discord.HTTPException):
            await ctx.send("❌ 처리하다가 오류가 났어요. 같은 명령어를 `%`로 써보거나, 계속되면 `%건의`로 알려주세요.")
    if not ctx.sent:
        with contextlib.suppress(discord.HTTPException):
            await interaction.delete_original_response()     # 아무 말도 안 한 명령어: "생각 중…" 지우기


def command(name, description):
    """서버에서만 쓰는 /명령어"""
    def deco(fn):
        return app_commands.guild_only()(tree.command(name=name, description=description)(fn))
    return deco


# ───────────── 자동완성 ─────────────

def _choices(values, current, limit=25):
    current = (current or "").lower()
    picked = [v for v in values if current in v.lower()]
    return [app_commands.Choice(name=v, value=v) for v in picked[:limit]]


async def ac_stock(interaction, current):
    return _choices(sorted(stocks.stock_prices), current)


async def ac_my_item(interaction, current):
    return _choices(list(await db.get_enhance_items(interaction.user.id)), current)


async def ac_my_title(interaction, current):
    owned = await db.get_titles(interaction.user.id)
    names = [titles.BY_KEY[k]["name"] for k in owned if k in titles.BY_KEY]
    return _choices(names, current)


async def ac_position(interaction, current):
    values = [str(p["id"]) for p in await db.get_positions(interaction.user.id)] + ["전체"]
    return _choices(values, current)


async def ac_all(interaction, current):
    return _choices(["전부"], current)


DIRECTION = [app_commands.Choice(name="이하가 되면", value="이하"), app_commands.Choice(name="이상이 되면", value="이상")]


# ───────────── 돈 · 기본 ─────────────

@command("머니", "내 (또는 다른 사람의) 잔액과 미납금")
@app_commands.describe(유저="볼 사람 (안 고르면 나)")
async def s_money(i: discord.Interaction, 유저: discord.Member = None):
    await run(i, economy.money, 유저)


@command("송금", "다른 사람에게 돈 보내기 (수수료 10%, 하루 10만)")
@app_commands.describe(유저="받을 사람", 금액="보낼 금액")
async def s_send(i: discord.Interaction, 유저: discord.Member, 금액: app_commands.Range[int, 1]):
    await run(i, economy.send, 유저, 금액)


@command("머니랭킹", "현금 순위")
async def s_money_rank(i: discord.Interaction):
    await run(i, economy.money_rank)


@command("기초수급", "하루 한 번 공짜 돈 (연속으로 받으면 늘어나요)")
async def s_welfare(i: discord.Interaction):
    await run(i, economy.welfare)


@command("위로금", "잔액이 1천 미만일 때 하루 한 번")
async def s_consolation(i: discord.Interaction):
    await run(i, economy.consolation)


@command("파산", "빚이 있을 때만: 빚 대신 가진 것을 전부 잃어요")
async def s_bankrupt(i: discord.Interaction):
    await run(i, economy.파산)


@command("은행", "대출 · 상환 · 적금 · 출금")
async def s_bank(i: discord.Interaction):
    await run(i, bank.bank)


@command("미션", "오늘의 미션 3개 (다 깨면 토큰)")
async def s_missions(i: discord.Interaction):
    await run(i, missions.daily_missions)


@command("자산", "순자산 (현금 · 주식 · 적금 · 레버리지 · 강화템)")
@app_commands.describe(유저="볼 사람 (안 고르면 나)")
async def s_assets(i: discord.Interaction, 유저: discord.Member = None):
    await run(i, assets.assets, 유저)


@command("자산랭킹", "순자산 순위")
async def s_asset_rank(i: discord.Interaction):
    await run(i, assets.asset_rank)


@command("자산그래프", "순자산 변화 그래프 (친구랑 비교 가능)")
@app_commands.describe(일="최근 며칠 (기본 7, 최대 30)", 친구1="같이 볼 사람", 친구2="같이 볼 사람", 친구3="같이 볼 사람")
async def s_asset_chart(i: discord.Interaction, 일: app_commands.Range[int, 1, 30] = None,
                        친구1: discord.Member = None, 친구2: discord.Member = None, 친구3: discord.Member = None):
    friends = [m for m in (친구1, 친구2, 친구3) if m]
    mentions = ([i.user] + friends) if friends else []
    await run(i, assets.asset_chart, *([str(일)] if 일 else []), mentions=mentions)


# ───────────── 주식 ─────────────

@command("주식", "지금 주식 시세")
async def s_stock(i: discord.Interaction):
    await run(i, stocks.stock)


@command("주식구매", "주식 사기")
@app_commands.describe(주식="종목", 수량="몇 주")
@app_commands.autocomplete(주식=ac_stock)
async def s_buy(i: discord.Interaction, 주식: str, 수량: app_commands.Range[int, 1]):
    await run(i, stocks.buy_stock, 주식, 수량)


@command("주식판매", "주식 팔기 (수수료 2%, 30분 안에 팔면 8%)")
@app_commands.describe(주식="종목", 수량="몇 주")
@app_commands.autocomplete(주식=ac_stock)
async def s_sell(i: discord.Interaction, 주식: str, 수량: app_commands.Range[int, 1]):
    await run(i, stocks.sell_stock, 주식, 수량)


@command("주식전량구매", "가진 돈으로 살 수 있는 만큼 사기")
@app_commands.describe(주식="종목")
@app_commands.autocomplete(주식=ac_stock)
async def s_buy_all(i: discord.Interaction, 주식: str):
    await run(i, stocks.buy_all_stock, 주식)


@command("주식절반구매", "살 수 있는 만큼의 절반 사기")
@app_commands.describe(주식="종목")
@app_commands.autocomplete(주식=ac_stock)
async def s_buy_half(i: discord.Interaction, 주식: str):
    await run(i, stocks.buy_half_stock, 주식)


@command("주식전량판매", "주식 전부 팔기 (종목을 안 고르면 모든 종목)")
@app_commands.describe(주식="종목 (안 고르면 전부)")
@app_commands.autocomplete(주식=ac_stock)
async def s_sell_all(i: discord.Interaction, 주식: str = None):
    await run(i, stocks.sell_all_stock, 주식)


@command("주식확인", "가진 주식과 손익")
@app_commands.describe(유저="볼 사람 (안 고르면 나)")
async def s_stock_status(i: discord.Interaction, 유저: discord.Member = None):
    await run(i, stocks.stock_status, 유저)


@command("주가그래프", "주가 그래프 (60분 무료, 60분 더 볼 때마다 2,000 byte)")
@app_commands.describe(주식="종목 (안 고르면 전부)", 분="최근 몇 분 (기본 60, 최대 1440)")
@app_commands.autocomplete(주식=ac_stock)
async def s_stock_chart(i: discord.Interaction, 주식: str = None, 분: app_commands.Range[int, 1, 1440] = None):
    await run(i, stocks.stock_chart, *[str(a) for a in (주식, 분) if a])


@command("주식랭킹", "주식 수익 순위")
async def s_stock_rank(i: discord.Interaction):
    await run(i, stocks.stock_rank)


@command("뉴스", "최근 주식 뉴스")
async def s_news(i: discord.Interaction):
    await run(i, news.news)


@command("예약구매", "가격이 닿으면 자동으로 사기 (토큰 1개)")
@app_commands.describe(주식="종목", 수량="몇 주", 가격="이 가격에 닿으면", 조건="기본: 이하가 되면")
@app_commands.autocomplete(주식=ac_stock)
@app_commands.choices(조건=DIRECTION)
async def s_order_buy(i: discord.Interaction, 주식: str, 수량: app_commands.Range[int, 1], 가격: float, 조건: str = None):
    await run(i, orders.order_buy, 주식, str(수량), str(가격), *([조건] if 조건 else []))


@command("예약판매", "가격이 닿으면 자동으로 팔기 (토큰 1개, 이하 = 손절)")
@app_commands.describe(주식="종목", 수량="몇 주 또는 전부", 가격="이 가격에 닿으면", 조건="기본: 이상이 되면")
@app_commands.autocomplete(주식=ac_stock, 수량=ac_all)
@app_commands.choices(조건=DIRECTION)
async def s_order_sell(i: discord.Interaction, 주식: str, 수량: str, 가격: float, 조건: str = None):
    await run(i, orders.order_sell, 주식, 수량, str(가격), *([조건] if 조건 else []))


@command("예약목록", "내 주식 예약 보기 · 취소")
async def s_order_list(i: discord.Interaction):
    await run(i, orders.order_list)


@command("롱", "레버리지 롱: 오르면 이득")
@app_commands.describe(주식="종목", 증거금="걸 돈", 배율="몇 배 (기본 1)")
@app_commands.autocomplete(주식=ac_stock)
async def s_long(i: discord.Interaction, 주식: str, 증거금: app_commands.Range[int, 1], 배율: app_commands.Range[int, 1] = 1):
    await run(i, futures.open_long, 주식, 증거금, 배율)


@command("숏", "레버리지 숏: 내리면 이득")
@app_commands.describe(주식="종목", 증거금="걸 돈", 배율="몇 배 (기본 1)")
@app_commands.autocomplete(주식=ac_stock)
async def s_short(i: discord.Interaction, 주식: str, 증거금: app_commands.Range[int, 1], 배율: app_commands.Range[int, 1] = 1):
    await run(i, futures.open_short, 주식, 증거금, 배율)


@command("포지션", "레버리지 포지션 · 청산가")
@app_commands.describe(유저="볼 사람 (안 고르면 나)")
async def s_positions(i: discord.Interaction, 유저: discord.Member = None):
    await run(i, futures.positions, 유저)


@command("청산", "레버리지 포지션 정리하고 돈 받기")
@app_commands.describe(번호="포지션 번호 또는 전체")
@app_commands.autocomplete(번호=ac_position)
async def s_close(i: discord.Interaction, 번호: str = None):
    await run(i, futures.close_position, 번호)


# ───────────── 강화 ─────────────

@command("강화", "아이템 만들기 · 강화 (목표를 쓰면 자동 강화)")
@app_commands.describe(아이템="아이템 이름 (없으면 새로 만들어요)", 목표="자동 강화 목표 레벨", 제물="제물로 바칠 아이템 이름 (여러 개면 띄어쓰기)")
@app_commands.autocomplete(아이템=ac_my_item)
async def s_enhance(i: discord.Interaction, 아이템: str, 목표: app_commands.Range[int, 2, 13] = None, 제물: str = None):
    args = ([str(목표)] if 목표 else []) + (제물.split() if 제물 else [])
    await run(i, enhance.enhance, 아이템, *args)


@command("강화목록", "가진 강화 아이템")
@app_commands.describe(유저="볼 사람 (안 고르면 나)")
async def s_enhance_list(i: discord.Interaction, 유저: discord.Member = None):
    await run(i, enhance.enhance_list, 유저)


@command("강화판매", "강화 아이템을 봇에게 팔기")
@app_commands.describe(아이템="팔 아이템")
@app_commands.autocomplete(아이템=ac_my_item)
async def s_enhance_sell(i: discord.Interaction, 아이템: str):
    await run(i, enhance.sell_enhance, 아이템)


@command("강화확률", "강화 확률표 · 비용 · 판매가")
async def s_enhance_odds(i: discord.Interaction):
    await run(i, enhance.enhance_odds)


@command("강화랭킹", "최고 강화 아이템 순위")
async def s_enhance_rank(i: discord.Interaction):
    await run(i, enhance.enhance_rank)


@command("강화능력설정", "아이템 능력 슬롯 보기 · 잠금 · 리롤")
@app_commands.describe(아이템="아이템")
@app_commands.autocomplete(아이템=ac_my_item)
async def s_ability_panel(i: discord.Interaction, 아이템: str):
    await run(i, abilities.ability_panel, 아이템)


@command("리롤", "잠그지 않은 능력 슬롯 다시 뽑기 (토큰)")
@app_commands.describe(아이템="아이템")
@app_commands.autocomplete(아이템=ac_my_item)
async def s_reroll(i: discord.Interaction, 아이템: str):
    await run(i, abilities.reroll_command, 아이템)


@command("내능력", "모든 아이템 능력을 합친 효과")
@app_commands.describe(유저="볼 사람 (안 고르면 나)")
async def s_my_abilities(i: discord.Interaction, 유저: discord.Member = None):
    await run(i, abilities.my_abilities, 유저)


@command("암시장", "유저끼리 강화 아이템 · 토큰 사고팔기")
async def s_market(i: discord.Interaction):
    await run(i, market.black_market)


# ───────────── 토큰 · 코인 · 채굴 ─────────────

@command("토큰", "내 토큰과 지금 토큰 가격")
@app_commands.describe(유저="볼 사람 (안 고르면 나)")
async def s_token(i: discord.Interaction, 유저: discord.Member = None):
    await run(i, tokens.check_token, 유저)


@command("토큰구매", "byte 로 토큰 사기 (살 때마다 2배, 하루에 4배씩 떨어짐)")
@app_commands.describe(개수="몇 개 (기본 1)")
async def s_token_buy(i: discord.Interaction, 개수: app_commands.Range[int, 1] = 1):
    await run(i, tokens.buy_token, 개수)


@command("토큰최대교환", "가진 돈으로 살 수 있는 만큼 토큰 사기")
async def s_token_max(i: discord.Interaction):
    await run(i, tokens.buy_token_max)


@command("코인", "비트코인 시세 (토큰 단위)")
async def s_coin(i: discord.Interaction):
    await run(i, crypto.coin)


@command("코인구매", "토큰으로 비트코인 사기 (수수료 1%)")
@app_commands.describe(토큰="쓸 토큰 수")
async def s_coin_buy(i: discord.Interaction, 토큰: app_commands.Range[int, 1]):
    await run(i, crypto.coin_buy, 토큰)


@command("코인판매", "비트코인 팔고 토큰 받기 (수수료 1%)")
@app_commands.describe(개수="팔 개수 또는 전부 (안 쓰면 전부)")
@app_commands.autocomplete(개수=ac_all)
async def s_coin_sell(i: discord.Interaction, 개수: str = None):
    await run(i, crypto.coin_sell, 개수)


@command("코인확인", "가진 비트코인과 손익")
@app_commands.describe(유저="볼 사람 (안 고르면 나)")
async def s_coin_status(i: discord.Interaction, 유저: discord.Member = None):
    await run(i, crypto.coin_status, 유저)


@command("코인그래프", "비트코인 그래프 (60분 무료)")
@app_commands.describe(분="최근 몇 분 (기본 60, 최대 1440)")
async def s_coin_chart(i: discord.Interaction, 분: app_commands.Range[int, 1, 1440] = 60):
    await run(i, crypto.coin_chart, 분)


@command("코인랭킹", "비트코인 보유 순위")
async def s_coin_rank(i: discord.Interaction):
    await run(i, crypto.coin_rank)


@command("채굴", "내 채굴기 · 몫 · 다음 블록")
@app_commands.describe(유저="볼 사람 (안 고르면 나)")
async def s_mining(i: discord.Interaction, 유저: discord.Member = None):
    await run(i, mining.mining_status, 유저)


@command("채굴기구매", "채굴기 사기 (5만 byte, 최대 3대)")
async def s_mining_buy(i: discord.Interaction):
    await run(i, mining.mining_buy)


@command("채굴기업그레이드", "채굴기 레벨 올리기 (최대 Lv5)")
@app_commands.describe(번호="채굴기 번호 (안 쓰면 가장 낮은 것)")
async def s_mining_upgrade(i: discord.Interaction, 번호: app_commands.Range[int, 1, 3] = None):
    await run(i, mining.mining_upgrade, 번호)


@command("채굴켜기", "채굴 켜기 (블록마다 전기세)")
async def s_mining_on(i: discord.Interaction):
    await run(i, mining.mining_on)


@command("채굴끄기", "채굴 끄기")
async def s_mining_off(i: discord.Interaction):
    await run(i, mining.mining_off)


@command("채굴랭킹", "캔 코인 순위")
async def s_mining_rank(i: discord.Interaction):
    await run(i, mining.mining_rank)


# ───────────── 놀이 ─────────────

@command("가위바위보", "이길 때마다 보상 2배! (하루 5판)")
async def s_rps(i: discord.Interaction):
    await run(i, gamble.rps)


@command("도박", "꽝 50% / 최대 7배 (최대 10만)")
@app_commands.describe(금액="걸 돈")
async def s_gamble(i: discord.Interaction, 금액: app_commands.Range[int, 1]):
    await run(i, gamble.gamble, 금액)


@command("도박올인", "최대 판돈까지 전부 걸기")
async def s_gamble_allin(i: discord.Interaction):
    await run(i, gamble.gamble_allin)


@command("도박랭킹", "도박 수익 순위")
async def s_gamble_rank(i: discord.Interaction):
    await run(i, gamble.gamble_rank)


@command("끝말잇기", "끝말잇기 (봇과 1대1 · 연습 · 친구들과 같이)")
@app_commands.describe(모드="기본: 봇과 1대1 (보상 · 랭킹)")
@app_commands.choices(모드=[app_commands.Choice(name="봇과 1대1", value="1대1"),
                           app_commands.Choice(name="연습 (보상 없음)", value="연습"),
                           app_commands.Choice(name="친구들과 같이", value="같이")])
async def s_wordchain(i: discord.Interaction, 모드: str = None):
    await run(i, wordchain.wordchain, None if 모드 in (None, "1대1") else 모드)


@command("끝말잇기랭킹", "끝말잇기 한 판 최고 점수 순위")
@app_commands.describe(난이도="안 고르면 둘 다")
@app_commands.choices(난이도=[app_commands.Choice(name="어려움", value="어려움"), app_commands.Choice(name="지옥", value="지옥")])
async def s_wordchain_rank(i: discord.Interaction, 난이도: str = None):
    await run(i, wordchain.wordchain_rank, 난이도)


# ───────────── 자랑 · 상점 ─────────────

@command("칭호", "칭호 28개와 진행도")
@app_commands.describe(유저="볼 사람 (안 고르면 나)")
async def s_titles(i: discord.Interaction, 유저: discord.Member = None):
    await run(i, titles.titles_command, 유저)


@command("칭호장착", "칭호 하나를 이름 앞에 달기")
@app_commands.describe(칭호="가진 칭호")
@app_commands.autocomplete(칭호=ac_my_title)
async def s_title_equip(i: discord.Interaction, 칭호: str):
    await run(i, titles.title_equip, name=칭호)


@command("칭호해제", "장착한 칭호 빼기")
async def s_title_unequip(i: discord.Interaction):
    await run(i, titles.title_unequip)


@command("칭호랭킹", "가진 칭호 수 순위")
async def s_title_rank(i: discord.Interaction):
    await run(i, titles.title_rank)


@command("역할상점", "byte 로 디스코드 역할 사기")
async def s_role_shop(i: discord.Interaction):
    await run(i, roleshop.role_shop)


@command("내역할", "산 역할과 남은 기간")
async def s_my_roles(i: discord.Interaction):
    await run(i, roleshop.my_shop_roles)


# ───────────── 학교 ─────────────

@command("급식", "급식 (오늘 · 내일 · 날짜)")
@app_commands.describe(날짜="내일, 모레, 1024, 10/24 (안 쓰면 오늘)")
async def s_meal(i: discord.Interaction, 날짜: str = None):
    await run(i, school.school_meal, when=날짜)


@command("시간표", "시간표 (반을 안 쓰면 %내반 으로 정한 반)")
@app_commands.describe(학년="학년", 반="반", 날짜="내일, 1024 … (안 쓰면 오늘)")
async def s_timetable(i: discord.Interaction, 학년: app_commands.Range[int, 1, 6] = None, 반: app_commands.Range[int, 1, 30] = None, 날짜: str = None):
    args = ([str(학년), str(반)] if 학년 and 반 else []) + ([날짜] if 날짜 else [])
    await run(i, school.school_timetable, *args)


@command("내반", "내 반 저장 (/시간표 에 쓰여요)")
@app_commands.describe(학년="학년", 반="반")
async def s_my_class(i: discord.Interaction, 학년: app_commands.Range[int, 1, 6], 반: app_commands.Range[int, 1, 30]):
    await run(i, school.my_class, 학년, str(반))


@command("학사일정", "그 달 학사일정")
@app_commands.describe(월="몇 월 (안 쓰면 이번 달)")
async def s_schedule(i: discord.Interaction, 월: app_commands.Range[int, 1, 12] = None):
    await run(i, school.school_schedule, 월)


# ───────────── 통화방 ─────────────

@command("재생", "통화방에서 유튜브 노래 틀기")
@app_commands.describe(노래="유튜브 링크 또는 제목")
async def s_play(i: discord.Interaction, 노래: str):
    await run(i, music.music_play, query=노래)


@command("스킵", "지금 노래 넘기기")
async def s_skip(i: discord.Interaction):
    await run(i, music.music_skip)


@command("일시정지", "노래 일시정지")
async def s_pause(i: discord.Interaction):
    await run(i, music.music_pause)


@command("다시재생", "일시정지한 노래 이어서 듣기")
async def s_resume(i: discord.Interaction):
    await run(i, music.music_resume)


@command("정지", "노래 멈추고 대기열 비우기")
async def s_stop(i: discord.Interaction):
    await run(i, music.music_stop)


@command("대기열", "지금 노래와 다음 노래들")
async def s_queue(i: discord.Interaction):
    await run(i, music.music_queue)


@command("지금곡", "지금 노래 정보 · 버튼")
async def s_now(i: discord.Interaction):
    await run(i, music.music_now)


@command("볼륨", "음악 볼륨 (0~100)")
@app_commands.describe(값="0~100 (안 쓰면 지금 볼륨)")
async def s_volume(i: discord.Interaction, 값: app_commands.Range[int, 0, 100] = None):
    await run(i, music.music_volume, 값)


@command("읽어", "이 채널 채팅을 통화방에서 읽어주기 (TTS)")
async def s_tts(i: discord.Interaction):
    await run(i, tts.tts_start)


@command("나가", "봇을 통화방에서 내보내기 (TTS · 음악 끝)")
async def s_leave(i: discord.Interaction):
    await run(i, tts.voice_leave)


@command("줄임말설정", "TTS 가 글자를 어떻게 읽을지 (- 면 안 읽기)")
@app_commands.describe(글자="바꿀 글자 · 초성 · 기호", 읽을말="이렇게 읽기 (- 면 안 읽기)")
async def s_abbrev_set(i: discord.Interaction, 글자: str, 읽을말: str):
    await run(i, tts.tts_abbrev_set, 글자, reading=읽을말)


@command("줄임말삭제", "TTS 줄임말 지우기")
@app_commands.describe(글자="지울 글자")
async def s_abbrev_del(i: discord.Interaction, 글자: str):
    await run(i, tts.tts_abbrev_set, "삭제", reading=글자)


@command("줄임말", "이 서버의 TTS 줄임말 목록")
async def s_abbrev_list(i: discord.Interaction):
    await run(i, tts.tts_abbrev_list)


# ───────────── 기타 ─────────────

@command("도움말", "미림봇 길라잡이 · 모든 명령어 (노션)")
async def s_help(i: discord.Interaction):
    await run(i, general.명령어)


@command("패치노트", "최근 업데이트 내용")
async def s_patchnote(i: discord.Interaction):
    await run(i, general.patchnote)


@command("시간", "지금 한국 시간")
async def s_time(i: discord.Interaction):
    await run(i, general.timeget)


@command("핑", "어디가 느린지 재보기 (디스코드 · DB · 봇)")
async def s_ping(i: discord.Interaction):
    await run(i, health.health_ping)


@command("건의", "미림봇에 건의하기 (1시간에 한 번)")
@app_commands.describe(내용="건의할 내용")
async def s_suggest(i: discord.Interaction, 내용: str):
    await run(i, suggestions.suggestion, content=내용)


@command("경고확인", "경고 확인")
@app_commands.describe(유저="볼 사람 (안 고르면 나)")
async def s_warnings(i: discord.Interaction, 유저: discord.Member = None):
    await run(i, moderation.check_warning, target=유저.mention if 유저 else None)


# ───────────── 관리자: /관리 ─────────────

class Admin(app_commands.Group):
    async def interaction_check(self, interaction):
        if interaction.guild is None or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ 관리자만 쓸 수 있어요.", ephemeral=True)
            return False
        return True


manage = Admin(name="관리", description="관리자 명령어", guild_only=True,
               default_permissions=discord.Permissions(administrator=True))
tree.add_command(manage)


def admin_command(name, description):
    return manage.command(name=name, description=description)


@admin_command("로그", "명령어 · 버튼 기록 보기")
@app_commands.describe(유저="이 사람만", 찾을말="이름이나 내용에 들어간 말 (관리자 = 관리자 명령어만)", 개수="최대 50")
async def a_log(i: discord.Interaction, 유저: discord.Member = None, 찾을말: str = None, 개수: app_commands.Range[int, 1, 50] = None):
    args = ([찾을말] if 찾을말 else []) + ([str(개수)] if 개수 else [])
    await run(i, audit.audit_log, 유저, *args)


@admin_command("머니추가", "유저에게 돈 추가")
async def a_money_add(i: discord.Interaction, 유저: discord.Member, 금액: app_commands.Range[int, 1]):
    await run(i, economy.moneyadd, 유저, 금액)


@admin_command("머니제거", "유저 돈 빼기 (모자라면 미납금)")
async def a_money_del(i: discord.Interaction, 유저: discord.Member, 금액: app_commands.Range[int, 1]):
    await run(i, economy.moneydel, 유저, 금액)


@admin_command("토큰추가", "유저에게 토큰 추가")
async def a_token_add(i: discord.Interaction, 유저: discord.Member, 개수: app_commands.Range[int, 1]):
    await run(i, tokens.add_token, 유저, 개수)


@admin_command("토큰제거", "유저 토큰 빼기")
async def a_token_del(i: discord.Interaction, 유저: discord.Member, 개수: app_commands.Range[int, 1]):
    await run(i, tokens.remove_token, 유저, 개수)


@admin_command("토큰구매가", "유저의 토큰 구매 가격 정하기 (기본 100)")
async def a_token_price(i: discord.Interaction, 유저: discord.Member, 가격: app_commands.Range[int, 1] = 100):
    await run(i, tokens.set_token_price, 유저, 가격)


@admin_command("강화제작", "원하는 레벨의 아이템 만들기 (테스트용)")
async def a_craft(i: discord.Interaction, 아이템: str, 레벨: app_commands.Range[int, 1, 13], 유저: discord.Member = None):
    await run(i, enhance.admin_craft, 아이템, 레벨, 유저)


@admin_command("강화수정", "아이템 레벨 바꾸기 (테스트용)")
async def a_set_level(i: discord.Interaction, 아이템: str, 레벨: app_commands.Range[int, 1, 13], 유저: discord.Member = None):
    await run(i, enhance.admin_set_enhance, 아이템, 레벨, 유저)


@admin_command("경고", "경고 주기 (누적되면 타임아웃 · 이용제한 · 차단)")
async def a_warn(i: discord.Interaction, 유저: discord.Member, 개수: app_commands.Range[int, 1] = 1, 사유: str = None):
    await run(i, moderation.warn, 유저.mention, 개수, reason=사유)


@admin_command("청소", "메시지 지우기 (14일 지난 것은 못 지움)")
async def a_clean(i: discord.Interaction, 개수: app_commands.Range[int, 1, 100]):
    await i.response.defer(ephemeral=True, thinking=True)
    deleted = await i.channel.purge(limit=개수)        # %청소 는 명령어 메시지까지 지우지만 / 는 없다
    await i.followup.send(f"🧹 {len(deleted)}개 지웠어요.", ephemeral=True)


@admin_command("초기화", "모든 게임 데이터 초기화 (확인 버튼)")
async def a_reset(i: discord.Interaction):
    await run(i, admin.reset_all_data)


@admin_command("상점관리", "역할 상점 관리 패널")
async def a_shop(i: discord.Interaction):
    await run(i, roleshop.role_shop_admin)


@admin_command("학사설정", "학사정보 (학교 · 아침 알림) 설정 패널")
async def a_school(i: discord.Interaction):
    await run(i, school.school_settings)


@admin_command("뉴스채널", "주식 뉴스를 올릴 채널")
async def a_news_channel(i: discord.Interaction, 채널: discord.TextChannel):
    await run(i, news.set_news_channel, 채널.id)


@admin_command("뉴스발행", "지금 바로 주식 뉴스 내기")
async def a_news_publish(i: discord.Interaction):
    await run(i, news.publish_news)


@admin_command("퀴즈채널", "선착순 퀴즈를 올릴 채널")
async def a_quiz_channel(i: discord.Interaction, 채널: discord.TextChannel):
    await run(i, quiz.set_quiz_channel, 채널.id)


@admin_command("퀴즈출제", "지금 바로 퀴즈 내기")
@app_commands.choices(
    과목=[app_commands.Choice(name=s, value=s) for s in quiz.SUBJECTS],
    난이도=[app_commands.Choice(name=lv, value=lv) for lv in quiz.LEVELS],
)
async def a_quiz(i: discord.Interaction, 과목: str = None, 난이도: str = None):
    await run(i, quiz.publish_quiz, *[a for a in (과목, 난이도) if a])


@admin_command("주식가속", "시간이 지난 것처럼 주가 진행 (테스트용)")
async def a_stock_accel(i: discord.Interaction, 분: app_commands.Range[int, 1, 1440] = 60):
    await run(i, stocks.accelerate_stocks, 분)


@admin_command("주식초기화", "주식 가격 초기화")
async def a_stock_reset(i: discord.Interaction):
    await run(i, stocks.reset_stock)


@admin_command("코인가속", "시간이 지난 것처럼 코인 진행 (테스트용)")
async def a_coin_accel(i: discord.Interaction, 분: app_commands.Range[int, 1, 1440] = 60):
    await run(i, crypto.coin_accelerate, 분)


@admin_command("채굴가속", "블록 바로 캐기 (테스트용)")
async def a_mining_accel(i: discord.Interaction, 블록: app_commands.Range[int, 1, 168] = 1):
    await run(i, mining.mining_accelerate, 블록)


# ───────────── 등록 ─────────────

def commands_hash():
    payload = [c.to_dict(tree) for c in tree.get_commands()]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def sync():
    """setup_hook 에서 부른다. 명령어 목록이 바뀌었을 때만 디스코드에 등록한다. (등록은 하루 횟수 제한이 있다)"""
    digest = commands_hash()
    if await db.get_state(SYNC_KEY) == digest:
        return 0
    synced = await tree.sync()
    await db.set_state(SYNC_KEY, digest)
    print(f"[슬래시] 명령어 {len(synced)}개 등록")
    return len(synced)
