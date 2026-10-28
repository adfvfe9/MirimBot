"""주식: 시장 상태, 1분 시세 갱신, 구매/판매, 주식확인, 그래프, 주식랭킹"""
import asyncio
import datetime
import functools
import io
import math
import os
import random

import discord
import matplotlib

matplotlib.use("Agg")   # 화면 없이 그림만 그린다 (그래프 전용 스레드에서 그려도 되게)
import matplotlib.pyplot as plt  # noqa: E402
from discord import ButtonStyle, File
from discord.ext import commands, tasks
from concurrent.futures import ThreadPoolExecutor
from discord.ui import Button
from matplotlib import font_manager

import database as db
import respond
from bot import client
from features import abilities
from fmt import ALL, HALF, Amount, num, resolve_amount

# 그래프에 한글이 나오도록 맑은 고딕 폰트 등록 (malgun.ttf 는 프로젝트 폴더에 있다)
font_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'malgun.ttf'
)

font_manager.fontManager.addfont(font_path)
plt.rcParams['font.family'] = font_manager.FontProperties(
    fname=font_path
).get_name()
plt.rcParams['axes.unicode_minus'] = False


# ───────────── 주식 시장 상태 ─────────────
# 상승장(BULL) ↔ 하락장(BEAR)이 5~120분마다 바뀐다. (효과 크기는 아래 '가격 공식'의 TREND)
# 초상승장(HYPER_BULL) / 주식부도(CRASH) 는 잠깐 덮어쓰는 이벤트 상태다.
current_market = "BULL"
market_ends_at = None      # 지금 상태(BULL/BEAR)가 끝나는 시각
override_state = None
override_end = None


def random_market_duration():
    return datetime.timedelta(seconds=random.randint(300, 7200))  # 5~120분


async def load_market_state():
    global current_market, market_ends_at, override_state, override_end
    data = await db.load_market_state()
    if data:
        current_market = data["state"]
        market_ends_at = data["state_ends_at"]
        override_state = data["override_state"]
        override_end = data["override_end"]
    else:
        current_market = "BULL"
        market_ends_at = db.now() + random_market_duration()
        override_state = None
        override_end = None
        await save_market_state()


async def save_market_state():
    await db.save_market_state(current_market, market_ends_at, override_state, override_end)


# 현재 시장 상태를 가져오는 함수
async def get_effective_market_state():
    global override_state, override_end
    if override_state and override_end:
        if db.now() < override_end:
            return override_state
        else:
            if override_state == "HYPER_BULL":
                # 거품 붕괴: 모든 종목이 한 번에 떨어지고 주식부도 20분이 이어진다
                await set_override_state("CRASH", 20 * 60)
                await jump_all(-random.uniform(*CRASH_JUMP))
                return "CRASH"
            elif override_state == "CRASH":
                override_state = None
                override_end = None
                await save_market_state()
    return current_market

# 임시 시장 상태 설정 (초상승장, 주식부도)
async def set_override_state(state, duration_seconds):
    global override_state, override_end
    override_state = state
    override_end = db.now() + datetime.timedelta(seconds=duration_seconds)
    await save_market_state()

# ───────────── 주식 기본 정보 ─────────────
SELL_FEE = 0.02   # 주식 판매 수수료 2% (모든 판매 명령어 공통)
QUICK_SELL_FEE = 0.08     # 단타 수수료: 마지막으로 산 지 QUICK_SELL_MINUTES 분 안에 팔면 8%
QUICK_SELL_MINUTES = 30

# base: 기준가 (아주 천천히 이쪽으로 돌아온다), vol: 하루 변동성 (평소 흔들림이 하루에 대략 이만큼)
# (v1.3: 너무 잔잔하다는 의견이 많아서 4배로 올렸다. 1분 평균 변동 JS 약 0.18% ~ RUST 약 1.3%)
stock_info = {
    "JAVA":   {"base": 500,  "vol": 0.192},
    "C":      {"base": 300,  "vol": 0.144},
    "C++":    {"base": 800,  "vol": 0.240},
    "C#":     {"base": 1200, "vol": 0.216},
    "PYTHON": {"base": 100,  "vol": 0.360},
    "HTML":   {"base": 400,  "vol": 0.120},
    "JS":     {"base": 2000, "vol": 0.072},
    "TS":     {"base": 1000, "vol": 0.288},
    "RUST":   {"base": 200,  "vol": 0.600},
    "RUBY":   {"base": 1500, "vol": 0.096}
}

# ───────────── 가격 공식 ─────────────
# 1분마다: 새 가격 = 지금 가격 × e^(변화율). 변화율은 아래를 더한 것 (전부 현재가 대비 비율)
#   평소 흔들림 (정규분포, 종목 vol 기준) + 아주 약한 되돌림 + 기본 성장 + 시장 상태 + 뉴스 후속 움직임
# 큰 움직임은 뉴스가 나오는 순간 한 번에 튀는 점프로 온다. (features/news.py)
# 예전처럼 기준가로 빠르게 돌아오면 "멀리 벗어난 종목 반대로 사기"로 누구나 벌 수 있어서, 되돌림은 반감기 14일로 아주 약하게 했다.
# 값은 시뮬레이션으로 정했다: 되돌림 매매 · 추세 추종 · 뉴스 따라가기 · 아무렇게나 레버리지 모두 기대 손익이 0 이하,
# 그냥 들고 있으면 하루 약 +1%. (부도 위기 / 거품 붕괴로 빠지는 만큼을 기본 성장이 메운다)
MINUTES_PER_DAY = 1440
REVERT_PER_MINUTE = math.log(2) / (14 * MINUTES_PER_DAY)   # 되돌림 반감기 14일
GROWTH_PER_MINUTE = 0.015 / MINUTES_PER_DAY                # 기본 성장 하루 1.5%
TREND = 0.10              # 상승장 / 하락장: 분당 평소 흔들림의 10% 만큼 오르거나 내린다
STATE_DRIFT = {"HYPER_BULL": 0.004, "CRASH": -0.0005}      # 초상승장 분당 +0.4%, 주식부도 분당 -0.05%
CRASH_JUMP = (0.02, 0.06)  # 거품이 꺼지는 순간 모든 종목이 2~6% 떨어진다
DELIST_FLOOR = 0.02        # 기준가의 2% 밑으로 떨어지면 상장폐지


def minute_sigma(name):
    """종목의 1분 평소 흔들림 크기 (하루 변동성 / √1440)"""
    return stock_info[name]["vol"] / math.sqrt(MINUTES_PER_DAY)

# 현재 주가는 1분마다 자주 읽으므로 메모리에 들고 있고, 바뀔 때마다 DB 에 저장한다.
stock_prices = {}
last_update_time = datetime.datetime.now(datetime.timezone.utc)

async def switch_market():
    """상승장 ↔ 하락장 전환"""
    global current_market, market_ends_at
    current_market = "BEAR" if current_market == "BULL" else "BULL"
    market_ends_at = db.now() + random_market_duration()
    await save_market_state()
    print(f"[🔁 시장 상태 변경됨] 현재 시장: {'📈 상승장' if current_market == 'BULL' else '📉 하락장'}")


