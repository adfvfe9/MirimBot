"""주식: 시장 상태, 1분 시세 갱신, 구매/판매, 주식확인, 그래프, 주식랭킹"""
import asyncio
import datetime
import io
import os
import random

import discord
import matplotlib.pyplot as plt
from discord import ButtonStyle, File
from discord.ext import commands, tasks
from discord.ui import Button, View
from matplotlib import font_manager

import database as db
from bot import client
from fmt import num

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
# 상승장(BULL) ↔ 하락장(BEAR)이 5~120분마다 바뀐다.
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
                await set_override_state("CRASH", 20 * 60)
                return "CRASH"
            elif override_state == "CRASH":
                override_state = None
                override_end = None
                await save_market_state()
                return "BULL"
    return current_market

# 임시 시장 상태 설정 (초상승장, 주식부도)
async def set_override_state(state, duration_seconds):
    global override_state, override_end
    override_state = state
    override_end = db.now() + datetime.timedelta(seconds=duration_seconds)
    await save_market_state()

# ───────────── 주식 기본 정보 ─────────────
SELL_FEE = 0.02   # 주식 판매 수수료 2% (모든 판매 명령어 공통)

stock_info = {
    "JAVA":   {"base": 500,  "limit": 0.08},
    "C":      {"base": 300,  "limit": 0.06},
    "C++":    {"base": 800,  "limit": 0.10},
    "C#":     {"base": 1200, "limit": 0.09},
    "PYTHON": {"base": 100,  "limit": 0.15},
    "HTML":   {"base": 400,  "limit": 0.05},
    "JS":     {"base": 2000, "limit": 0.02},
    "TS":     {"base": 1000, "limit": 0.12},
    "RUST":   {"base": 200,  "limit": 0.25},
    "RUBY":   {"base": 1500, "limit": 0.04}
}

# 현재 주가는 1분마다 자주 읽으므로 메모리에 들고 있고, 바뀔 때마다 DB 에 저장한다.
stock_prices = {}
last_update_time = datetime.datetime.now(datetime.timezone.utc)

# 시장 전환 루프
async def market_cycle():
    global current_market, market_ends_at
    await client.wait_until_ready()

    while True:
        remaining = (market_ends_at - db.now()).total_seconds()
        print(f"[📢 시장 전환 대기] {max(0, int(remaining)) // 60}분 후 상태 변경 예정")

        # 저장된 종료 시각까지 대기
        if remaining > 0:
            await asyncio.sleep(remaining)

        # 상태 전환
        current_market = "BEAR" if current_market == "BULL" else "BULL"
        market_ends_at = db.now() + random_market_duration()
        await save_market_state()
        print(f"[🔁 시장 상태 변경됨] 현재 시장: {'📈 상승장' if current_market == 'BULL' else '📉 하락장'}")

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
async def update_stocks():
    global last_update_time

    effective_state = await get_effective_market_state()  # ✅ 현재 실질 시장 상태

    for name, info in stock_info.items():
        base = info["base"]
        limit = info["limit"]
        prev_price = stock_prices[name]["current"]

        # 기본 변동
        change = random.uniform(-limit, limit)

        # 과한 변동 억제
        bias = (base - prev_price) / base * 0.05
        change += bias

        new_price = prev_price + base * change

        # ✅ 상승장 / 하락장 / 초상승장 / 주식부도 효과 (곱연산)
        # 상승장/하락장은 1분에 평균 ±0.2% → 가격이 기준가의 약 1.04배 / 0.96배 근처에서 놀게 된다.
        if effective_state == "BULL":
            new_price *= (1 + random.uniform(-0.004, 0.008))   # 평균 +0.2%
        elif effective_state == "BEAR":
            new_price *= (1 - random.uniform(-0.004, 0.008))   # 평균 -0.2%
        elif effective_state == "HYPER_BULL":
            new_price *= (1 + random.uniform(-0.02, 0.1))  # -2~10%
        elif effective_state == "CRASH":
            new_price *= (1 - random.uniform(-0.015, 0.15))    # 1.5~-15%

        # 상장폐지 처리: 모든 유저의 해당 주식 삭제 + 다음 %주식확인 때 알림
        if new_price <= 0:
            new_price = base
            print(f"[📉 상장폐지] {name} → 기본가로 초기화됨")
            await db.delist_stock(name)
            # 레버리지 포지션은 가격 0 으로 정산 (롱은 증거금을 잃고, 숏은 크게 번다)
            await futures().settle_symbol(name, exit_price=0, reason="상장폐지")

        stock_prices[name]["previous"] = prev_price
        stock_prices[name]["current"] = round(new_price, 2)

    last_update_time = datetime.datetime.now(datetime.timezone.utc)

    # 현재가 저장 + 가격 기록 추가 (종목당 최근 1440개 = 24시간만 보관)
    await db.save_stock_tick(stock_prices, keep=1440)

    # 새 가격으로 레버리지 포지션 강제청산 검사
    await futures().check_liquidations()


