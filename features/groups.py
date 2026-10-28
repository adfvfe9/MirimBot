"""% 명령어 묶음: 상위 명령어 아래에 하위 명령어를 단다. (/명령어는 slash.py 에 같은 모양으로 있다)

    %주식 구매 JAVA 10       %주식 롱 JAVA 5만 5       %머니 송금 @철수 1000       %관리 머니추가 @철수 5000

- 기능 파일은 하위 명령어를 @commands.command(name="구매") 로 만들기만 하고, 어느 상위 명령어에 달지는 여기 TREE 에서 정한다.
- 상위 명령어만 치면 첫 번째 하위 명령어를 한다: %주식 = %주식 시세, %머니 @철수 = %머니 확인 @철수, %도박 5만 = %도박 걸기 5만
  첫 번째가 None 이면 하위 명령어 목록을 보여준다. (%학교, %관리)
- 은행 · 미션은 하위 명령어가 하나뿐이라 그대로 %은행 · %미션. 장난 명령어와 봇 주인 전용(%연장 등)도 그대로.
- 예전 이름(%주식구매, %포지션, %도박올인 …)도 된다. main.py 의 on_message 가 new_form() 으로 새 모양으로 바꿔서 읽는다.
  도움말 · 노션 · 사용법 안내에는 새 모양만 보여준다.
"""
import re

import discord
from discord.ext import commands

from bot import client
from features import (
    abilities, admin, assets, audit, crypto, digest, economy, enhance, errors, futures, gamble, games, general,
    health, market, mining, moderation, music, news, orders, quiz, roleshop, school, stocks, suggestions, titles,
    tokens, tts, wordchain,
)


async def show_menu(ctx):
    """하위 명령어 없이 치면: 하위 명령어 목록"""
    group = ctx.command
    lines = [f"`{errors.usage_line(sub, sub.qualified_name)}`" for sub in errors.subcommands(group)]
    embed = discord.Embed(title=f"%{group.name} · /{group.name}", description="\n".join(lines), color=discord.Color.blurple())
    await ctx.send(embed=embed)


# (상위 이름, [하위 명령어 …]). 첫 번째가 None 이면 상위 명령어만 칠 때 목록을 보여준다.
TREE = [
    ("머니", [economy.money, economy.send, economy.money_rank, economy.welfare, economy.consolation, economy.파산]),
    ("자산", [assets.assets, assets.asset_rank, assets.asset_chart]),
    ("주식", [stocks.stock, stocks.buy_stock, stocks.sell_stock, stocks.sell_all_stock, stocks.stock_status,
              stocks.stock_chart, stocks.stock_rank, news.news, orders.order_buy, orders.order_sell, orders.order_list,
              futures.open_long, futures.open_short, futures.positions, futures.close_position]),
    ("강화", [enhance.enhance, enhance.enhance_list, enhance.sell_enhance, enhance.enhance_odds, enhance.enhance_rank,
              abilities.my_abilities, abilities.ability_panel, abilities.reroll_command, market.black_market]),
    ("토큰", [tokens.check_token, tokens.buy_token]),
    ("코인", [crypto.coin, crypto.coin_buy, crypto.coin_sell, crypto.coin_status, crypto.coin_chart, crypto.coin_rank]),
    ("채굴", [mining.mining_status, mining.mining_buy, mining.mining_upgrade, mining.mining_on, mining.mining_off,
              mining.mining_rank]),
    ("도박", [gamble.gamble, gamble.gamble_rank, gamble.rps]),
    ("끝말잇기", [wordchain.wordchain, wordchain.wordchain_rank]),
    ("게임", [games.game_record, games.game_register, games.game_unregister, games.game_bet, games.game_bet_list]),
    ("칭호", [titles.titles_command, titles.title_equip, titles.title_unequip, titles.title_rank]),
    ("역할", [roleshop.role_shop, roleshop.my_shop_roles]),
    ("학교", [None, school.school_meal, school.school_timetable, school.my_class, school.school_schedule]),
    ("음악", [music.music_play, music.music_skip, music.music_pause, music.music_resume, music.music_stop,
              music.music_queue, music.music_now, music.music_volume, tts.voice_leave.copy()]),
    ("읽기", [tts.tts_start, tts.voice_leave, tts.tts_abbrev_list, tts.tts_abbrev_set, tts.tts_abbrev_delete]),
    ("봇", [general.명령어, general.patchnote, general.timeget, health.health_ping, suggestions.suggestion,
            moderation.check_warning]),
    ("관리", [None, audit.audit_log, economy.moneyadd, economy.moneydel, tokens.add_token, tokens.remove_token,
              tokens.set_token_price, enhance.admin_craft, enhance.admin_set_enhance, moderation.warn, general.clean,
              admin.reset_all_data, roleshop.role_shop_admin, school.school_settings, news.set_news_channel,
              digest.digest_channel, digest.digest_preview, news.publish_news, quiz.set_quiz_channel,
              quiz.publish_quiz, stocks.accelerate_stocks, stocks.reset_stock, crypto.coin_accelerate,
              mining.mining_accelerate]),
]

for name, subs in TREE:
    default = subs[0]
    group = commands.Group(default.callback if default else show_menu, name=name, invoke_without_command=True,
                           usage=default.usage if default else None)
    for sub in subs:
        if sub is not None:
            group.add_command(sub)
    if name == "관리":
        group = commands.has_permissions(administrator=True)(group)   # %관리 목록도 관리자만
    client.add_command(group)


