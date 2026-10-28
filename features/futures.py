"""레버리지 거래: 롱(오르면 이득) / 숏(내리면 이득)

    %롱 <종목> <증거금> [배율]     예) %롱 JAVA 10000 5 · %롱 JAVA 5만 5 · %롱 JAVA 올인 10 (절반도 된다)
    %숏 <종목> <증거금> [배율]     예) %숏 RUST 5000 3
    %포지션 [@유저]               내 포지션과 손익 보기
    %청산 <번호 | 전체>            포지션 정리하고 돈 받기

- 증거금(내 돈) × 배율(최대 10배, 🚀 배율 한계 돌파 능력만큼 더, 상한 없음) 만큼의 규모로 거래한다. 5배면 가격이 1% 움직일 때 내 돈은 5% 움직인다.
- 손실이 증거금만큼 커지면(= 청산가에 닿으면) 1분마다 하는 가격 갱신 때 강제청산되고 증거금을 전부 잃는다.
- 수수료: 진입할 때 포지션 규모의 0.5% (증거금과 따로 잔액에서 낸다), 정리할 때 포지션 규모의 0.5%.
- 보유 비용: 포지션 규모의 시간당 0.1% 가 증거금에서 계속 빠진다. (오래 들고 있을수록 청산가가 가까워진다)
- 상장폐지되면 가격 0 으로 정산한다. (롱은 전부 잃고, 숏은 크게 번다)
- 뉴스로 방향이 정해진 구간에는 새로 진입할 수 없다. (뉴스 보고 들어가면 무조건 버는 구멍 방지)
  초상승장 / 주식부도 중에는 모든 종목, 부도 위기 뉴스가 진행 중이면 그 종목. 이미 연 포지션은 그대로 둔다.
"""
import discord
from discord.ui import Button

import database as db
import respond
from bot import client
from features import abilities, digest, stocks
from fmt import ALL, HALF, Amount, debt_line, num, resolve_amount

# ───────────── 밸런스 설정 ─────────────
MAX_LEVERAGE = 10             # 최대 배율
MARGIN_LIMIT = 100000         # 한 사람이 동시에 걸 수 있는 증거금 합계 (📊 능력만큼 늘어난다)
OPEN_FEE = 0.005              # 진입 수수료 (포지션 규모 기준 0.5%, 증거금과 따로 낸다)
CLOSE_FEE = 0.005             # 청산 수수료 (포지션 규모 기준 0.5%)
# 보유 비용: 포지션 규모 기준 시간당 0.1%. 증거금에서 계속 빠지므로 오래 들고 있을수록 청산가가 가까워진다.
# 손실은 증거금에서 멈추고 이익은 끝이 없어서, 보유 비용이 없으면 고배율을 오래 들고 있는 것만으로 평균 이득이 났다.
# (시뮬레이션: 4배 변동폭에서 아무렇게나 15배 10시간 보유가 +5.8% → 이 비용으로 손해)
HOLD_FEE_PER_HOUR = 0.001

SIDE_TEXT = {"LONG": "📈 롱", "SHORT": "📉 숏"}


# ───────────── 계산 ─────────────

def pnl(pos, price):
    """현재 가격 기준 손익"""
    size = pos["margin"] * pos["leverage"]
    change = price / pos["entry_price"] - 1
    return size * change if pos["side"] == "LONG" else -size * change


def holding_fee(pos, at=None):
    """지금까지 쌓인 보유 비용 (진입 전 미리보기처럼 opened_at 이 없으면 0)"""
    opened = pos.get("opened_at")
    if opened is None:
        return 0.0
    hours = max(0.0, ((at or db.now()) - opened).total_seconds() / 3600)
    return pos["margin"] * pos["leverage"] * HOLD_FEE_PER_HOUR * hours


def hourly_fee(pos):
    return pos["margin"] * pos["leverage"] * HOLD_FEE_PER_HOUR


def equity(pos, price):
    """지금 청산하면 남는 내 돈 (보유 비용은 빼고 청산 수수료는 빼기 전, 0 미만으로는 안 내려감)"""
    return max(0.0, pos["margin"] + pnl(pos, price) - holding_fee(pos))


