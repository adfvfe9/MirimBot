"""비트코인: 토큰으로만 사고파는 코인

    %코인                     시세, 1시간 / 24시간 변동, 최근 코인 뉴스
    %코인구매 <토큰 수>        토큰으로 코인 사기
    %코인판매 [코인 수 | 전부]  코인 팔고 토큰 받기 (안 쓰면 전부)
    %코인확인 [@유저]          보유량, 평균 단가, 손익
    %코인그래프 [분]           가격 그래프 (60분 무료, 더 보려면 byte)
    %코인랭킹                 코인 평가액 순위
    %코인가속 [분]             (관리자) 코인만 [분] 만큼 빨리 진행 (%주식가속 과 따로)

- 가격 단위는 토큰이다. 1분마다 주식과 같이 갱신된다. (stocks.auto_update_stocks 루프가 tick 을 부른다)
- 평소 흔들림 하루 약 25% + 4~8시간마다 코인 뉴스로 ±5~20% 점프. 주식보다 훨씬 거칠다.
- 그냥 들고 있으면 평균 본전이 되게 만들었다 (흔들림 보정 -σ²/2, 점프는 +x% / -x% 같은 확률).
  토큰은 리롤 재료라, 코인으로 토큰이 저절로 불어나면 리롤이 공짜가 된다.
  시뮬레이션: 그냥 보유 / 급락 뒤 사기 / 급등 뒤 사기 모두 수수료만큼 손해. (하루 최저가와 최고가 차이는 보통 1.7배)
  처음 생각한 하루 80% 는 일주일이면 보통 90% 를 잃을 만큼 거칠어서 낮췄다.
- 수수료: 살 때 1%, 팔 때 1%. 팔면 토큰은 정수만 받고, 딱 그만큼의 코인만 팔려서 남는 끝자리는 코인으로 남는다.
- 가격이 0.1 밑으로 내려가면 ×100, 1000 위로 올라가면 ÷100 액면 조정을 한다. 보유량도 반대로 바뀌어서 가치는 그대로.
- 레버리지는 일부러 없다. (손실은 막히고 이익은 끝이 없어서 구조적으로 이득이 나기 쉽다)
"""
import asyncio
import math
import random
from collections import deque

import discord
from discord.ext import commands
from discord.ui import Button, View

import database as db
import respond
from bot import client
from fmt import num

# ───────────── 밸런스 설정 ─────────────
START_PRICE = 10.0
DAILY_VOL = 0.25
SIGMA = DAILY_VOL / math.sqrt(1440)      # 1분 흔들림
NEWS_MINUTES = (240, 480)                # 코인 뉴스 간격
JUMP = (0.05, 0.20)                      # 뉴스 점프 크기 (+/- 같은 확률)
FEE = 0.01
SPLIT_LOW, SPLIT_HIGH, SPLIT_FACTOR = 0.1, 1000.0, 100
HISTORY_KEEP = 1440
CHART_FREE_MINUTES, CHART_HOUR_PRICE = 60, 2000   # %주가그래프와 같은 규칙

GOOD_NEWS = [
    "일론 머스크, 트위터에 '₿🚀' 한 줄 남겨",
    "미국, 비트코인 현물 ETF 추가 승인",
    "대형 은행, 고객 자산에 비트코인 편입 발표",
    "엘살바도르, 비트코인 채권 완판",
    "미림마이스터고 매점, 비트코인 결제 시범 도입",
    "유명 투자자 '비트코인은 디지털 금' 인터뷰",
]
BAD_NEWS = [
    "대형 거래소 해킹… 비트코인 대량 유출",
    "중국, 비트코인 채굴 전면 금지 재확인",
    "일론 머스크 '이제 비트코인 안 받는다'",
    "미국 금융당국, 코인 거래소 조사 착수",
    "'고래' 지갑에서 비트코인 대량 매도 포착",
    "코인 유튜버 '지금 다 팔아라' 영상 화제",
]

# ───────────── 상태 (메모리) ─────────────
price = START_PRICE
previous = START_PRICE
history = deque(maxlen=HISTORY_KEEP)   # 최근 가격 (가치 기준으로 액면 조정됨)
pending = []                           # 아직 DB 에 안 쓴 가격 기록 (%주식가속 중에 모아 둔다)
news_left = random.randint(*NEWS_MINUTES)
recent_news = deque(maxlen=5)          # [(시각, 헤드라인, 변화율)]
lock = asyncio.Lock()                  # 1분 갱신과 %코인가속이 겹치지 않게


