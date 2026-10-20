"""순자산: %자산 (내 자산 내역), %자산랭킹 (순자산 TOP 10)

순자산 = 현금 + 주식 평가액 + 적금(이자 포함) + 레버리지 포지션 가치 - 갚을 대출금 - 미납금
"""
import discord

import database as db
from bot import client
from features import bank, futures, stocks
from fmt import num


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


def breakdown(user, holdings, positions, loans):
    """순자산 내역 dict"""
    parts = {
        "현금": user["money"],
        "주식": stock_value(holdings),
        "적금": bank.deposit_value(user),
        "레버리지": positions_value(positions),
        "대출": -bank.get_total_loan(loans),
        "미납금": -user["unpaid_amount"],
    }
    parts["순자산"] = sum(parts.values())
    return parts


@client.command(aliases=["자산"])
async def assets(ctx, member: discord.Member = None):
    await ctx.message.delete()
    member = member or ctx.author

    user = await db.get_user(member.id)
    parts = breakdown(
        user,
        await db.get_portfolio(member.id),
        await db.get_positions(member.id),
        await db.get_loans(member.id),
    )

    embed = discord.Embed(
        title=f"💼 {member.display_name}님의 자산",
        color=discord.Color.blue()
    )
    icons = {"현금": "💵", "주식": "📈", "적금": "🏦", "레버리지": "🎢", "대출": "💳", "미납금": "🧾"}
    for name, icon in icons.items():
        if parts[name] != 0 or name in ("현금",):
            embed.add_field(name=f"{icon} {name}", value=f"{num(parts[name])} byte", inline=True)
    embed.add_field(name="🏆 순자산", value=f"**{num(parts['순자산'])} byte**", inline=False)
    embed.set_footer(text="순자산 = 현금 + 주식 + 적금 + 레버리지 - 대출 - 미납금")
    await ctx.send(embed=embed)


@client.command(aliases=["자산랭킹", "순자산랭킹"])
async def asset_rank(ctx):
    await ctx.message.delete()

    users = await db.all_users()
    if not users:
        await ctx.send("❌ 데이터가 없습니다.")
        return

    portfolios = await db.all_portfolios()
    positions, loans = {}, {}
    for p in await db.all_positions():
        positions.setdefault(p["user_id"], []).append(p)
    for loan in await db.all_open_loans():
        loans.setdefault(loan["user_id"], []).append(loan)

    ranking = sorted(
        (
            (
                u["user_id"],
                breakdown(
                    u,
                    portfolios.get(u["user_id"], {}),
                    positions.get(u["user_id"], []),
                    loans.get(u["user_id"], []),
                )["순자산"],
            )
            for u in users
        ),
        key=lambda x: x[1],
        reverse=True,
    )

    embed = discord.Embed(
        title="🏆 순자산 랭킹 TOP 10",
        description="현금 + 주식 + 적금 + 레버리지 - 대출 - 미납금 기준입니다.",
        color=discord.Color.gold()
    )
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, (user_id, worth) in enumerate(ranking[:10], start=1):
        member = ctx.guild.get_member(user_id) if ctx.guild else None
        name = member.display_name if member else f"알 수 없음 ({user_id})"
        embed.add_field(
            name=f"{medals.get(i, f'{i}위')} {name}",
            value=f"{num(worth)} byte",
            inline=False
        )

    my_rank = next((i for i, (uid, _) in enumerate(ranking, start=1) if uid == ctx.author.id), None)
    if my_rank:
        embed.set_footer(text=f"{ctx.author.display_name}님은 {len(ranking)}명 중 {my_rank}위")
    await ctx.send(embed=embed)