async def pass_market_minute():
    """%주식가속용: 시장 상태 타이머를 1분 앞당긴다. (1분이 지난 것처럼) 상승장/하락장이 바뀌었으면 True.
    초상승장/주식부도가 끝나는 처리는 get_effective_market_state 가 한다."""
    global market_ends_at, override_end
    one_minute = datetime.timedelta(minutes=1)
    market_ends_at -= one_minute
    if override_end:
        override_end -= one_minute
    if market_ends_at <= db.now():
        await switch_market()
        return True
    return False


# 시장 전환 루프
async def market_cycle():
    await client.wait_until_ready()
    print(f"[📢 시장 전환 대기] {max(0, int((market_ends_at - db.now()).total_seconds())) // 60}분 후 상태 변경 예정")

    while True:
        # 종료 시각이 될 때까지 기다린다. %주식가속이 종료 시각을 당길 수 있어서 1분마다 다시 확인한다.
        remaining = (market_ends_at - db.now()).total_seconds()
        if remaining > 0:
            await asyncio.sleep(min(remaining, 60))
            continue
        await switch_market()

# ───────────── 저장/로드 함수 ─────────────
async def load_stock_prices():
    global stock_prices, last_update_time
    stock_prices = await db.load_stock_prices()

    # 🛠️ 누락된 주식 보정 (예: 처음 실행, 새 종목 추가)
    missing = {
        name: {"current": data["base"], "previous": data["base"]}
        for name, data in stock_info.items()
        if name not in stock_prices
    }
    if missing:
        stock_prices.update(missing)
        await db.save_stock_prices(missing)

    last_update_time = datetime.datetime.now(datetime.timezone.utc)

# ───────────── 주식 가격 갱신 ─────────────
# 1분 자동 갱신과 %주식가속이 동시에 가격을 바꾸지 않게 막는 잠금
update_lock = asyncio.Lock()


async def update_stocks(history=None, positions=None):
    """가격을 1분만큼 갱신한다. {"delisted": 상장폐지된 종목들, "liquidated": 강제청산 개수}
    %주식가속은 매분 DB 를 다녀오면 느리므로 두 가지를 넘긴다.
      history:   리스트를 주면 가격을 DB 에 저장하지 않고 [(종목, 가격), ...] 으로 여기에 쌓는다. (끝나고 한 번에 저장)
      positions: 레버리지 포지션 목록을 주면 DB 에서 다시 읽지 않고 이걸로 강제청산을 검사한다."""
    global last_update_time
    delisted = []

    effective_state = await get_effective_market_state()  # ✅ 현재 실질 시장 상태

    doomed = []  # 이번 분에 상장폐지될 종목
    for name, info in stock_info.items():
        base = info["base"]
        prev_price = stock_prices[name]["current"]
        sigma = minute_sigma(name)

        # 평소 흔들림. -σ²/2 는 흔들림이 클수록 평균 가격이 저절로 오르는 효과를 지운다
        # (안 지우면 변동이 큰 종목은 그냥 들고만 있어도 평균적으로 돈이 불어난다)
        change = random.gauss(-sigma * sigma / 2, sigma)
        change -= REVERT_PER_MINUTE * math.log(prev_price / base)  # 아주 약한 되돌림 (반감기 14일)
        change += GROWTH_PER_MINUTE                              # 기본 성장
        change += news().current_drift(name)                     # 📰 뉴스 후속 움직임 (features/news.py)

        # 상승장 / 하락장 / 초상승장 / 주식부도
        if effective_state == "BULL":
            change += TREND * sigma
        elif effective_state == "BEAR":
            change -= TREND * sigma
        else:
            change += STATE_DRIFT.get(effective_state, 0)

        new_price = prev_price * math.exp(change)
        if new_price < base * DELIST_FLOOR:
            doomed.append(name)

        stock_prices[name]["previous"] = prev_price
        stock_prices[name]["current"] = max(round(new_price, 2), 0.01)

    # 뉴스 효과 1분 경과. 상장폐지로 끝나는 부도 위기 종목을 받아온다.
    doomed += news().tick_effects()
    for name in dict.fromkeys(doomed):
        await delist(name)
        delisted.append(name)

    last_update_time = datetime.datetime.now(datetime.timezone.utc)

    # 현재가 저장 + 가격 기록 추가 (종목당 최근 1440개 = 24시간만 보관)
    if history is None:
        await db.save_stock_tick(stock_prices, keep=1440)
    else:
        history.extend((name, data["current"]) for name, data in stock_prices.items())

    # 새 가격으로 레버리지 포지션 강제청산 검사
    liquidated = await futures().check_liquidations(positions)
    return {"delisted": delisted, "liquidated": liquidated}


async def delist(name):
    """상장폐지: 기준가로 되돌리고, 모든 유저의 해당 주식을 지우고(다음 %주식확인 때 알림), 레버리지는 가격 0 으로 정산."""
    stock_prices[name]["current"] = float(stock_info[name]["base"])
    print(f"[📉 상장폐지] {name} → 기본가로 초기화됨")
    await db.delist_stock(name)
    # 롱은 증거금을 잃고, 숏은 크게 번다
    await futures().settle_symbol(name, exit_price=0, reason="상장폐지")


async def jump(name, size):
    """뉴스로 가격이 한 번에 튄다. size 는 변화율 (0.1 이면 약 +10.5%, -0.1 이면 약 -9.5%).
    %주식에서 얼마나 튀었는지 보이게 previous 를 튀기 전 가격으로 둔다."""
    data = stock_prices[name]
    data["previous"] = data["current"]
    data["current"] = max(round(data["current"] * math.exp(size), 2), 0.01)
    await db.save_stock_prices(stock_prices)


async def jump_all(size):
    """시장 전체 뉴스 / 거품 붕괴: 모든 종목이 같이 튄다."""
    for name in stock_prices:
        data = stock_prices[name]
        data["previous"] = data["current"]
        data["current"] = max(round(data["current"] * math.exp(size), 2), 0.01)
    await db.save_stock_prices(stock_prices)


# features/futures.py, features/news.py 가 이 파일을 import 하므로, 서로 물고 물리지 않게 쓸 때 가져온다.
def futures():
    from features import futures as module
    return module


def crypto():
    from features import crypto as module
    return module


def orders():
    from features import orders as module
    return module


def mining():
    from features import mining as module
    return module


def news():
    from features import news as module
    return module