async def load():
    """봇 시작 때: DB 에서 시세와 기록을 읽는다. 처음이면 시작가로."""
    global price, previous
    data = await db.load_coin()
    if data is None:
        price = previous = START_PRICE
        await db.save_coin(price, previous, [])
        return
    price, previous, rows = data
    history.clear()
    history.extend(rows)


async def rescale(factor):
    """액면 조정: 가격 ×factor, 보유량 ÷factor"""
    global price, previous
    price *= factor
    previous *= factor
    scaled = [p * factor for p in history]
    history.clear()
    history.extend(scaled)
    pending[:] = [p * factor for p in pending]
    await db.rescale_coin(factor)


async def tick(save=True):
    """1분 갱신. save=False 면 기록을 모아 두기만 한다 (%주식가속, 끝나고 flush)."""
    global price, previous, news_left
    previous = price
    price *= math.exp(random.gauss(-SIGMA * SIGMA / 2, SIGMA))

    headline = None
    news_left -= 1
    if news_left <= 0:
        news_left = random.randint(*NEWS_MINUTES)
        up = random.random() < 0.5
        size = random.uniform(*JUMP)
        price *= 1 + size if up else 1 - size
        headline = random.choice(GOOD_NEWS if up else BAD_NEWS)
        recent_news.append((db.now(), headline, size if up else -size))

    if price < SPLIT_LOW:
        await rescale(SPLIT_FACTOR)
        await announce("🔁 비트코인 액면 조정", f"가격이 너무 낮아져서 가격 ×{SPLIT_FACTOR}, 보유량 ÷{SPLIT_FACTOR} 했어요. 가치는 그대로예요.", save)
    elif price > SPLIT_HIGH:
        await rescale(1 / SPLIT_FACTOR)
        await announce("🔁 비트코인 액면 조정", f"가격이 너무 높아져서 가격 ÷{SPLIT_FACTOR}, 보유량 ×{SPLIT_FACTOR} 했어요. 가치는 그대로예요.", save)

    price = round(price, 4)
    history.append(price)
    pending.append(price)
    if headline:
        change = recent_news[-1][2]
        await announce(f"₿ [코인 속보] {headline}", f"비트코인 {num(change * 100, sign=True)}% → **{num(price)} 토큰**", save)
    if save:
        await flush()


async def flush():
    """현재가와 모아 둔 기록을 DB 에 쓴다."""
    await db.save_coin(price, previous, list(pending), HISTORY_KEEP)
    pending.clear()


async def announce(title, body, live):
    """뉴스 채널에 올린다. (%주식가속 중에는 올리지 않는다)"""
    print(f"[코인] {title} {body}")
    if not live:
        return
    embed = discord.Embed(title=title, description=body, color=discord.Color.orange())
    for channel_id in await db.get_news_channels():
        channel = client.get_channel(channel_id)
        if channel is None:
            continue
        try:
            await channel.send(embed=embed)
        except discord.HTTPException as e:
            print(f"[코인] 채널 {channel_id} 전송 실패: {e}")


def change_since(minutes):
    """minutes 분 전 대비 변화율 (기록이 모자라면 None)"""
    if len(history) <= minutes:
        return None
    old = history[-minutes - 1]
    return price / old - 1 if old else None


# ───────────── 거래 ─────────────

async def buy(user_id, tokens):
    """토큰으로 코인을 산다. 실패하면 안내(str), 성공하면 {"coins", "price", "amount"(총 보유)}"""
    if tokens < 1:
        return "❌ 1토큰 이상으로 사주세요."
    async with db.user_tx(user_id) as conn:
        if await db.add_tokens(user_id, -tokens, conn) is None:
            return "🪙 토큰이 부족합니다. (`%토큰구매`, 퀴즈, `%암시장`으로 얻을 수 있어요)"
        now_price = price
        coins = tokens * (1 - FEE) / now_price
        holding = await db.get_coin_holding(user_id, conn)
        await db.set_coin_holding(user_id, holding["amount"] + coins, holding["spent"] + tokens, conn)
    return {"coins": coins, "price": now_price, "amount": holding["amount"] + coins}


