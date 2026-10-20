"""레버리지 거래: 롱(오르면 이득) / 숏(내리면 이득)

    %롱 <종목> <증거금> [배율]     예) %롱 JAVA 10000 5
    %숏 <종목> <증거금> [배율]     예) %숏 RUST 5000 3
    %포지션 [@유저]               내 포지션과 손익 보기
    %청산 <번호 | 전체>            포지션 정리하고 돈 받기

- 증거금(내 돈) × 배율 만큼의 규모로 거래한다. 5배면 가격이 1% 움직일 때 내 돈은 5% 움직인다.
- 손실이 증거금만큼 커지면(= 청산가에 닿으면) 1분마다 하는 가격 갱신 때 강제청산되고 증거금을 전부 잃는다.
- 청산할 때 수수료: 포지션 규모의 0.5%.
- 상장폐지되면 가격 0 으로 정산한다. (롱은 전부 잃고, 숏은 크게 번다)
"""
import discord
from discord.ui import Button, View

import database as db
from bot import client
from features import stocks
from fmt import debt_line, num

# ───────────── 밸런스 설정 ─────────────
MAX_LEVERAGE = 10             # 최대 배율
MARGIN_LIMIT = 100000         # 한 사람이 동시에 걸 수 있는 증거금 합계
CLOSE_FEE = 0.005             # 청산 수수료 (포지션 규모 기준 0.5%)

SIDE_TEXT = {"LONG": "📈 롱", "SHORT": "📉 숏"}


# ───────────── 계산 ─────────────

def pnl(pos, price):
    """현재 가격 기준 손익"""
    size = pos["margin"] * pos["leverage"]
    change = price / pos["entry_price"] - 1
    return size * change if pos["side"] == "LONG" else -size * change


def equity(pos, price):
    """지금 청산하면 남는 내 돈 (수수료 전, 0 미만으로는 안 내려감)"""
    return max(0.0, pos["margin"] + pnl(pos, price))


def liquidation_price(pos):
    """이 가격에 닿으면 강제청산"""
    move = 1 / pos["leverage"]
    if pos["side"] == "LONG":
        return pos["entry_price"] * (1 - move)
    return pos["entry_price"] * (1 + move)


def close_fee(pos):
    return pos["margin"] * pos["leverage"] * CLOSE_FEE


def current_price(symbol):
    return stocks.stock_prices[symbol]["current"]


# ───────────── 주식 가격 갱신 때 호출됨 (stocks.update_stocks) ─────────────

async def check_liquidations():
    """새 가격으로 모든 포지션을 검사해서, 손실이 증거금 이상이면 강제청산한다."""
    for pos in await db.all_positions():
        if pos["symbol"] not in stocks.stock_prices:
            continue
        price = current_price(pos["symbol"])
        if equity(pos, price) > 0:
            continue

        async with db.transaction() as conn:
            # delete_position 이 None 이면 이미 다른 곳에서 정리된 것
            if await db.delete_position(pos["id"], conn) is None:
                continue
            await db.add_notice(
                pos["user_id"],
                f"💥 강제청산: `{pos['symbol']}` {SIDE_TEXT[pos['side']]} {pos['leverage']}배 "
                f"(진입가 {num(pos['entry_price'])} → {num(price)}) — "
                f"증거금 {num(pos['margin'])} byte를 모두 잃었습니다.",
                conn,
            )
        print(f"[강제청산] 유저 {pos['user_id']} {pos['symbol']} {pos['side']} x{pos['leverage']}")


async def settle_symbol(symbol, exit_price, reason):
    """해당 종목의 포지션을 exit_price 로 전부 정산한다. (상장폐지 등)"""
    for pos in await db.all_positions():
        if pos["symbol"] != symbol:
            continue
        payout = equity(pos, exit_price)
        async with db.user_tx(pos["user_id"]) as conn:
            if await db.delete_position(pos["id"], conn) is None:
                continue
            if payout > 0:
                await db.receive(pos["user_id"], payout, conn)
            await db.add_notice(
                pos["user_id"],
                f"⚠️ {reason}: `{symbol}` {SIDE_TEXT[pos['side']]} {pos['leverage']}배 포지션이 "
                f"가격 {num(exit_price)}으로 정산되어 {num(payout)} byte를 돌려받았습니다.",
                conn,
            )


# ───────────── 진입 ─────────────