# ───────────── 자동 1분 갱신 루프 ─────────────
@tasks.loop(minutes=1)
async def auto_update_stocks():
    try:
        async with update_lock:
            await update_stocks()
    except Exception as e:
        print(f"[주식 갱신 오류] {type(e).__name__}: {e}")
    # ₿ 비트코인도 같은 1분 루프에서 갱신 (가속은 %코인가속 으로 따로)
    try:
        async with crypto().lock:
            await crypto().tick()
    except Exception as e:
        print(f"[코인 갱신 오류] {type(e).__name__}: {e}")
    # 🤖 주식 예약 매매 (방금 바뀐 가격으로)
    try:
        await orders().check()
    except Exception as e:
        print(f"[예약 매매 오류] {type(e).__name__}: {e}")
    # ⛏️ 채굴 블록 (1시간마다)
    try:
        async with crypto().lock:
            await mining().maybe_block()
    except Exception as e:
        print(f"[채굴 오류] {type(e).__name__}: {e}")
    # 💼 순자산 기록 + 칭호 확인 (1시간마다)
    try:
        from features import assets
        await assets.maybe_snapshot()
    except Exception as e:
        print(f"[자산 기록 오류] {type(e).__name__}: {e}")

@auto_update_stocks.before_loop
async def before_loop():
    await client.wait_until_ready()


# ───────────── %주식가속 (관리자, 테스트용) ─────────────
ACCEL_MAX_MINUTES = 1440   # 가격 기록이 종목당 1440개(24시간)까지라 그 이상은 의미가 없다
ACCEL_PROGRESS_SECONDS = 2  # 진행 상황 메시지를 고치는 간격 (너무 자주 고치면 디스코드가 막는다)


def accel_progress(done, minutes, elapsed):
    """가속 진행 상황 한 줄. 예) ⏩ 주식 가속 중 ▓▓▓▓░░░░░░ 40% (48/120분) · 12초 지남"""
    filled = done * 10 // minutes
    bar = "▓" * filled + "░" * (10 - filled)
    return f"⏩ 주식 가속 중 {bar} {done * 100 // minutes}% ({done}/{minutes}분) · {int(elapsed)}초 지남"


@client.command(aliases=["주식가속"])
@commands.has_permissions(administrator=True)
async def accelerate_stocks(ctx, minutes: int = 60):
    """minutes 분이 지난 것처럼 1분 처리를 minutes 번 바로 돌린다.
    매분: 시장 상태 타이머(상승장/하락장, 초상승장/주식부도) 1분 당기기 → 뉴스 타이머 → 가격 갱신.
    상장폐지, 강제청산도 실제로 처리된다. 단타 수수료(30분)는 실제 시각 그대로다.
    가속 중에 나온 뉴스는 DB 에 저장되고(%뉴스) 효과도 걸리지만, 뉴스 채널에 도배되지 않게 채널에는 올리지 않는다."""
    respond.delete_soon(ctx.message)
    if not 1 <= minutes <= ACCEL_MAX_MINUTES:
        await ctx.send(f"❌ 1~{ACCEL_MAX_MINUTES}분 사이로 입력해주세요.")
        return
    if update_lock.locked():
        await ctx.send("⏳ 지금 주식 가격을 갱신하는 중이에요. 잠시 뒤 다시 시도해주세요.")
        return

    before = {name: data["current"] for name, data in stock_prices.items()}
    message = await ctx.send(accel_progress(0, minutes, 0))
    delisted = []
    liquidated = 0
    switches = 0
    headlines = []
    done = 0
    clock = asyncio.get_running_loop().time
    started = last_shown = clock()
    # 매분 DB 를 다녀오면 1분에 1초 가까이 걸려서, 가격 기록은 모았다가 끝나고 한 번에 저장하고
    # 포지션은 한 번 읽어 둔 목록으로 강제청산을 검사한다. (60분마다, 상장폐지 뒤에는 다시 읽는다)
    history = []
    positions = await db.all_positions()
    # 레버리지 보유 비용도 가속: 포지션 진입 시각을 1분씩 당긴다. (메모리 목록은 매분, DB 는 다시 읽을 때 모아서)
    shifted = 0
    one_minute = datetime.timedelta(minutes=1)

    async with update_lock:
        try:
            for done in range(1, minutes + 1):
                for pos in positions:
                    if pos.get("opened_at"):
                        pos["opened_at"] -= one_minute
                switches += await pass_market_minute()
                if news().minute_passed():
                    _, _, headline, _ = await news().make_news()
                    headlines.append(f"`{done}분` {headline}")
                result = await update_stocks(history=history, positions=positions)
                delisted += result["delisted"]
                liquidated += result["liquidated"]
                if result["delisted"] or done % 60 == 0:
                    await db.shift_position_times(done - shifted)
                    shifted = done
                    positions = await db.all_positions()  # 상장폐지 정산, 그사이 새로 연 포지션 반영
                if done < minutes and clock() - last_shown >= ACCEL_PROGRESS_SECONDS:
                    last_shown = clock()
                    await message.edit(content=accel_progress(done, minutes, last_shown - started))
                await asyncio.sleep(0)  # 오래 걸려도 봇이 멈춘 것처럼 되지 않게 다른 일에 차례를 준다
        except Exception as e:
            print(f"[주식가속 오류] {type(e).__name__}: {e}")
            await message.edit(content=f"❌ {done}/{minutes}분째에 오류가 나서 멈췄어요: {type(e).__name__}")
            return
        finally:
            await db.shift_position_times(done - shifted)  # 남은 만큼 보유 시간 반영
            if history:
                await db.save_stock_tick(stock_prices, keep=1440, history=history)  # 모아 둔 가격 기록 저장
            await save_market_state()  # 당긴 타이머 저장

    embed = discord.Embed(
        title=f"⏩ 주식 {minutes}분 가속 완료",
        description=(
            f"**{minutes}분**({num(minutes / 60)}시간)이 지난 것처럼 처리했어요. (실제로 걸린 시간 {int(clock() - started)}초)\n"
            "새 가격은 `%주식`, 흐름은 `%주가그래프`로 확인하세요."
        ),
        color=discord.Color.blue()
    )
    for name, price in stock_prices.items():
        old = before.get(name, price["current"])
        change = (price["current"] / old - 1) * 100 if old else 0
        embed.add_field(
            name=name,
            value=f"{num(old)} → {num(price['current'])}\n({num(change, sign=True)}%)",
            inline=True
        )
    if delisted:
        counts = {name: delisted.count(name) for name in dict.fromkeys(delisted)}
        embed.add_field(
            name="📉 상장폐지",
            value=", ".join(f"{name} {n}번" for name, n in counts.items()),
            inline=False
        )
    embed.add_field(name="💥 강제청산", value=f"{liquidated}건", inline=False)
    # 지금이 상승장인지 하락장인지는 일부러 숨기고, 몇 번 바뀌었는지만 보여준다.
    embed.add_field(name="🔁 시장 분위기 전환", value=f"{switches}번", inline=False)
    if headlines:
        shown = headlines[-10:]
        more = f"\n... 외 {len(headlines) - len(shown)}개" if len(headlines) > len(shown) else ""
        embed.add_field(name=f"📰 가속 중 나온 뉴스 ({len(headlines)}개)", value="\n".join(shown)[:1000] + more, inline=False)
    else:
        embed.add_field(name="📰 가속 중 나온 뉴스", value="없음", inline=False)
    embed.set_footer(text=f"요청자: {ctx.author.display_name} · 가속 중 뉴스는 뉴스 채널에 올리지 않아요 (%뉴스로 확인)")
    await message.edit(content=None, embed=embed)