async def sell(user_id, amount=None):
    """코인을 팔고 토큰을 받는다. amount 가 None 이면 전부.
    실패하면 안내(str), 성공하면 {"coins", "tokens", "price", "left"}"""
    async with db.user_tx(user_id) as conn:
        holding = await db.get_coin_holding(user_id, conn)
        have = holding["amount"]
        if have <= 0:
            return "❌ 가진 코인이 없어요."
        coins = have if amount is None else amount
        if coins <= 0:
            return "❌ 0보다 많이 팔아야 해요."
        if coins > have + 1e-12:
            return f"❌ 가진 코인은 {have:.6f} BTC 예요."
        coins = min(coins, have)
        now_price = price
        unit = now_price * (1 - FEE)          # 코인 1개를 팔면 받는 토큰 (수수료 뺀 것)
        tokens = math.floor(coins * unit)
        if tokens < 1:
            return f"❌ 너무 적어요. 수수료를 빼고 1토큰 이상이 돼야 팔 수 있어요. (지금 {coins * unit:.2f} 토큰어치)"
        # 토큰은 정수라서, 딱 tokens 개가 되는 만큼만 팔고 남는 끝자리는 코인으로 남긴다
        sold = min(coins, tokens / unit)
        left = have - sold
        spent_left = holding["spent"] * (left / have) if have else 0
        await db.set_coin_holding(user_id, left if left > 1e-12 else 0, spent_left, conn)
        await db.add_tokens(user_id, tokens, conn)
    return {"coins": sold, "tokens": tokens, "price": now_price, "left": max(left, 0)}


# ───────────── 명령어 ─────────────

def fmt_change(change):
    if change is None:
        return "기록 부족"
    arrow = "▲" if change > 0 else "▼" if change < 0 else "―"
    return f"{arrow} {num(change * 100, sign=True)}%"


@client.command(aliases=["코인", "비트코인"])
async def coin(ctx):
    embed = discord.Embed(
        title=f"₿ 비트코인 {num(price)} 토큰",
        description="토큰으로만 사고팔아요. 주식보다 훨씬 거칠어요! (1분마다 갱신)",
        color=discord.Color.orange(),
    )
    embed.add_field(name="1분 전 대비", value=fmt_change(price / previous - 1 if previous else None), inline=True)
    embed.add_field(name="1시간", value=fmt_change(change_since(60)), inline=True)
    embed.add_field(name="24시간", value=fmt_change(change_since(1439)), inline=True)
    if recent_news:
        lines = [
            f"<t:{int(at.timestamp())}:R> {headline} ({num(change * 100, sign=True)}%)"
            for at, headline, change in reversed(recent_news)
        ]
        embed.add_field(name="📰 최근 코인 뉴스", value="\n".join(lines), inline=False)
    embed.set_footer(text=f"%코인구매 <토큰> · %코인판매 [개수|전부] · 수수료 살 때 {int(FEE * 100)}% / 팔 때 {int(FEE * 100)}%")
    await ctx.send(embed=embed)


def confirm_view(owner_id, on_confirm):
    """확인 / 취소 버튼. on_confirm(interaction) 은 확인을 누른 순간 실행된다."""
    view = View(timeout=60)

    async def yes(interaction):
        if interaction.user.id != owner_id:
            await respond.reply(interaction, "이 버튼은 당신의 것이 아니에요!", ephemeral=True)
            return
        await respond.defer(interaction)
        await on_confirm(interaction)

    async def no(interaction):
        if interaction.user.id != owner_id:
            await respond.reply(interaction, "이 버튼은 당신의 것이 아니에요!", ephemeral=True)
            return
        await respond.edit(interaction, embed=discord.Embed(description="❌ 취소했어요.", color=discord.Color.red()), view=None)

    for label, style, callback in (("확인", discord.ButtonStyle.green, yes), ("취소", discord.ButtonStyle.red, no)):
        button = Button(label=label, style=style)
        button.callback = callback
        view.add_item(button)
    return view


