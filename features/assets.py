"""순자산: %자산 (내 자산 내역), %자산랭킹 (순자산 TOP 10), %자산그래프 (순자산 변화)

순자산 = 현금 + 주식 평가액 + 적금(이자 포함) + 레버리지 포지션 가치 + 강화템 판매가 - 갚을 대출금 - 미납금
- 1시간마다 모든 유저의 순자산을 기록한다 (최근 30일). %자산그래프 와 💰 재산 칭호(최고 순자산)에 쓴다.
- 장착한 칭호가 %자산 / %자산랭킹 이름 앞에 붙는다. (features/titles.py)
"""
import asyncio
import datetime
import io

import discord
from matplotlib.ticker import FuncFormatter

import database as db
from bot import client
from features import bank, enhance, futures, stocks
from fmt import num

SNAPSHOT_MINUTES = 60
HISTORY_DAYS = 30
GRAPH_DEFAULT_DAYS = 7


def titles():
    from features import titles as module
    return module


def stock_value(holdings):
    return sum(
        h["quantity"] * stocks.stock_prices.get(symbol, {}).get("current", h["avg_price"])
        for symbol, h in holdings.items()
    )


def positions_value(positions):
    return sum(
        futures.equity(p, futures.current_price(p["symbol"]))
        for p in positions
        if p["symbol"] in stocks.stock_prices
    )


def breakdown(user, holdings, positions, loans, items):
    """순자산 내역 dict. items = {아이템 이름: 레벨}"""
    parts = {
        "현금": user["money"],
        "주식": stock_value(holdings),
        "적금": bank.deposit_value(user),
        "레버리지": positions_value(positions),
        "강화템": sum(enhance.SELL_PRICE.get(level, 0) for level in items.values()),
        "대출": -bank.get_total_loan(loans),
        "미납금": -user["unpaid_amount"],
    }
    parts["순자산"] = sum(parts.values())
    return parts


async def user_breakdown(user_id):
    # 서로 상관없는 조회라 한꺼번에 보낸다 (차례로 보내면 DB 왕복 5번을 기다린다)
    return breakdown(*await asyncio.gather(
        db.get_user(user_id),
        db.get_portfolio(user_id),
        db.get_positions(user_id),
        db.get_loans(user_id),
        db.get_enhance_items(user_id),
    ))


async def net_worth(user_id):
    return (await user_breakdown(user_id))["순자산"]


async def all_net_worths():
    """{user_id: 순자산} 모든 유저"""
    users, portfolios, all_positions, all_loans, all_items = await asyncio.gather(
        db.all_users(), db.all_portfolios(), db.all_positions(), db.all_open_loans(), db.all_enhance_items(),
    )
    positions, loans, items = {}, {}, {}
    for p in all_positions:
        positions.setdefault(p["user_id"], []).append(p)
    for loan in all_loans:
        loans.setdefault(loan["user_id"], []).append(loan)
    for item in all_items:
        items.setdefault(item["user_id"], {})[item["item_name"]] = item["level"]
    return {
        u["user_id"]: breakdown(
            u,
            portfolios.get(u["user_id"], {}),
            positions.get(u["user_id"], []),
            loans.get(u["user_id"], []),
            items.get(u["user_id"], {}),
        )["순자산"]
        for u in users
    }


# ───────────── 1시간마다 기록 ─────────────
last_snapshot = None


async def maybe_snapshot():
    """1분 루프에서 부른다. 1시간이 지났으면 모든 유저 순자산을 기록하고 칭호를 확인한다."""
    global last_snapshot
    now = db.now()
    if last_snapshot is None:
        saved = await db.get_state("asset_snapshot_at")
        last_snapshot = datetime.datetime.fromisoformat(saved) if saved else now - datetime.timedelta(hours=1)
    if now - last_snapshot < datetime.timedelta(minutes=SNAPSHOT_MINUTES):
        return
    worths = await all_net_worths()
    await db.save_asset_snapshot(worths, now, HISTORY_DAYS)
    last_snapshot = now
    await db.set_state("asset_snapshot_at", now.isoformat())
    # 재산 칭호 등이 새로 풀렸는지 확인. 유저마다 쿼리가 여러 번이라 1분 루프를 막지 않게 따로 돌린다
    asyncio.create_task(check_titles(worths))


async def check_titles(worths):
    for user_id, worth in worths.items():
        try:
            await titles().check(user_id, worth)
        except Exception as e:
            print(f"[칭호] {user_id} 확인 실패: {type(e).__name__}: {e}")


# ───────────── 명령어 ─────────────