def futures():
    # features/futures.py 가 이 파일을 import 하므로, 서로 물고 물리지 않게 쓸 때 가져온다.
    from features import futures as module
    return module

# ───────────── 자동 1분 갱신 루프 ─────────────
@tasks.loop(minutes=1)
async def auto_update_stocks():
    try:
        await update_stocks()
    except Exception as e:
        print(f"[주식 갱신 오류] {type(e).__name__}: {e}")

@auto_update_stocks.before_loop
async def before_loop():
    await client.wait_until_ready()

# ───────────── %주식 명령어 ─────────────
@client.command(aliases=["주식"])
async def stock(ctx):
    await ctx.message.delete()

    next_update = last_update_time + datetime.timedelta(seconds=60)
    timestamp = int(next_update.timestamp())

    embed = discord.Embed(
        title="📈 실시간 주식 시세",
        description="1분마다 자동 갱신됩니다.",
        color=discord.Color.green()
    )
    state = await get_effective_market_state()
    state_text = {
        "BULL": "📈 상승장",
        "BEAR": "📉 하락장",
        "HYPER_BULL": "🚀 초상승장",
        "CRASH": "💥 주식부도"
    }.get(state, "❓ 알 수 없음")

    embed.add_field(
        name="📊 현재 시장 상태",
        value=state_text,
        inline=False
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

        embed.add_field(
            name=name,
            value=f"💵 {num(current)} byte\n({diff_str})",
            inline=True
        )
    embed.add_field(
        name="⏱️ 다음 갱신",
        value=f"<t:{timestamp}:R>",  # ✅ 여기에 쓰면 디스코드가 해석함
        inline=False
    )

    await ctx.send(embed=embed)


@client.command(aliases=["주식초기화"])
@commands.has_permissions(administrator=True)
async def reset_stock(ctx):
    await ctx.message.delete()
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
async def buy_shares(user_id, stock_key, amount, price, total_cost):
    """돈을 내고 주식을 산다. 잔액이 부족하면 None, 성공하면 남은 잔액."""
    async with db.user_tx(user_id) as conn:
        balance = await db.get_money(user_id, conn)
        if balance < total_cost:
            return None

        holdings = await db.get_portfolio(user_id, conn)
        stock = holdings.get(stock_key, {"quantity": 0, "avg_price": price})

        # 새 평균 단가 계산
        total_quantity = stock["quantity"] + amount
        total_spent = stock["quantity"] * stock["avg_price"] + total_cost

        await db.set_holding(user_id, stock_key, total_quantity, total_spent / total_quantity, conn)
        return await db.add_money(user_id, -total_cost, conn)


async def sell_shares(user_id, sales, earned):
    """sales = {종목: 팔 수량}. 보유 수량이 부족하면 None, 성공하면 남은 잔액."""
    async with db.user_tx(user_id) as conn:
        holdings = await db.get_portfolio(user_id, conn)
        for name, quantity in sales.items():
            if holdings.get(name, {}).get("quantity", 0) < quantity:
                return None

        for name, quantity in sales.items():
            stock = holdings[name]
            await db.set_holding(user_id, name, stock["quantity"] - quantity, stock["avg_price"], conn)
        return await db.add_money(user_id, earned, conn)

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
@client.command(aliases=["주식구매"])
async def buy_stock(ctx, stock_name: str, amount: int):
    await ctx.message.delete()
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
    embed.add_field(name="총 가격", value=f"{num(total_cost)} byte", inline=False)

    view = View()

    async def confirm_callback(interaction: discord.Interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("이 버튼은 당신의 것이 아니에요!", ephemeral=True)
            return

        if await buy_shares(user_id, stock_key, amount, price, total_cost) is None:
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="❌ 구매 실패",
                    description="잔액이 부족합니다.",
                    color=discord.Color.red()
                ),
                view=None
            )
            return

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="✅ 구매 완료",
                description=f"{stock_key} {amount}주 구매 완료!",
                color=discord.Color.green()
            ),
            view=None
        )

    async def cancel_callback(interaction: discord.Interaction):
        await interaction.response.edit_message(
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
@client.command(aliases=["주식판매"])
async def sell_stock(ctx, stock_name: str, amount: int):
    await ctx.message.delete()
    user_id = ctx.author.id
    stock_key = stock_aliases.get(stock_name.upper())

    if not stock_key or stock_key not in stock_prices:
        await ctx.send("❌ 존재하지 않는 주식입니다.")
        return
    if amount <= 0:
        await ctx.send("❌ 1 이상의 수량을 입력해주세요.")
        return
    stock = (await db.get_portfolio(user_id)).get(stock_key)

    # 주식이 아예 없을 경우
    if stock is None:
        await ctx.send("❌ 보유 중인 해당 주식이 없습니다.")
        return

    quantity = stock["quantity"]

    if quantity < amount:
        await ctx.send("❌ 보유 수량이 부족합니다.")
        return


    price = stock_prices[stock_key]["current"]
    total_earned = price * amount * (1 - SELL_FEE)  # 판매 수수료 2%

    embed = discord.Embed(
        title="📤 주식 판매 확인",
        description=f"{ctx.author.mention}님, 아래 거래를 확인해주세요.",
        color=discord.Color.orange()
    )
    embed.add_field(name="종목", value=stock_key, inline=True)
    embed.add_field(name="수량", value=f"{amount} 주", inline=True)
    embed.add_field(name=f"수수료 {num(SELL_FEE * 100)}% 차감 후", value=f"{num(total_earned)} byte", inline=False)

    view = View()

    async def confirm_callback(interaction: discord.Interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("이 버튼은 당신의 것이 아니에요!", ephemeral=True)
            return

        if await sell_shares(user_id, {stock_key: amount}, total_earned) is None:
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="❌ 판매 실패",
                    description="보유 수량이 부족합니다.",
                    color=discord.Color.red()
                ),
                view=None
            )
            return

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="✅ 판매 완료",
                description=f"{stock_key} {amount}주 판매 완료!",
                color=discord.Color.green()
            ),
            view=None
        )

    async def cancel_callback(interaction: discord.Interaction):
        await interaction.response.edit_message(
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
    await ctx.message.delete()
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
    await ctx.message.delete()
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
    embed.add_field(name="총 가격", value=f"{num(total_cost)} byte", inline=False)

    view = View()

    async def confirm_callback(interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("이 버튼은 당신의 것이 아닙니다.", ephemeral=True)
            return

        if await buy_shares(user_id, stock_key, max_amount, price, total_cost) is None:
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="❌ 구매 실패",
                    description="잔액이 부족합니다.",
                    color=discord.Color.red()
                ),
                view=None
            )
            return

        result = discord.Embed(
            title="✅ 전량 구매 완료",
            description=f"{stock_key} {max_amount}주를 구매했습니다.",
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=result, view=None)

    async def cancel_callback(interaction):
        await interaction.response.edit_message(
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
    await ctx.message.delete()
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

    view = View()

    async def confirm_callback(interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message(
                "이 버튼은 당신의 것이 아닙니다.",
                ephemeral=True
            )
            return

        # 확인 버튼을 누르기 전 잔액 및 주가가 변경되었는지 검사
        current_price = stock_prices[stock_key]["current"]
        new_balance = None

        if current_price == price:
            new_balance = await buy_shares(user_id, stock_key, buy_amount, price, total_cost)

        if new_balance is None:
            await interaction.response.edit_message(
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
            value=f"{num(total_cost)} byte",
            inline=True
        )
        result.add_field(
            name="남은 잔액",
            value=f"{num(new_balance)} byte",
            inline=True
        )

        await interaction.response.edit_message(embed=result, view=None)

    async def cancel_callback(interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message(
                "이 버튼은 당신의 것이 아닙니다.",
                ephemeral=True
            )
            return

        await interaction.response.edit_message(
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
    await ctx.message.delete()
    user_id = ctx.author.id
    holdings = await db.get_portfolio(user_id)

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
        net = gross * (1 - SELL_FEE)  # 판매 수수료 2%

        embed = discord.Embed(
            title="📤 전량 판매 확인",
            description=f"{ctx.author.mention}, **{stock_key}** {quantity}주를 판매하시겠습니까?",
            color=discord.Color.orange()
        )
        embed.add_field(name="1주 가격", value=f"{num(price)} byte", inline=True)
        embed.add_field(name="수익 (수수료 적용)", value=f"{num(net)} byte", inline=False)

        view = View()

        async def confirm_callback(interaction):
            if interaction.user != ctx.author:
                await interaction.response.send_message("이 버튼은 당신의 것이 아닙니다.", ephemeral=True)
                return

            if await sell_shares(user_id, {stock_key: quantity}, net) is None:
                await interaction.response.edit_message(
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
                description=f"{stock_key} {quantity}주를 판매했습니다.",
                color=discord.Color.green()
            )
            await interaction.response.edit_message(embed=result, view=None)

        async def cancel_callback(interaction):
            await interaction.response.edit_message(
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
        net = gross * (1 - SELL_FEE)

        is_loss = net < cost  # ✅ 손해 여부 판단

        if is_loss:
            summary_lines.append(f"⚠️ {name}: {q}주 → {num(net)} byte (손해!)")
        else:
            summary_lines.append(f"{name}: {q}주 → {num(net)} byte")

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

    view = View()

    async def confirm_callback(interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("이 버튼은 당신의 것이 아닙니다.", ephemeral=True)
            return

        sales = {name: stock["quantity"] for name, stock in user_stocks.items()}
        if await sell_shares(user_id, sales, total_net) is None:
            await interaction.response.edit_message(
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
            description=f"{num(total_net)} byte를 획득했습니다.",
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=result, view=None)

    async def cancel_callback(interaction):
        await interaction.response.edit_message(
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

@client.command(aliases=["주가그래프"])
async def stock_chart(ctx, stock_name: str = None):
    await ctx.message.delete()
    price_history = await db.load_price_history()
    if not price_history:
        await ctx.send("❌ 아직 기록된 가격 데이터가 없습니다.")
        return

    if stock_name:
        stock_key = stock_aliases.get(stock_name.upper())
        if not stock_key or stock_key not in price_history:
            await ctx.send("❌ 해당 주식의 가격 데이터가 없습니다.")
            return

        prices = price_history[stock_key]
        plt.figure(figsize=(10, 4))
        plt.plot(prices, label=stock_key)
        plt.title(f"{stock_key} 24시간 주가")
        plt.xlabel("시간 (1분 단위)")
        plt.ylabel("가격")
        plt.grid(True)
        plt.legend()

        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        plt.close()

        await ctx.send(file=File(buf, filename=f"{stock_key}_chart.png"))
    else:
        plt.figure(figsize=(12, 6))
        for name, prices in price_history.items():
            plt.plot(prices, label=name)

        plt.title("모든 주식 24시간 주가")
        plt.xlabel("시간 (1분 단위)")
        plt.ylabel("가격")
        plt.legend()
        plt.grid(True)

        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        plt.close()

        await ctx.send(file=File(buf, filename="all_stock_chart.png"))

    # 링크 임베드 추가
    link_embed = discord.Embed(
        title="📊 실시간 주식 그래프 웹사이트",
        description="[👉 그래프 웹에서 보기](https://mirimbot.netlify.app/)",
        color=discord.Color.blue()
    )
    link_embed.set_footer(text="웹사이트는 실시간 가격 데이터를 반영합니다.")
    await ctx.send(embed=link_embed)


@client.command(aliases=["주식랭킹"])
async def stock_rank(ctx):
    await ctx.message.delete()

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