# ───────────── 예전 이름 ─────────────
# 예전 이름 → 새 모양. {} 가 있으면 그 자리에 뒤에 친 말이 들어간다. (%주식올인 JAVA → %주식 구매 JAVA 올인)
OLD_NAMES = {
    "머니확인": "머니 확인", "송금": "머니 송금", "머니랭킹": "머니 랭킹", "기초수급": "머니 기초수급",
    "위로금": "머니 위로금", "파산": "머니 파산",
    "자산랭킹": "자산 랭킹", "순자산랭킹": "자산 랭킹", "자산그래프": "자산 그래프",
    "주식구매": "주식 구매", "주식판매": "주식 판매", "주식올인": "주식 구매 {} 올인", "주식전량구매": "주식 구매 {} 올인",
    "주식절반구매": "주식 구매 {} 절반", "주식전량판매": "주식 전량판매", "주식확인": "주식 확인", "주가그래프": "주식 그래프",
    "주식랭킹": "주식 랭킹", "뉴스": "주식 뉴스", "예약구매": "주식 예약구매", "예약판매": "주식 예약판매",
    "예약목록": "주식 예약목록", "롱": "주식 롱", "숏": "주식 숏", "포지션": "주식 포지션", "청산": "주식 청산",
    "강화목록": "강화 목록", "강화판매": "강화 판매", "강화확률": "강화 확률", "강화랭킹": "강화 랭킹",
    "내능력": "강화 능력", "강화능력설정": "강화 능력설정", "강화능력": "강화 능력설정", "리롤": "강화 리롤",
    "암시장": "강화 암시장",
    "토큰확인": "토큰 확인", "토큰구매": "토큰 구매", "토큰교환": "토큰 구매", "토큰최대교환": "토큰 구매 최대",
    "비트코인": "코인", "코인구매": "코인 구매", "코인판매": "코인 판매", "코인확인": "코인 확인",
    "코인그래프": "코인 그래프", "코인랭킹": "코인 랭킹",
    "채굴기구매": "채굴 구매", "채굴기업그레이드": "채굴 업그레이드", "채굴기강화": "채굴 업그레이드",
    "채굴켜기": "채굴 켜기", "채굴끄기": "채굴 끄기", "채굴랭킹": "채굴 랭킹",
    "도박올인": "도박 걸기 올인", "도박랭킹": "도박 랭킹", "가위바위보": "도박 가위바위보",
    "가위바위보게임": "도박 가위바위보", "ㄱㅇㅂㅇㅂ": "도박 가위바위보", "짱깨뽀": "도박 가위바위보",
    "끝말": "끝말잇기", "끝말잇기랭킹": "끝말잇기 랭킹", "끝말랭킹": "끝말잇기 랭킹",
    "롤등록": "게임 등록 롤 {}", "발로등록": "게임 등록 발로 {}", "발로란트등록": "게임 등록 발로 {}",
    "게임등록해제": "게임 해제", "전적": "게임 전적", "최근전적": "게임 전적", "베팅": "게임 베팅",
    "베팅목록": "게임 베팅목록",
    "칭호장착": "칭호 장착", "칭호해제": "칭호 해제", "칭호랭킹": "칭호 랭킹",
    "역할상점": "역할 상점", "상점": "역할 상점", "내역할": "역할 목록",
    "급식": "학교 급식", "시간표": "학교 시간표", "내반": "학교 내반", "학사일정": "학교 학사일정",
    "재생": "음악 재생", "play": "음악 재생", "p": "음악 재생", "스킵": "음악 스킵", "skip": "음악 스킵",
    "일시정지": "음악 일시정지", "pause": "음악 일시정지", "다시재생": "음악 다시재생", "resume": "음악 다시재생",
    "정지": "음악 정지", "stop": "음악 정지", "대기열": "음악 대기열", "queue": "음악 대기열", "q": "음악 대기열",
    "지금곡": "음악 지금곡", "np": "음악 지금곡", "볼륨": "음악 볼륨", "volume": "음악 볼륨",
    "읽어": "읽기 시작", "tts": "읽기 시작", "나가": "읽기 나가기", "나가기": "읽기 나가기", "leave": "읽기 나가기",
    "줄임말": "읽기 줄임말", "줄임말목록": "읽기 줄임말", "줄임말설정": "읽기 줄임말설정",
    "도움말": "봇 도움말", "가이드": "봇 도움말", "명령어": "봇 도움말", "help": "봇 도움말", "패치노트": "봇 패치노트",
    "시간": "봇 시간", "핑": "봇 핑", "ping": "봇 핑", "건의": "봇 건의", "경고확인": "봇 경고확인",
    **{old: f"관리 {old}" for old in (
        "로그", "머니추가", "머니제거", "토큰추가", "토큰제거", "토큰구매가", "강화제작", "강화수정", "경고", "청소",
        "초기화", "상점관리", "학사설정", "뉴스채널", "소식채널", "소식미리보기", "뉴스발행", "퀴즈채널", "퀴즈출제",
        "주식가속", "주식초기화", "코인가속", "채굴가속")},
}

_COMMAND = re.compile(r"(\S+)(\s.*)?", re.DOTALL)


def new_form(content: str) -> str:
    """'%주식구매 JAVA 10' → '%주식 구매 JAVA 10'. 예전 이름이 아니면 그대로 돌려준다."""
    prefix = client.command_prefix
    if not content.startswith(prefix):
        return content
    match = _COMMAND.fullmatch(content[len(prefix):])
    if match is None or match[1] not in OLD_NAMES:
        return content
    new, rest = OLD_NAMES[match[1]], (match[2] or "").strip()
    if "{}" in new:
        return prefix + new.replace("{}", rest).replace("  ", " ").strip()
    return f"{prefix}{new} {rest}".rstrip()