@client.command(aliases=["코인구매"])
async def coin_buy(ctx, tokens: int = None):
    if tokens is None or tokens < 1:
        await ctx.send("사용법: `%코인구매 <토큰 수>` 예) `%코인구매 5`")
        return
    have = (await db.get_user(ctx.author.id))["tokens"]
    if have < tokens:
        await ctx.send(f"🪙 토큰이 부족해요. (보유 {have}개)")
        return
    embed = discord.Embed(
        title="₿ 비트코인 구매 확인",
        description=(
            f"🪙 **{tokens} 토큰**으로 약 **{tokens * (1 - FEE) / price:.6f} BTC**를 사요. (지금 가격 {num(price)} 토큰, 수수료 {int(FEE * 100)}%)\n"
            "확인을 누르는 순간의 가격으로 거래돼요."
        ),
        color=discord.Color.orange(),
    )

    async def on_confirm(interaction):
        r = await buy(ctx.author.id, tokens)
        if isinstance(r, str):
            await respond.edit(interaction, embed=discord.Embed(description=r, color=discord.Color.red()), view=None)
            return
        await respond.edit(interaction, embed=discord.Embed(
            title="✅ 비트코인 구매 완료",
            description=f"{r['coins']:.6f} BTC를 {num(r['price'])} 토큰에 샀어요. 이제 **{r['amount']:.6f} BTC** 보유!",
            color=discord.Color.green(),
        ), view=None)

    await ctx.send(embed=embed, view=confirm_view(ctx.author.id, on_confirm))


@client.command(aliases=["코인판매"])
async def coin_sell(ctx, amount: str = None):
    holding = await db.get_coin_holding(ctx.author.id)
    if holding["amount"] <= 0:
        await ctx.send("❌ 가진 코인이 없어요. `%코인구매 <토큰>`으로 사보세요!")
        return
    coins = None
    if amount is not None and amount not in ("전부", "전체", "all"):
        try:
            coins = float(amount)
        except ValueError:
            await ctx.send("사용법: `%코인판매 [코인 수 | 전부]` 예) `%코인판매 0.5`")
            return
    shown = holding["amount"] if coins is None else coins
    embed = discord.Embed(
        title="₿ 비트코인 판매 확인",
        description=(
            f"**{shown:.6f} BTC**를 팔면 지금 가격({num(price)} 토큰)으로 약 "
            f"**{math.floor(shown * price * (1 - FEE))} 토큰**을 받아요. (수수료 {int(FEE * 100)}%, 토큰은 정수만 받고 남는 끝자리는 코인으로 남아요)\n"
            "확인을 누르는 순간의 가격으로 거래돼요."
        ),
        color=discord.Color.orange(),
    )

    async def on_confirm(interaction):
        r = await sell(ctx.author.id, coins)
        if isinstance(r, str):
            await respond.edit(interaction, embed=discord.Embed(description=r, color=discord.Color.red()), view=None)
            return
        await respond.edit(interaction, embed=discord.Embed(
            title="✅ 비트코인 판매 완료",
            description=f"{r['coins']:.6f} BTC를 {num(r['price'])} 토큰에 팔아서 🪙 **{r['tokens']} 토큰**을 받았어요. (남은 코인 {r['left']:.6f} BTC)",
            color=discord.Color.green(),
        ), view=None)

    await ctx.send(embed=embed, view=confirm_view(ctx.author.id, on_confirm))


@client.command(aliases=["코인확인"])
async def coin_status(ctx, member: discord.Member = None):
    member = member or ctx.author
    holding = await db.get_coin_holding(member.id)
    if holding["amount"] <= 0:
        await ctx.send(f"{member.display_name}님은 비트코인이 없어요.")
        return
    value = holding["amount"] * price
    profit = value - holding["spent"]
    embed = discord.Embed(title=f"₿ {member.display_name}님의 비트코인", color=discord.Color.orange())
    embed.add_field(name="보유", value=f"{holding['amount']:.6f} BTC", inline=True)
    embed.add_field(name="평가액", value=f"{num(value)} 토큰", inline=True)
    embed.add_field(name="평균 단가", value=f"{num(holding['spent'] / holding['amount'])} 토큰", inline=True)
    embed.add_field(name="손익 (수수료 전)", value=f"{num(profit, sign=True)} 토큰 ({num(profit / holding['spent'] * 100 if holding['spent'] else 0, sign=True)}%)", inline=False)
    await ctx.send(embed=embed)