@client.command(aliases=["자산"])
async def assets(ctx, member: discord.Member = None):
    await ctx.message.delete()
    member = member or ctx.author
    parts, badge = await asyncio.gather(user_breakdown(member.id), titles().badge(member.id))

    embed = discord.Embed(
        title=f"💼 {badge}{member.display_name}님의 자산",
        color=discord.Color.blue()
    )
    icons = {"현금": "💵", "주식": "📈", "적금": "🏦", "레버리지": "🎢", "강화템": "🔨", "대출": "💳", "미납금": "🧾"}
    for name, icon in icons.items():
        if parts[name] != 0 or name in ("현금",):
            embed.add_field(name=f"{icon} {name}", value=f"{num(parts[name])} byte", inline=True)
    embed.add_field(name="🏆 순자산", value=f"**{num(parts['순자산'])} byte**", inline=False)
    embed.set_footer(text="순자산 = 현금 + 주식 + 적금 + 레버리지 + 강화템 - 대출 - 미납금 · %자산그래프 로 변화 보기")
    await ctx.send(embed=embed)


@client.command(aliases=["자산랭킹", "순자산랭킹"])
async def asset_rank(ctx):
    await ctx.message.delete()

    worths, equipped = await asyncio.gather(all_net_worths(), db.equipped_titles())
    if not worths:
        await ctx.send("❌ 데이터가 없습니다.")
        return
    ranking = sorted(worths.items(), key=lambda x: x[1], reverse=True)

    embed = discord.Embed(
        title="🏆 순자산 랭킹 TOP 10",
        description="현금 + 주식 + 적금 + 레버리지 + 강화템 - 대출 - 미납금 기준입니다.",
        color=discord.Color.gold()
    )
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, (user_id, worth) in enumerate(ranking[:10], start=1):
        member = ctx.guild.get_member(user_id) if ctx.guild else None
        name = member.display_name if member else f"알 수 없음 ({user_id})"
        embed.add_field(
            name=f"{medals.get(i, f'{i}위')} {titles().badge_of(equipped.get(user_id))}{name}",
            value=f"{num(worth)} byte",
            inline=False
        )

    my_rank = next((i for i, (uid, _) in enumerate(ranking, start=1) if uid == ctx.author.id), None)
    if my_rank:
        embed.set_footer(text=f"{ctx.author.display_name}님은 {len(ranking)}명 중 {my_rank}위")
    await ctx.send(embed=embed)


def draw_worth_chart(series, title):
    """series: {이름: [(시각, 순자산), ...]} → PNG"""
    plt = stocks.plt   # 한글 글꼴 설정을 같이 쓴다
    plt.figure(figsize=(10, 4) if len(series) == 1 else (12, 6))
    for name, points in series.items():
        # 그래프 시각은 한국 시간으로 (matplotlib 은 기본으로 UTC 로 그린다)
        plt.plot([t.astimezone(db.KST).replace(tzinfo=None) for t, _ in points], [w for _, w in points], label=name, marker="." if len(points) < 50 else None)
    plt.title(title)
    plt.ylabel("순자산 (byte)")
    plt.grid(True)
    plt.legend()
    plt.gca().yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    plt.gcf().autofmt_xdate()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight")
    buf.seek(0)
    plt.close()
    return buf


@client.command(aliases=["자산그래프"])
async def asset_chart(ctx, *args):
    """%자산그래프 [@유저 ...] [일]  — 기본 나, 최근 7일 (최대 30일). 여러 명을 멘션하면 같이 그린다."""
    await ctx.message.delete()
    days = GRAPH_DEFAULT_DAYS
    for arg in args:
        if arg.isdigit():
            days = int(arg)
    if not 1 <= days <= HISTORY_DAYS:
        await ctx.send(f"❌ 1~{HISTORY_DAYS}일 사이로 입력해주세요.")
        return
    members = [m for m in ctx.message.mentions if not m.bot][:5] or [ctx.author]

    since = db.now() - datetime.timedelta(days=days)
    series = {}
    for member in members:
        points = await db.asset_history(member.id, since)
        points.append((db.now(), await net_worth(member.id)))   # 마지막 점은 지금 값
        series[member.display_name] = points
    if all(len(p) < 2 for p in series.values()):
        await ctx.send("📉 아직 기록이 부족해요. 순자산은 1시간마다 기록돼요. 조금 뒤에 다시 봐주세요!")
        return

    names = ", ".join(series)
    buf = await stocks.in_plot_thread(draw_worth_chart, series, f"{names} 순자산 (최근 {days}일)")
    lines = []
    for name, points in series.items():
        first, last = points[0][1], points[-1][1]
        change = f" ({num((last / first - 1) * 100, sign=True)}%)" if first > 0 else ""
        lines.append(f"**{name}** {num(first)} → **{num(last)} byte**{change}")
    await ctx.send(content="📈 " + "\n".join(lines), file=discord.File(buf, filename="asset_chart.png"))