def liquidation_price(pos):
    """이 가격에 닿으면 강제청산. 쌓인 보유 비용만큼 진입가 쪽으로 가까워진다."""
    move = max(0.0, pos["margin"] - holding_fee(pos)) / (pos["margin"] * pos["leverage"])
    if pos["side"] == "LONG":
        return pos["entry_price"] * (1 - move)
    return pos["entry_price"] * (1 + move)


def open_fee(pos):
    return pos["margin"] * pos["leverage"] * OPEN_FEE


def close_fee(pos):
    return pos["margin"] * pos["leverage"] * CLOSE_FEE


def position_memo(pos):
    """돈 기록(money_log)에 남길 포지션 설명. 예) RUST SHORT x5 margin 100000"""
    return f"{pos['symbol']} {pos['side']} x{pos['leverage']} margin {pos['margin']}"


def current_price(symbol):
    return stocks.stock_prices[symbol]["current"]


# ───────────── 주식 가격 갱신 때 호출됨 (stocks.update_stocks) ─────────────

async def check_liquidations(positions=None):
    """새 가격으로 모든 포지션을 검사해서, 손실이 증거금 이상이면 강제청산한다. 청산한 개수를 돌려준다.
    positions 를 주면 DB 에서 읽지 않고 그 목록을 검사하고, 정리된 포지션은 목록에서 뺀다. (%주식가속)"""
    count = 0
    for pos in list(positions) if positions is not None else await db.all_positions():
        if pos["symbol"] not in stocks.stock_prices:
            continue
        price = current_price(pos["symbol"])
        if equity(pos, price) > 0:
            continue

        if positions is not None:
            positions.remove(pos)
        async with db.user_tx(pos["user_id"]) as conn:
            # delete_position 이 None 이면 이미 다른 곳에서 정리된 것
            if await db.delete_position(pos["id"], conn) is None:
                continue
            # 🧯 청산 보험: 증거금의 일부를 돌려받는다
            refund = pos["margin"] * await abilities.total(pos["user_id"], "liq_insurance", conn) / 100
            if refund > 0:
                await db.receive(pos["user_id"], refund, conn)
                await db.log_money(pos["user_id"], "futures_insurance", refund, position_memo(pos), conn)
            await db.add_notice(
                pos["user_id"],
                f"💥 강제청산: `{pos['symbol']}` {SIDE_TEXT[pos['side']]} {pos['leverage']}배 "
                f"(진입가 {num(pos['entry_price'])} → {num(price)}) — "
                + (f"🧯 청산 보험으로 증거금 {num(pos['margin'])} byte 중 {num(refund)} byte를 돌려받았습니다."
                   if refund > 0 else f"증거금 {num(pos['margin'])} byte를 모두 잃었습니다."),
                conn,
            )
        print(f"[강제청산] 유저 {pos['user_id']} {pos['symbol']} {pos['side']} x{pos['leverage']}")
        digest.liquidation(pos["user_id"], pos, pos["margin"] - refund)
        count += 1
    return count


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
                await db.log_money(pos["user_id"], "futures_settle", payout, position_memo(pos), conn)
            await db.add_notice(
                pos["user_id"],
                f"⚠️ {reason}: `{symbol}` {SIDE_TEXT[pos['side']]} {pos['leverage']}배 포지션이 "
                f"가격 {num(exit_price)}으로 정산되어 {num(payout)} byte를 돌려받았습니다.",
                conn,
            )


# ───────────── 진입 ─────────────

async def entry_block_reason(symbol):
    """지금 이 종목에 새로 진입할 수 없으면 그 이유, 진입할 수 있으면 None."""
    state = await stocks.get_effective_market_state()
    if state == "HYPER_BULL":
        return "🚀 초상승장(거품) 중에는 레버리지 신규 진입이 막혀 있어요."
    if state == "CRASH":
        return "📉 주식부도(거품 붕괴) 중에는 레버리지 신규 진입이 막혀 있어요."
    if stocks.news().under_default_risk(symbol):
        return f"💥 `{symbol}`은(는) 부도 위기 중이라 레버리지 신규 진입이 막혀 있어요."
    return None