async def open_position(ctx, side, stock_name, margin, leverage):
    user_id = ctx.author.id
    symbol = stocks.stock_aliases.get(stock_name.upper())

    if not symbol or symbol not in stocks.stock_prices:
        await ctx.send("❌ 존재하지 않는 주식입니다.")
        return
    if margin <= 0:
        await ctx.send("❌ 증거금은 1 이상이어야 합니다.")
        return
    if not 1 <= leverage <= MAX_LEVERAGE:
        await ctx.send(f"❌ 배율은 1~{MAX_LEVERAGE}배 사이로 입력해주세요.")
        return

    user = await db.get_user(user_id)
    used = sum(p["margin"] for p in await db.get_positions(user_id))
    if user["money"] < margin:
        await ctx.send("❌ 잔액이 부족합니다.")
        return
    if used + margin > MARGIN_LIMIT:
        await ctx.send(
            f"❌ 증거금 합계는 최대 **{num(MARGIN_LIMIT)} byte**까지예요. "
            f"(지금 사용 중: {num(used)} byte)"
        )
        return

    price = current_price(symbol)
    preview = {"side": side, "margin": margin, "leverage": leverage, "entry_price": price}

    embed = discord.Embed(
        title=f"{SIDE_TEXT[side]} 포지션 진입 확인",
        description=(
            f"{ctx.author.mention}님, **{symbol}** 가격이 "
            f"{'오르면' if side == 'LONG' else '내리면'} 이득을 보는 거래입니다."
        ),
        color=discord.Color.green() if side == "LONG" else discord.Color.red()
    )
    embed.add_field(name="증거금 (내 돈)", value=f"{num(margin)} byte", inline=True)
    embed.add_field(name="배율", value=f"{leverage}배", inline=True)
    embed.add_field(name="거래 규모", value=f"{num(margin * leverage)} byte", inline=True)
    embed.add_field(name="현재가 (진입가)", value=f"{num(price)} byte", inline=True)
    embed.add_field(
        name="💥 청산가",
        value=f"{num(liquidation_price(preview))} byte",
        inline=True
    )
    embed.add_field(
        name="📌 알아두기",
        value=(
            f"가격이 1% 움직이면 내 돈은 {leverage}% 움직여요.\n"
            "청산가에 닿으면 증거금을 **전부** 잃어요.\n"
            f"정리할 때 수수료 {num(CLOSE_FEE * 100)}% (거래 규모 기준): {num(close_fee(preview))} byte\n"
            "실제 진입가는 확인 버튼을 누른 순간의 가격이에요."
        ),
        inline=False
    )

    view = View()

    async def confirm_callback(interaction: discord.Interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("이 버튼은 당신의 것이 아니에요!", ephemeral=True)
            return

        entry = current_price(symbol)
        error = None
        async with db.user_tx(user_id) as conn:
            money = await db.get_money(user_id, conn)
            used_now = sum(p["margin"] for p in await db.get_positions(user_id, conn))
            if money < margin:
                error = "잔액이 부족합니다."
            elif used_now + margin > MARGIN_LIMIT:
                error = f"증거금 합계 한도({num(MARGIN_LIMIT)} byte)를 넘습니다."
            else:
                await db.update_user(user_id, conn, money=money - margin)
                position_id = await db.add_position(user_id, symbol, side, margin, leverage, entry, conn)

        if error:
            await interaction.response.edit_message(
                embed=discord.Embed(title="❌ 진입 실패", description=error, color=discord.Color.red()),
                view=None
            )
            return

        pos = {"side": side, "margin": margin, "leverage": leverage, "entry_price": entry}
        await interaction.response.edit_message(
            embed=discord.Embed(
                title=f"✅ {SIDE_TEXT[side]} 진입 완료 (#{position_id})",
                description=(
                    f"**{symbol}** {leverage}배, 증거금 {num(margin)} byte\n"
                    f"진입가 {num(entry)} / 청산가 {num(liquidation_price(pos))}\n"
                    f"`%포지션`으로 손익을 확인하고 `%청산 {position_id}`로 정리하세요."
                ),
                color=discord.Color.green()
            ),
            view=None
        )

    async def cancel_callback(interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=discord.Embed(title="❌ 진입 취소", description="거래가 취소되었습니다.", color=discord.Color.red()),
            view=None
        )

    yes = Button(label="확인", style=discord.ButtonStyle.green)
    no = Button(label="취소", style=discord.ButtonStyle.red)
    yes.callback = confirm_callback
    no.callback = cancel_callback
    view.add_item(yes)
    view.add_item(no)

    await ctx.send(embed=embed, view=view)


@client.command(aliases=["롱"])
async def open_long(ctx, stock_name: str, margin: int, leverage: int = 1):
    await ctx.message.delete()
    await open_position(ctx, "LONG", stock_name, margin, leverage)


@client.command(aliases=["숏"])
async def open_short(ctx, stock_name: str, margin: int, leverage: int = 1):
    await ctx.message.delete()
    await open_position(ctx, "SHORT", stock_name, margin, leverage)


# ───────────── 조회 ─────────────

@client.command(aliases=["포지션"])
async def positions(ctx, member: discord.Member = None):
    await ctx.message.delete()
    member = member or ctx.author

    if member == ctx.author:
        notices = await db.pop_notices(member.id)
        if notices:
            await ctx.send("\n".join(notices))

    rows = await db.get_positions(member.id)
    if not rows:
        await ctx.send(f"{member.display_name}님은 열려 있는 레버리지 포지션이 없습니다.")
        return

    embed = discord.Embed(
        title=f"📊 {member.display_name}님의 레버리지 포지션",
        description="가격은 1분마다 바뀌어요. 청산가에 닿으면 강제청산됩니다.",
        color=discord.Color.purple()
    )

    total_margin = 0.0
    total_pnl = 0.0
    for pos in rows:
        price = current_price(pos["symbol"])
        p = pnl(pos, price)
        total_margin += pos["margin"]
        total_pnl += p
        embed.add_field(
            name=f"#{pos['id']}  {pos['symbol']} {SIDE_TEXT[pos['side']]} {pos['leverage']}배",
            value=(
                f"증거금 {num(pos['margin'])} byte\n"
                f"진입가 {num(pos['entry_price'])} → 현재가 {num(price)}\n"
                f"손익 **{num(p, sign=True)} byte** ({num(p / pos['margin'] * 100, sign=True)}%)\n"
                f"청산가 {num(liquidation_price(pos))}"
            ),
            inline=False
        )

    embed.add_field(
        name="합계",
        value=f"증거금 {num(total_margin)} byte / 손익 **{num(total_pnl, sign=True)} byte**",
        inline=False
    )
    embed.set_footer(text="정리하려면 %청산 <번호> 또는 %청산 전체")
    await ctx.send(embed=embed)


# ───────────── 청산 ─────────────

@client.command(aliases=["청산"])
async def close_position(ctx, target: str = None):
    await ctx.message.delete()
    user_id = ctx.author.id

    if target is None:
        await ctx.send("❗ 청산할 포지션 번호를 입력해주세요. 예: `%청산 12` 또는 `%청산 전체`")
        return

    mine = await db.get_positions(user_id)
    if target in ("전체", "all"):
        chosen = mine
    else:
        try:
            position_id = int(target.lstrip("#"))
        except ValueError:
            await ctx.send("❌ 포지션 번호를 숫자로 입력해주세요. (`%포지션`에서 확인)")
            return
        chosen = [p for p in mine if p["id"] == position_id]

    if not chosen:
        await ctx.send("❌ 해당 포지션이 없습니다. (`%포지션`에서 번호를 확인하세요)")
        return

    lines = []
    total_payout = 0.0
    total_collected = 0.0
    for pos in chosen:
        price = current_price(pos["symbol"])
        p = pnl(pos, price)
        payout = max(0.0, equity(pos, price) - close_fee(pos))
        async with db.user_tx(user_id) as conn:
            # 이미 강제청산된 포지션이면 None (두 번 정산 방지)
            if await db.delete_position(pos["id"], conn) is None:
                continue
            result = await db.receive(user_id, payout, conn)
        total_payout += payout
        total_collected += result["collected"]
        lines.append(
            f"#{pos['id']} {pos['symbol']} {SIDE_TEXT[pos['side']]} {pos['leverage']}배: "
            f"손익 {num(p, sign=True)} → 받은 돈 {num(payout)} byte"
        )

    if not lines:
        await ctx.send("❌ 이미 정리된 포지션입니다.")
        return

    embed = discord.Embed(
        title="✅ 포지션 청산 완료",
        description="\n".join(lines) + debt_line(total_collected),
        color=discord.Color.green()
    )
    embed.add_field(name="받은 돈 합계 (수수료 차감)", value=f"{num(total_payout)} byte", inline=False)
    await ctx.send(embed=embed)