# ───────────── %주식 명령어 ─────────────
@client.command(aliases=["주식"])
async def stock(ctx):
    respond.delete_soon(ctx.message)

    next_update = last_update_time + datetime.timedelta(seconds=60)
    timestamp = int(next_update.timestamp())

    # 시장 상태(상승장/하락장)는 일부러 보여주지 않는다. (보이면 롱/숏이 너무 쉬워짐)
    # 대신 진행 중인 시장 뉴스가 있으면 알려준다.
    description = "1분마다 자동 갱신됩니다. 시장 분위기는 뉴스와 그래프로 추측해보세요!"
    market_news = news().market_badge()
    if market_news:
        description += f"\n{market_news}"

    embed = discord.Embed(
        title="📈 실시간 주식 시세",
        description=description,
        color=discord.Color.green()
    )

    for name, price_data in stock_prices.items():
        current = price_data["current"]
        previous = price_data["previous"]
        diff = current - previous
        percent = (current / previous) * 100 - 100 if previous != 0 else 0

        diff_str = (
            f"▲ {num(abs(diff))} byte (+{num(percent)}%)" if diff > 0 else
            f"▼ {num(abs(diff))} byte ({num(percent)}%)" if diff < 0 else
            "― 변동 없음"
        )

        badge = news().badge(name)  # 📰 진행 중인 뉴스: 🔥 호재 / 🧊 악재 / 💥 부도 위기
        embed.add_field(
            name=f"{name} {badge}".strip(),
            value=f"💵 {num(current)} byte\n({diff_str})",
            inline=True
        )
    embed.add_field(
        name="⏱️ 다음 갱신",
        value=f"<t:{timestamp}:R>",  # ✅ 여기에 쓰면 디스코드가 해석함
        inline=False
    )
    embed.set_footer(text="📰 뉴스 진행 중: 🔥 호재 · 🧊 악재 · ❓ 루머 · 💥 부도 위기  (%뉴스)")

    await ctx.send(embed=embed)


@client.command(aliases=["주식초기화"])
@commands.has_permissions(administrator=True)
async def reset_stock(ctx):
    respond.delete_soon(ctx.message)
    global stock_prices, last_update_time

    # 주식 초기화
    stock_prices = {
        name: {"current": info["base"], "previous": info["base"]}
        for name, info in stock_info.items()
    }
    await db.save_stock_prices(stock_prices)
    await db.clear_price_history()
    last_update_time = datetime.datetime.now(datetime.timezone.utc)

    embed = discord.Embed(
        title="🔄 주식 초기화 완료",
        description="모든 주식이 기본가로 초기화되었습니다.",
        color=discord.Color.orange()
    )
    embed.set_footer(text=f"요청자: {ctx.author.display_name}")
    await ctx.send(embed=embed)

# ───────────── 주식 거래 공통 처리 ─────────────
# 확인 창을 띄운 뒤 가격이 바뀔 수 있으므로, 실제 거래는 확인 버튼을 누른 순간의 현재가로 한다.
# (창을 띄운 시점 가격으로 하면, 가격이 유리하게 바뀌었을 때만 확인을 눌러 공짜로 벌 수 있다)

# 아래 함수들의 bonus 는 abilities.totals 결과 (⏱️ 단타 시간 단축, 💸 판매 수수료 할인)

def quick_minutes(bonus=None):
    """단타 수수료가 붙는 시간 (분)"""
    return QUICK_SELL_MINUTES - (bonus or {}).get("quick_sell_time", 0)


def is_quick(stock, bonus=None):
    """보유 주식(db.get_portfolio 의 값 하나)이 아직 단타 수수료 시간 안인지"""
    bought = stock.get("last_bought_at")
    return bool(bought) and db.now() - bought < datetime.timedelta(minutes=quick_minutes(bonus))


def sell_fee(stock, bonus=None):
    """지금 팔 때의 수수료율. 단타 시간 안이면 단타 수수료, 판매 수수료 할인 능력만큼 낮아진다."""
    fee = QUICK_SELL_FEE if is_quick(stock, bonus) else SELL_FEE
    return max(0.0, fee - (bonus or {}).get("sell_fee", 0) / 100)