async def margin_limit(user_id, conn=None):
    """이 사람의 증거금 합계 한도 (📊 능력 포함)"""
    return MARGIN_LIMIT * (1 + await abilities.total(user_id, "margin_limit", conn) / 100)


async def open_position(ctx, side, stock_name, margin, leverage):
    user_id = ctx.author.id
    symbol = stocks.stock_aliases.get(stock_name.upper())

    if not symbol or symbol not in stocks.stock_prices:
        await ctx.send("❌ 존재하지 않는 주식입니다.")
        return
    max_leverage = MAX_LEVERAGE + int(await abilities.total(user_id, "leverage_up"))  # 🚀 배율 한계 돌파
    if not 1 <= leverage <= max_leverage:
        await ctx.send(f"❌ 배율은 1~{max_leverage}배 사이로 입력해주세요.")
        return
    blocked = await entry_block_reason(symbol)
    if blocked:
        await ctx.send(f"❌ {blocked}")
        return

    user = await db.get_user(user_id)
    used = sum(p["margin"] for p in await db.get_positions(user_id))
    limit = await margin_limit(user_id)
    # 올인 / 절반: 잔액(진입 수수료 포함)과 증거금 한도 안에서 걸 수 있는 만큼
    affordable = max(0.0, min(user["money"] / (1 + leverage * OPEN_FEE), limit - used))
    typed = margin not in (ALL, HALF)
    margin = resolve_amount(margin, affordable)
    if margin <= 0:
        await ctx.send("❌ 증거금은 1 이상이어야 합니다." if typed else
                       "❌ 걸 수 있는 증거금이 없어요. (잔액이 부족하거나 증거금 한도를 다 썼어요)")
        return

    price = current_price(symbol)
    preview = {"symbol": symbol, "side": side, "margin": margin, "leverage": leverage, "entry_price": price}
    total = margin + open_fee(preview)  # 진입할 때 잔액에서 나가는 돈

    if user["money"] < total:
        await ctx.send(f"❌ 잔액이 부족합니다. (증거금 + 진입 수수료 {num(total)} byte 필요)")
        return
    if used + margin > limit:
        await ctx.send(
            f"❌ 증거금 합계는 최대 **{num(limit)} byte**까지예요. "
            f"(지금 사용 중: {num(used)} byte)"
        )
        return

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
            f"진입 수수료 {num(OPEN_FEE * 100)}% (거래 규모 기준): {num(open_fee(preview))} byte → "
            f"지금 잔액에서 **{num(total)} byte**가 나가요\n"
            f"정리할 때 수수료 {num(CLOSE_FEE * 100)}% (거래 규모 기준): {num(close_fee(preview))} byte\n"
            f"보유 비용 시간당 {num(HOLD_FEE_PER_HOUR * 100)}% (거래 규모 기준): **시간당 {num(hourly_fee(preview))} byte**가 "
            "증거금에서 빠져요. 오래 들고 있을수록 청산가가 가까워져요.\n"
            "실제 진입가는 확인 버튼을 누른 순간의 가격이에요."
        ),
        inline=False
    )

    view = respond.ConfirmView(ctx.author)

    async def confirm_callback(interaction: discord.Interaction):
        await respond.defer(interaction)

        entry = current_price(symbol)
        # 확인 창을 띄운 뒤에 뉴스가 났을 수도 있으니 다시 검사
        error = await entry_block_reason(symbol)
        async with db.user_tx(user_id) as conn:
            money = await db.get_money(user_id, conn)
            used_now = sum(p["margin"] for p in await db.get_positions(user_id, conn))
            if error:
                pass
            elif money < total:
                error = f"잔액이 부족합니다. (증거금 + 진입 수수료 {num(total)} byte 필요)"
            elif used_now + margin > await margin_limit(user_id, conn):
                error = f"증거금 합계 한도({num(await margin_limit(user_id, conn))} byte)를 넘습니다."
            else:
                fee = open_fee(preview)
                await db.update_user(user_id, conn, money=money - margin - fee)
                position_id = await db.add_position(user_id, symbol, side, margin, leverage, entry, conn)
                await db.log_money(user_id, "futures_open", -margin, position_memo(preview), conn)
                await db.log_money(user_id, "futures_fee", -fee, position_memo(preview), conn)

        if error:
            await respond.edit(interaction,
                embed=discord.Embed(title="❌ 진입 실패", description=error, color=discord.Color.red()),
                view=None
            )
            return

        pos = {"side": side, "margin": margin, "leverage": leverage, "entry_price": entry}
        await respond.edit(interaction,
            embed=discord.Embed(
                title=f"✅ {SIDE_TEXT[side]} 진입 완료 (#{position_id})",
                description=(
                    f"**{symbol}** {leverage}배, 증거금 {num(margin)} byte (진입 수수료 {num(open_fee(preview))} byte)\n"
                    f"진입가 {num(entry)} / 청산가 {num(liquidation_price(pos))}\n"
                    f"`%포지션`으로 손익을 확인하고 `%청산 {position_id}`로 정리하세요."
                ),
                color=discord.Color.green()
            ),
            view=None
        )

    async def cancel_callback(interaction: discord.Interaction):
        await respond.defer(interaction)
        await respond.edit(interaction,
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
async def open_long(ctx, stock_name: str, margin: Amount, leverage: int = 1):
    respond.delete_soon(ctx.message)
    await open_position(ctx, "LONG", stock_name, margin, leverage)


@client.command(aliases=["숏"])
async def open_short(ctx, stock_name: str, margin: Amount, leverage: int = 1):
    respond.delete_soon(ctx.message)
    await open_position(ctx, "SHORT", stock_name, margin, leverage)


# ───────────── 조회 ─────────────

@client.command(aliases=["포지션"])
async def positions(ctx, member: discord.Member = None):
    respond.delete_soon(ctx.message)
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
        hold = holding_fee(pos)
        p = pnl(pos, price) - hold   # 보유 비용까지 뺀 손익
        total_margin += pos["margin"]
        total_pnl += p
        embed.add_field(
            name=f"#{pos['id']}  {pos['symbol']} {SIDE_TEXT[pos['side']]} {pos['leverage']}배",
            value=(
                f"증거금 {num(pos['margin'])} byte\n"
                f"진입가 {num(pos['entry_price'])} → 현재가 {num(price)}\n"
                f"손익 **{num(p, sign=True)} byte** ({num(p / pos['margin'] * 100, sign=True)}%)\n"
                f"보유 비용 -{num(hold)} byte (시간당 {num(hourly_fee(pos))})\n"
                f"청산가 {num(liquidation_price(pos))}"
            ),
            inline=False
        )

    embed.add_field(
        name="합계",
        value=f"증거금 {num(total_margin)} byte / 손익 **{num(total_pnl, sign=True)} byte** (보유 비용 포함)",
        inline=False
    )
    embed.set_footer(text="정리하려면 %청산 <번호> 또는 %청산 전체")
    await ctx.send(embed=embed)


# ───────────── 청산 ─────────────

@client.command(aliases=["청산"])
async def close_position(ctx, target: str = None):
    respond.delete_soon(ctx.message)
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
        hold = holding_fee(pos)
        payout = max(0.0, equity(pos, price) - close_fee(pos))   # equity 에서 보유 비용은 이미 빠짐
        async with db.user_tx(user_id) as conn:
            # 이미 강제청산된 포지션이면 None (두 번 정산 방지)
            if await db.delete_position(pos["id"], conn) is None:
                continue
            result = await db.receive(user_id, payout, conn)
            await db.log_money(user_id, "futures_close", payout, f"{position_memo(pos)} hold_fee {hold:.2f}", conn)
        total_payout += payout
        total_collected += result["collected"]
        if payout - pos["margin"] > 0:
            digest.leverage_win(user_id, pos, payout - pos["margin"])
        lines.append(
            f"#{pos['id']} {pos['symbol']} {SIDE_TEXT[pos['side']]} {pos['leverage']}배: "
            f"손익 {num(p, sign=True)} · 보유 비용 -{num(hold)} → 받은 돈 {num(payout)} byte"
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