@client.command(aliases=["코인그래프"])
async def coin_chart(ctx, minutes: int = CHART_FREE_MINUTES):
    from features import stocks   # 그래프 그리기는 주식 쪽 함수를 같이 쓴다
    if not 1 <= minutes <= HISTORY_KEEP:
        await ctx.send(f"❌ 1~{HISTORY_KEEP}분 사이로 입력해주세요.")
        return
    if not history:
        await ctx.send("❌ 아직 가격 기록이 없어요.")
        return
    minutes = min(minutes, len(history))
    cost = stocks.chart_cost(minutes)
    if cost:
        async with db.user_tx(ctx.author.id) as conn:
            money = await db.get_money(ctx.author.id, conn)
            if money < cost:
                await ctx.send(f"💸 돈이 부족합니다. {minutes}분 그래프는 {num(cost)} byte예요.")
                return
            await db.update_user(ctx.author.id, conn, money=money - cost)
            await db.log_money(ctx.author.id, "chart", -cost, f"코인 {minutes}분", conn)
    buf = stocks.draw_chart({"BTC (토큰)": list(history)}, minutes, f"비트코인 최근 {minutes}분")
    paid = f" · {num(cost)} byte 지불" if cost else ""
    await ctx.send(content=f"₿ 비트코인 최근 {minutes}분{paid}", file=discord.File(buf, filename="btc_chart.png"))


ACCEL_MAX_MINUTES = 1440


@client.command(aliases=["코인가속"])
@commands.has_permissions(administrator=True)
async def coin_accelerate(ctx, minutes: int = 60):
    """비트코인만 minutes 분이 지난 것처럼 진행한다. (뉴스와 액면 조정 포함, 뉴스 채널에는 안 올림)"""
    await ctx.message.delete()
    if not 1 <= minutes <= ACCEL_MAX_MINUTES:
        await ctx.send(f"❌ 1~{ACCEL_MAX_MINUTES}분 사이로 입력해주세요.")
        return
    if lock.locked():
        await ctx.send("⏳ 지금 코인 가격을 갱신하는 중이에요. 잠시 뒤 다시 시도해주세요.")
        return

    start_value = price
    headlines = []
    async with lock:
        try:
            for done in range(1, minutes + 1):
                last = recent_news[-1] if recent_news else None
                await tick(save=False)
                if recent_news and recent_news[-1] is not last:
                    _, headline, change = recent_news[-1]
                    headlines.append(f"`{done}분` {headline} ({num(change * 100, sign=True)}%)")
                if done % 200 == 0:
                    await asyncio.sleep(0)
        finally:
            await flush()

    # 액면 조정이 있었으면 기록도 같이 바뀌었으므로, 시작가는 기록에서 다시 읽는다
    if len(history) > minutes:
        start_value = history[-minutes - 1]
    change = price / start_value - 1 if start_value else 0
    embed = discord.Embed(
        title=f"⏩ 비트코인 {minutes}분 가속 완료",
        description=f"**{num(start_value)} → {num(price)} 토큰** ({num(change * 100, sign=True)}%)",
        color=discord.Color.orange(),
    )
    embed.add_field(
        name=f"📰 가속 중 나온 코인 뉴스 ({len(headlines)}개)",
        value="\n".join(headlines[-10:])[:1000] if headlines else "없음",
        inline=False,
    )
    embed.set_footer(text="가속 중 뉴스는 뉴스 채널에 올리지 않아요 · 주식은 %주식가속 으로 따로")
    await ctx.send(embed=embed)


@client.command(aliases=["코인랭킹"])
async def coin_rank(ctx):
    rows = sorted(await db.all_coin_holdings(), key=lambda r: -r["amount"])[:10]
    if not rows:
        await ctx.send("❌ 아직 비트코인을 가진 사람이 없어요.")
        return
    embed = discord.Embed(title="₿ 비트코인 랭킹 TOP 10", description=f"평가액 기준 (지금 {num(price)} 토큰)", color=discord.Color.orange())
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, r in enumerate(rows, start=1):
        member = ctx.guild.get_member(r["user_id"]) if ctx.guild else None
        name = member.display_name if member else f"알 수 없음 ({r['user_id']})"
        profit = r["amount"] * price - r["spent"]
        embed.add_field(
            name=f"{medals.get(i, f'{i}위')} {name}",
            value=f"{r['amount']:.6f} BTC · {num(r['amount'] * price)} 토큰 ({num(profit, sign=True)})",
            inline=False,
        )
    await ctx.send(embed=embed)