def quick_sell_left(stock, bonus=None):
    """단타 수수료가 끝나기까지 남은 분 (올림). 이미 끝났으면 0."""
    bought = stock.get("last_bought_at")
    if not bought:
        return 0
    left = datetime.timedelta(minutes=quick_minutes(bonus)) - (db.now() - bought)
    return max(0, -(-int(left.total_seconds()) // 60))


async def buy_shares(user_id, stock_key, amount):
    """현재가로 주식을 산다. 잔액이 부족하면 None, 성공하면 {"price", "cost", "balance"}."""
    async with db.user_tx(user_id) as conn:
        price = stock_prices[stock_key]["current"]
        total_cost = round(price * amount, 2)
        balance = await db.get_money(user_id, conn)
        if balance < total_cost:
            return None

        holdings = await db.get_portfolio(user_id, conn)
        stock = holdings.get(stock_key, {"quantity": 0, "avg_price": price})

        # 새 평균 단가 계산
        total_quantity = stock["quantity"] + amount
        total_spent = stock["quantity"] * stock["avg_price"] + total_cost

        await db.set_holding(
            user_id, stock_key, total_quantity, total_spent / total_quantity, conn, bought_at=db.now()
        )
        balance = await db.add_money(user_id, -total_cost, conn)
        await db.log_money(user_id, "stock_buy", -total_cost, f"{stock_key} {amount}주 @{price}", conn)
    return {"price": price, "cost": total_cost, "balance": balance}


async def sell_shares(user_id, sales):
    """sales = {종목: 팔 수량}. 현재가로 판다.
    보유 수량이 부족하면 None, 성공하면 {"earned": 받은 돈, "fees": {종목: 수수료율}, "balance": 잔액}."""
    async with db.user_tx(user_id) as conn:
        holdings = await db.get_portfolio(user_id, conn)
        for name, quantity in sales.items():
            if holdings.get(name, {}).get("quantity", 0) < quantity:
                return None

        earned = 0.0
        fees = {}
        bonus = await abilities.totals(user_id, conn)
        for name, quantity in sales.items():
            stock = holdings[name]
            price = stock_prices[name]["current"]
            fees[name] = sell_fee(stock, bonus)
            net = price * quantity * (1 - fees[name])
            earned += net
            await db.set_holding(user_id, name, stock["quantity"] - quantity, stock["avg_price"], conn)
            await db.log_money(
                user_id, "stock_sell", net, f"{name} {quantity}주 @{price} 수수료 {fees[name]:.2%}", conn
            )
        balance = await db.add_money(user_id, earned, conn)
    return {"earned": earned, "fees": fees, "balance": balance}


def fee_text(stock, bonus=None):
    """확인 창에 보여줄 수수료 설명"""
    fee = sell_fee(stock, bonus)
    if is_quick(stock, bonus):
        return f"단타 수수료 {num(fee * 100)}% (산 지 {quick_minutes(bonus)}분 안, {quick_sell_left(stock, bonus)}분 남음)"
    return f"수수료 {num(fee * 100)}%"

# ───────────── 주식 이름 줄임말 처리 ─────────────
stock_aliases = {
    "J": "JAVA", "JAVA": "JAVA",
    "C": "C",
    "+": "C++", "C++": "C++",
    "#": "C#", "C#": "C#",
    "P": "PYTHON", "PYTHON": "PYTHON",
    "H": "HTML", "HTML": "HTML",
    "JS": "JS",
    "TS": "TS",
    "RUST": "RUST", "RS" : "RUST",
    "RUBY": "RUBY", "RB": "RUBY"
}

# ───────────── %주식구매 ─────────────
@client.command(aliases=["주식구매"], usage="<종목> <수량 | 올인 | 절반>")
async def buy_stock(ctx, stock_name: str, amount: Amount):
    if amount == ALL:
        return await buy_all_stock(ctx, stock_name)
    if amount == HALF:
        return await buy_half_stock(ctx, stock_name)
    respond.delete_soon(ctx.message)
    user_id = ctx.author.id
    stock_key = stock_aliases.get(stock_name.upper())

    if not stock_key or stock_key not in stock_prices:
        await ctx.send("❌ 존재하지 않는 주식입니다.")
        return
    if amount <= 0:
        await ctx.send("❌ 1 이상의 수량을 입력해주세요.")
        return

    price = stock_prices[stock_key]["current"]
    total_cost = round(price * amount, 2)

    if await db.get_money(user_id) < total_cost:
        await ctx.send("❌ 잔액이 부족합니다.")
        return

    embed = discord.Embed(
        title="📥 주식 구매 확인",
        description=f"{ctx.author.mention}님, 아래 거래를 확인해주세요.",
        color=discord.Color.blue()
    )
    embed.add_field(name="종목", value=stock_key, inline=True)
    embed.add_field(name="수량", value=f"{amount} 주", inline=True)
    embed.add_field(name="총 가격 (지금 가격 기준)", value=f"{num(total_cost)} byte", inline=False)
    embed.set_footer(
        text=f"확인을 누르는 순간의 가격으로 거래돼요. 산 뒤 {QUICK_SELL_MINUTES}분 안에 팔면 단타 수수료 "
             f"{num(QUICK_SELL_FEE * 100)}%가 붙어요."
    )

    view = respond.ConfirmView(ctx.author)

    async def confirm_callback(interaction: discord.Interaction):
        await respond.defer(interaction)

        bought = await buy_shares(user_id, stock_key, amount)
        if bought is None:
            await respond.edit(interaction,
                embed=discord.Embed(
                    title="❌ 구매 실패",
                    description="잔액이 부족합니다.",
                    color=discord.Color.red()
                ),
                view=None
            )
            return

        await respond.edit(interaction,
            embed=discord.Embed(
                title="✅ 구매 완료",
                description=(
                    f"{stock_key} {amount}주 구매 완료!\n"
                    f"1주 {num(bought['price'])} byte, 총 {num(bought['cost'])} byte"
                ),
                color=discord.Color.green()
            ),
            view=None
        )

    async def cancel_callback(interaction: discord.Interaction):
        await respond.defer(interaction)
        await respond.edit(interaction,
            embed=discord.Embed(
                title="❌ 구매 취소",
                description="거래가 취소되었습니다.",
                color=discord.Color.red()
            ),
            view=None
        )

    yes = Button(label="확인", style=discord.ButtonStyle.green)
    no = Button(label="취소", style=discord.ButtonStyle.red)
    yes.callback = confirm_callback
    no.callback = cancel_callback
    view.add_item(yes)
    view.add_item(no)

    await ctx.send(embed=embed, view=view)

# ───────────── %주식판매 ─────────────
@client.command(aliases=["주식판매"], usage="<종목> <수량 | 전부 | 절반>")
async def sell_stock(ctx, stock_name: str, amount: Amount):
    if amount == ALL:
        return await sell_all_stock(ctx, stock_name)
    respond.delete_soon(ctx.message)
    user_id = ctx.author.id
    stock_key = stock_aliases.get(stock_name.upper())

    if not stock_key or stock_key not in stock_prices:
        await ctx.send("❌ 존재하지 않는 주식입니다.")
        return
    stock = (await db.get_portfolio(user_id)).get(stock_key)

    # 주식이 아예 없을 경우
    if stock is None:
        await ctx.send("❌ 보유 중인 해당 주식이 없습니다.")
        return

    quantity = stock["quantity"]
    amount = resolve_amount(amount, quantity)   # 절반: 가진 수량의 절반
    if amount <= 0:
        await ctx.send("❌ 1 이상의 수량을 입력해주세요.")
        return

    if quantity < amount:
        await ctx.send("❌ 보유 수량이 부족합니다.")
        return


    price = stock_prices[stock_key]["current"]
    bonus = await abilities.totals(user_id)
    total_earned = price * amount * (1 - sell_fee(stock, bonus))

    embed = discord.Embed(
        title="📤 주식 판매 확인",
        description=f"{ctx.author.mention}님, 아래 거래를 확인해주세요.",
        color=discord.Color.orange()
    )
    embed.add_field(name="종목", value=stock_key, inline=True)
    embed.add_field(name="수량", value=f"{amount} 주", inline=True)
    embed.add_field(name=f"{fee_text(stock, bonus)} 차감 후 (지금 가격 기준)", value=f"{num(total_earned)} byte", inline=False)
    embed.set_footer(text="확인을 누르는 순간의 가격으로 거래돼요.")

    view = respond.ConfirmView(ctx.author)

    async def confirm_callback(interaction: discord.Interaction):
        await respond.defer(interaction)

        sold = await sell_shares(user_id, {stock_key: amount})
        if sold is None:
            await respond.edit(interaction,
                embed=discord.Embed(
                    title="❌ 판매 실패",
                    description="보유 수량이 부족합니다.",
                    color=discord.Color.red()
                ),
                view=None
            )
            return

        await respond.edit(interaction,
            embed=discord.Embed(
                title="✅ 판매 완료",
                description=(
                    f"{stock_key} {amount}주 판매 완료!\n"
                    f"받은 돈 {num(sold['earned'])} byte (수수료 {num(sold['fees'][stock_key] * 100)}%)"
                ),
                color=discord.Color.green()
            ),
            view=None
        )

    async def cancel_callback(interaction: discord.Interaction):
        await respond.defer(interaction)
        await respond.edit(interaction,
            embed=discord.Embed(
                title="❌ 판매 취소",
                description="거래가 취소되었습니다.",
                color=discord.Color.red()
            ),
            view=None
        )

    yes = Button(label="확인", style=discord.ButtonStyle.green)
    no = Button(label="취소", style=discord.ButtonStyle.red)
    yes.callback = confirm_callback
    no.callback = cancel_callback
    view.add_item(yes)
    view.add_item(no)

    await ctx.send(embed=embed, view=view)

@client.command(aliases=["주식확인"])
async def stock_status(ctx, member: discord.Member = None):
    respond.delete_soon(ctx.message)
    member = member or ctx.author
    user_id = member.id

    # ✅ 알림 먼저 띄우기 (상장폐지, 강제청산 등)
    if member == ctx.author:
        notices = await db.pop_notices(user_id)
        if notices:
            await ctx.send("\n".join(notices))

    holdings = await db.get_portfolio(user_id)
    if not holdings:
        await ctx.send(f"{member.display_name}님은 보유 중인 주식이 없습니다.")
        return

    embed = discord.Embed(
        title=f"📊 {member.display_name}님의 주식 상태",
        description="보유 수량 및 현재 평가 금액",
        color=discord.Color.purple()
    )

    total_value = 0.0
    total_cost = 0.0

    for name, stock in holdings.items():
        quantity = stock.get("quantity", 0)
        avg_price = stock.get("avg_price", stock_info.get(name, {}).get("base", 0))
        current_price = stock_prices.get(name, {}).get("current", avg_price)
        value = round(current_price * quantity, 2)
        cost = round(avg_price * quantity, 2)

        total_value += value
        total_cost += cost

        # 손익률 계산
        profit_rate = ((current_price - avg_price) / avg_price * 100) if avg_price > 0 else 0
        profit_str = f"{num(profit_rate, sign=True)}%"

        embed.add_field(
            name=name,
            value=(
                f"보유량: **{quantity}주**\n"
                f"총 매입가: **{num(avg_price * quantity)} byte**\n"
                f"평가액: **{num(value)} byte**\n"
                f"손익률: **{profit_str}**"
            ),
            inline=False
        )

    if total_cost > 0:
        profit_amount = round(total_value - total_cost, 2)
        total_profit_rate = (profit_amount / total_cost) * 100
        profit_str = f"{num(total_profit_rate, sign=True)}%"
        profit_amount_str = f"{num(profit_amount, sign=True)} byte"
    else:
        profit_str = "N/A"
        profit_amount_str = "N/A"

    embed.add_field(name="📈 총 이익금", value=f"**{profit_amount_str}**", inline=False)
    embed.add_field(name="📊 총 손익률", value=f"**{profit_str}**", inline=False)
    embed.set_footer(text=f"요청자: {ctx.author.display_name}")

    await ctx.send(embed=embed)

@client.command(aliases=["주식올인", "주식전량구매"])
async def buy_all_stock(ctx, stock_name: str):
    respond.delete_soon(ctx.message)
    user_id = ctx.author.id
    stock_key = stock_aliases.get(stock_name.upper())

    if not stock_key or stock_key not in stock_prices:
        await ctx.send("❌ 존재하지 않는 주식입니다.")
        return

    price = stock_prices[stock_key]["current"]
    balance = await db.get_money(user_id)
    max_amount = int(balance // price)

    if max_amount <= 0:
        await ctx.send("❌ 잔액이 부족합니다.")
        return

    total_cost = round(price * max_amount, 2)

    embed = discord.Embed(
        title="📥 주식 전량 구매 확인",
        description=f"{ctx.author.mention}, **{stock_key}**를 최대 수량만큼 구매하시겠습니까?",
        color=discord.Color.blue()
    )
    embed.add_field(name="구매 수량", value=f"{max_amount} 주", inline=True)
    embed.add_field(name="1주 가격", value=f"{num(price)} byte", inline=True)
    embed.add_field(name="총 가격 (지금 가격 기준)", value=f"{num(total_cost)} byte", inline=False)
    embed.set_footer(
        text=f"확인을 누르는 순간의 가격으로 거래돼요. 산 뒤 {QUICK_SELL_MINUTES}분 안에 팔면 단타 수수료 "
             f"{num(QUICK_SELL_FEE * 100)}%가 붙어요."
    )

    view = respond.ConfirmView(ctx.author)

    async def confirm_callback(interaction):
        await respond.defer(interaction)

        bought = await buy_shares(user_id, stock_key, max_amount)
        if bought is None:
            await respond.edit(interaction,
                embed=discord.Embed(
                    title="❌ 구매 실패",
                    description="잔액이 부족합니다. (그사이 가격이 올랐을 수 있어요. 명령어를 다시 실행해주세요)",
                    color=discord.Color.red()
                ),
                view=None
            )
            return

        result = discord.Embed(
            title="✅ 전량 구매 완료",
            description=(
                f"{stock_key} {max_amount}주를 구매했습니다.\n"
                f"1주 {num(bought['price'])} byte, 총 {num(bought['cost'])} byte"
            ),
            color=discord.Color.green()
        )
        await respond.edit(interaction, embed=result, view=None)

    async def cancel_callback(interaction):
        await respond.defer(interaction)
        await respond.edit(interaction,
            embed=discord.Embed(
                title="❌ 거래 취소됨",
                description="구매가 취소되었습니다.",
                color=discord.Color.red()
            ),
            view=None
        )

    yes = Button(label="확인", style=ButtonStyle.green)
    no = Button(label="취소", style=ButtonStyle.red)
    yes.callback = confirm_callback
    no.callback = cancel_callback
    view.add_item(yes)
    view.add_item(no)

    await ctx.send(embed=embed, view=view)

@client.command(aliases=["주식절반구매"])
async def buy_half_stock(ctx, stock_name: str):
    respond.delete_soon(ctx.message)
    user_id = ctx.author.id
    stock_key = stock_aliases.get(stock_name.upper())

    if not stock_key or stock_key not in stock_prices:
        await ctx.send("❌ 존재하지 않는 주식입니다.")
        return

    price = stock_prices[stock_key]["current"]
    balance = await db.get_money(user_id)

    # 현재 잔액으로 구매 가능한 최대 수량의 절반
    max_amount = int(balance // price)
    buy_amount = max_amount // 2

    if buy_amount <= 0:
        await ctx.send("❌ 잔액이 부족하거나 절반 구매가 가능한 수량이 없습니다.")
        return

    total_cost = round(price * buy_amount, 2)

    embed = discord.Embed(
        title="📥 주식 절반 구매 확인",
        description=f"{ctx.author.mention}, **{stock_key}**를 구매 가능한 최대 수량의 절반만큼 구매하시겠습니까?",
        color=discord.Color.blue()
    )
    embed.add_field(name="구매 수량", value=f"{buy_amount} 주", inline=True)
    embed.add_field(name="1주 가격", value=f"{num(price)} byte", inline=True)
    embed.add_field(name="총 가격", value=f"{num(total_cost)} byte", inline=False)
    embed.add_field(
        name="구매 후 예상 잔액",
        value=f"{num(balance - total_cost)} byte",
        inline=False
    )
    embed.set_footer(
        text=f"확인 전에 주가가 바뀌면 취소돼요 (다시 실행해주세요). 산 뒤 {QUICK_SELL_MINUTES}분 안에 팔면 단타 수수료 "
             f"{num(QUICK_SELL_FEE * 100)}%가 붙어요."
    )

    view = respond.ConfirmView(ctx.author)

    async def confirm_callback(interaction):
        await respond.defer(interaction)

        # 확인 버튼을 누르기 전 주가가 바뀌었으면 다시 실행하게 한다 (예전 가격으로 사는 것 방지)
        bought = None
        if stock_prices[stock_key]["current"] == price:
            bought = await buy_shares(user_id, stock_key, buy_amount)

        if bought is None:
            await respond.edit(interaction,
                embed=discord.Embed(
                    title="❌ 구매 실패",
                    description="주가 또는 잔액이 변경되었습니다. 명령어를 다시 실행해주세요.",
                    color=discord.Color.red()
                ),
                view=None
            )
            return

        result = discord.Embed(
            title="✅ 절반 구매 완료",
            description=f"{stock_key} {buy_amount}주를 구매했습니다.",
            color=discord.Color.green()
        )
        result.add_field(
            name="사용 금액",
            value=f"{num(bought['cost'])} byte",
            inline=True
        )
        result.add_field(
            name="남은 잔액",
            value=f"{num(bought['balance'])} byte",
            inline=True
        )

        await respond.edit(interaction, embed=result, view=None)

    async def cancel_callback(interaction):
        await respond.defer(interaction)
        if interaction.user != ctx.author:
            await respond.reply(interaction,
                "이 버튼은 당신의 것이 아닙니다.",
                ephemeral=True
            )
            return

        await respond.edit(interaction,
            embed=discord.Embed(
                title="❌ 거래 취소됨",
                description="구매가 취소되었습니다.",
                color=discord.Color.red()
            ),
            view=None
        )

    yes = Button(label="확인", style=ButtonStyle.green)
    no = Button(label="취소", style=ButtonStyle.red)

    yes.callback = confirm_callback
    no.callback = cancel_callback

    view.add_item(yes)
    view.add_item(no)

    await ctx.send(embed=embed, view=view)

@client.command(aliases=["주식전량판매"])
async def sell_all_stock(ctx, stock_name: str = None):
    respond.delete_soon(ctx.message)
    user_id = ctx.author.id
    holdings = await db.get_portfolio(user_id)
    bonus = await abilities.totals(user_id)

    # 개별 주식 판매
    if stock_name:
        stock_key = stock_aliases.get(stock_name.upper())
        if not stock_key or stock_key not in stock_prices:
            await ctx.send("❌ 존재하지 않는 주식입니다.")
            return

        stock = holdings.get(stock_key)
        if not stock or stock["quantity"] <= 0:
            await ctx.send("❌ 해당 주식을 보유하고 있지 않습니다.")
            return

        quantity = stock["quantity"]
        price = stock_prices[stock_key]["current"]
        gross = price * quantity
        net = gross * (1 - sell_fee(stock, bonus))

        embed = discord.Embed(
            title="📤 전량 판매 확인",
            description=f"{ctx.author.mention}, **{stock_key}** {quantity}주를 판매하시겠습니까?",
            color=discord.Color.orange()
        )
        embed.add_field(name="1주 가격", value=f"{num(price)} byte", inline=True)
        embed.add_field(name=f"수익 ({fee_text(stock, bonus)} 적용)", value=f"{num(net)} byte", inline=False)
        embed.set_footer(text="확인을 누르는 순간의 가격으로 거래돼요.")

        view = respond.ConfirmView(ctx.author)

        async def confirm_callback(interaction):
            await respond.defer(interaction)

            sold = await sell_shares(user_id, {stock_key: quantity})
            if sold is None:
                await respond.edit(interaction,
                    embed=discord.Embed(
                        title="❌ 판매 실패",
                        description="보유 수량이 변경되었습니다. 명령어를 다시 실행해주세요.",
                        color=discord.Color.red()
                    ),
                    view=None
                )
                return

            result = discord.Embed(
                title="✅ 전량 판매 완료",
                description=(
                    f"{stock_key} {quantity}주를 판매했습니다.\n"
                    f"받은 돈 {num(sold['earned'])} byte (수수료 {num(sold['fees'][stock_key] * 100)}%)"
                ),
                color=discord.Color.green()
            )
            await respond.edit(interaction, embed=result, view=None)

        async def cancel_callback(interaction):
            await respond.defer(interaction)
            await respond.edit(interaction,
                embed=discord.Embed(
                    title="❌ 거래 취소됨",
                    description="판매가 취소되었습니다.",
                    color=discord.Color.red()
                ),
                view=None
            )

        yes = Button(label="확인", style=ButtonStyle.green)
        no = Button(label="취소", style=ButtonStyle.red)
        yes.callback = confirm_callback
        no.callback = cancel_callback
        view.add_item(yes)
        view.add_item(no)

        await ctx.send(embed=embed, view=view)
        return

    # 전체 주식 전량 판매
    user_stocks = holdings
    if not user_stocks:
        await ctx.send("❌ 보유 중인 주식이 없습니다.")
        return

    total_net = 0
    total_quantity = 0
    summary_lines = []

    for name, stock in user_stocks.items():
        q = stock["quantity"]
        avg = stock["avg_price"]
        cost = q * avg

        p = stock_prices.get(name, {}).get("current", stock_info[name]["base"])
        gross = p * q
        net = gross * (1 - sell_fee(stock, bonus))

        is_loss = net < cost  # ✅ 손해 여부 판단
        quick = " ⏱️단타" if is_quick(stock, bonus) else ""

        if is_loss:
            summary_lines.append(f"⚠️ {name}: {q}주 → {num(net)} byte (손해!){quick}")
        else:
            summary_lines.append(f"{name}: {q}주 → {num(net)} byte{quick}")

        total_quantity += q
        total_net += net

    embed = discord.Embed(
        title="📤 전체 주식 전량 판매 확인",
        description=f"{ctx.author.mention}님, 모든 보유 주식을 전량 판매하시겠습니까?",
        color=discord.Color.red()
    )
    embed.add_field(name="총 수량", value=f"{total_quantity} 주", inline=True)
    embed.add_field(name="예상 수익", value=f"{num(total_net)} byte", inline=True)
    embed.add_field(name="📋 상세 목록", value="\n".join(summary_lines), inline=False)
    embed.set_footer(
        text=f"⏱️단타: 산 지 {QUICK_SELL_MINUTES}분 안이라 수수료 {num(QUICK_SELL_FEE * 100)}% "
             f"(보통은 {num(SELL_FEE * 100)}%). 확인을 누르는 순간의 가격으로 거래돼요."
    )

    view = respond.ConfirmView(ctx.author)

    async def confirm_callback(interaction):
        await respond.defer(interaction)

        sales = {name: stock["quantity"] for name, stock in user_stocks.items()}
        sold = await sell_shares(user_id, sales)
        if sold is None:
            await respond.edit(interaction,
                embed=discord.Embed(
                    title="❌ 판매 실패",
                    description="보유 수량이 변경되었습니다. 명령어를 다시 실행해주세요.",
                    color=discord.Color.red()
                ),
                view=None
            )
            return

        result = discord.Embed(
            title="✅ 전체 주식 전량 판매 완료",
            description=f"{num(sold['earned'])} byte를 획득했습니다.",
            color=discord.Color.green()
        )
        await respond.edit(interaction, embed=result, view=None)

    async def cancel_callback(interaction):
        await respond.defer(interaction)
        await respond.edit(interaction,
            embed=discord.Embed(
                title="❌ 거래 취소됨",
                description="전체 판매가 취소되었습니다.",
                color=discord.Color.red()
            ),
            view=None
        )

    yes = Button(label="확인", style=ButtonStyle.green)
    no = Button(label="취소", style=ButtonStyle.red)
    yes.callback = confirm_callback
    no.callback = cancel_callback
    view.add_item(yes)
    view.add_item(no)

    await ctx.send(embed=embed, view=view)

CHART_FREE_MINUTES = 60      # %주가그래프 기본 (무료)
CHART_MAX_MINUTES = 1440     # 가격 기록은 종목당 24시간(1440분)까지만 남는다
CHART_HOUR_PRICE = 2000      # 60분 더 볼 때마다 내는 돈


def chart_cost(minutes):
    """기본 60분은 무료, 넘는 부분은 60분(시작 단위)마다 2000"""
    extra = max(0, minutes - CHART_FREE_MINUTES)
    return -(-extra // 60) * CHART_HOUR_PRICE


# 그래프 그리기는 오래 걸려서 (큰 그래프는 1초 넘게) 이벤트 루프에서 하면 그동안 봇 전체가 멈춘다.
# 그래서 그래프 전용 스레드 하나에서 차례로 그린다. (plt 는 여러 스레드에서 동시에 쓰면 안 돼서 하나만)
# 주가 · 코인 · 자산 그래프, 수학 퀴즈 그림이 모두 이걸 쓴다.
_plot_thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix="plot")


async def in_plot_thread(fn, *args):
    return await asyncio.get_running_loop().run_in_executor(_plot_thread, functools.partial(fn, *args))


async def warm_up_plot():
    """봇이 켜질 때 그래프를 한 번 그려 둔다. 처음 그릴 때만 글꼴 등을 불러와서 몇 배 느리다. (setup_hook)"""
    await in_plot_thread(draw_chart, {"-": [1.0, 1.0]}, 2, "")


def draw_chart(series, minutes, title):
    """series: {종목: [가격...]} → 최근 minutes 분 그래프 PNG"""
    plt.figure(figsize=(10, 4) if len(series) == 1 else (12, 6))
    for name, prices in series.items():
        prices = prices[-minutes:]
        plt.plot(range(-len(prices) + 1, 1), prices, label=name)
    plt.title(title)
    plt.xlabel("분 전")
    plt.ylabel("가격")
    plt.grid(True)
    plt.legend()
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    return buf


@client.command(aliases=["주가그래프"])
async def stock_chart(ctx, *args):
    """%주가그래프 [주식이름] [분]  — 기본 60분 무료, 60분 더 볼 때마다 2000 byte"""
    respond.delete_soon(ctx.message)
    stock_key, minutes = None, CHART_FREE_MINUTES
    for arg in args:
        if arg.isdigit():
            minutes = int(arg)
        else:
            stock_key = stock_aliases.get(arg.upper())
            if not stock_key:
                await ctx.send(f"❌ `{arg}` 은(는) 없는 주식입니다. (사용법: `%주가그래프 [주식이름] [분]`)")
                return
    if minutes < 1:
        await ctx.send("❌ 1분 이상으로 입력해주세요.")
        return
    if minutes > CHART_MAX_MINUTES:
        await ctx.send(f"❌ 최대 {CHART_MAX_MINUTES}분(24시간)까지만 볼 수 있어요.")
        return

    series = await db.load_recent_prices(minutes, stock_key)
    if stock_key and stock_key not in series:
        await ctx.send("❌ 해당 주식의 가격 데이터가 없습니다.")
        return
    if not series:
        await ctx.send("❌ 아직 기록된 가격 데이터가 없습니다.")
        return

    # 기록이 요청보다 짧으면 있는 만큼만 보여주고 그만큼만 받는다
    minutes = min(minutes, max(len(prices) for prices in series.values()))
    cost = chart_cost(minutes)
    if cost:
        async with db.user_tx(ctx.author.id) as conn:
            money = await db.get_money(ctx.author.id, conn)
            if money < cost:
                await ctx.send(f"💸 돈이 부족합니다. {minutes}분 그래프는 {num(cost)} byte예요. (보유: {num(money)} byte)")
                return
            await db.update_user(ctx.author.id, conn, money=money - cost)
            await db.log_money(ctx.author.id, "chart", -cost, f"{minutes}분", conn)

    title = f"{stock_key or '모든 주식'} 최근 {minutes}분 주가"
    buf = await in_plot_thread(draw_chart, series, minutes, title)
    filename = f"{stock_key or 'all_stock'}_chart.png".replace("#", "sharp").replace("+", "plus")
    paid = f" · {num(cost)} byte 지불" if cost else ""
    await ctx.send(content=f"📈 {title}{paid}", file=File(buf, filename=filename))


@client.command(aliases=["주식랭킹"])
async def stock_rank(ctx):
    respond.delete_soon(ctx.message)

    user_profits = []

    for user_id, stocks in (await db.all_portfolios()).items():
        total_cost = 0.0
        total_value = 0.0

        for name, data in stocks.items():
            quantity = data.get("quantity", 0)
            avg_price = data.get("avg_price", 0)
            current_price = stock_prices.get(name, {}).get("current", avg_price)

            total_cost += quantity * avg_price
            total_value += quantity * current_price

        if total_cost == 0:
            continue  # 매입 금액이 없으면 계산 불가

        profit = total_value - total_cost
        profit_rate = (profit / total_cost) * 100

        user_profits.append((user_id, round(profit, 2), round(profit_rate, 2)))

    if not user_profits:
        await ctx.send("❌ 주식을 보유한 유저가 없습니다.")
        return

    # 수익금 기준 내림차순 정렬
    user_profits.sort(key=lambda x: x[1], reverse=True)

    embed = discord.Embed(
        title="📈 주식 수익 랭킹 TOP 10",
        description="보유 주식의 총 수익금 기준 랭킹입니다.",
        color=discord.Color.teal()
    )

    for i, (user_id, profit, rate) in enumerate(user_profits[:10], start=1):
        member = ctx.guild.get_member(user_id)
        name = member.display_name if member else f"알 수 없음 ({user_id})"
        symbol = "📈" if profit > 0 else "📉" if profit < 0 else "💸"
        embed.add_field(
            name=f"{i}위: {name}",
            value=f"{symbol} 수익금: {num(profit, sign=True)} byte\n💹 수익률: {num(rate, sign=True)}%",
            inline=False
        )

    await ctx.send(embed=embed)
