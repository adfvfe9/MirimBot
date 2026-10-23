"""주식 예약 매매: 가격이 정한 값에 닿으면 자동으로 사고판다

    %예약구매 <주식> <수량> <가격> [이하 | 이상]     기본: 가격 이하로 떨어지면 산다
    %예약판매 <주식> <수량 | 전부> <가격> [이상 | 이하]  기본: 가격 이상으로 오르면 판다 (이하 = 손절)
    %예약목록                                        내 예약 보기 · 취소

- 예약할 때 🪙 토큰 ORDER_TOKEN_COST 개를 낸다. (취소하거나 만료돼도 돌려주지 않는다)
- 한 사람당 MAX_ORDERS 개까지, EXPIRE_HOURS 시간이 지나면 저절로 없어진다.
- 1분마다 주가가 바뀐 직후에 확인하고, 조건이 맞으면 그 순간 가격으로 거래한다. (정한 가격이 아니라 그때 가격)
  수수료 · 단타 수수료는 직접 사고팔 때와 같다.
- 돈이나 주식이 모자라면 그 예약은 취소된다. 거래 / 취소 / 만료는 DM 과 %주식확인 알림으로 알려준다.
"""
import datetime

import discord
from discord.ui import Select, View

import database as db
import respond
from bot import client
from features import stocks
from fmt import num

ORDER_TOKEN_COST = 1
MAX_ORDERS = 5
EXPIRE_HOURS = 24

DIRECTION_WORDS = {"이하": "below", "이상": "above"}


def describe(o):
    qty = "전부" if o["quantity"] is None else f"{o['quantity']}주"
    side = "사기" if o["side"] == "buy" else "팔기"
    cond = "이하가" if o["direction"] == "below" else "이상이"
    return f"`#{o['id']}` **{o['symbol']}** {qty} {side} · {num(o['price'])} {cond} 되면"


def triggered(o, price):
    return price <= o["price"] if o["direction"] == "below" else price >= o["price"]


async def tell(user_id, text):
    """DM + %주식확인 알림"""
    await db.add_notice(user_id, text)
    user = client.get_user(user_id)
    if user is not None:
        try:
            await user.send(text)
        except discord.HTTPException:
            pass        # DM 을 막아 둔 사람


async def place(user_id, side, stock_name, quantity_text, price_text, direction_text=None):
    """예약하기. 실패하면 안내(str), 성공하면 예약 dict"""
    usage = ("사용법: `%예약구매 <주식> <수량> <가격> [이하|이상]`" if side == "buy"
             else "사용법: `%예약판매 <주식> <수량|전부> <가격> [이상|이하]`")
    symbol = stocks.stock_aliases.get((stock_name or "").upper())
    if symbol not in stocks.stock_prices:
        return "❌ 존재하지 않는 주식입니다.\n" + usage
    if side == "sell" and quantity_text in ("전부", "전체", "all"):
        quantity = None
    elif quantity_text and quantity_text.isdigit() and int(quantity_text) > 0:
        quantity = int(quantity_text)
    else:
        return "❌ 수량은 1 이상 숫자로 써주세요." + (" (판매는 `전부`도 돼요)" if side == "sell" else "") + "\n" + usage
    try:
        price = float(str(price_text).replace(",", ""))
    except (TypeError, ValueError):
        return "❌ 가격을 숫자로 써주세요.\n" + usage
    if price <= 0:
        return "❌ 가격은 0보다 커야 해요."
    if direction_text is None:
        direction = "below" if side == "buy" else "above"
    elif direction_text in DIRECTION_WORDS:
        direction = DIRECTION_WORDS[direction_text]
    else:
        return "❌ 마지막에는 `이하` 또는 `이상`만 쓸 수 있어요.\n" + usage
    now_price = stocks.stock_prices[symbol]["current"]
    if triggered({"price": price, "direction": direction}, now_price):
        return f"❌ 지금 가격({num(now_price)})이 이미 조건에 맞아요. 바로 사고팔려면 `%주식구매` / `%주식판매`를 쓰세요."

    async with db.user_tx(user_id) as conn:
        if len(await db.user_orders(user_id, conn)) >= MAX_ORDERS:
            return f"❌ 예약은 한 사람당 {MAX_ORDERS}개까지예요. `%예약목록`에서 취소할 수 있어요."
        if side == "sell" and quantity is not None:
            held = (await db.get_portfolio(user_id, conn)).get(symbol, {}).get("quantity", 0)
            if held < quantity:
                return f"❌ {symbol} 주식이 {held}주뿐이에요."
        left = await db.add_tokens(user_id, -ORDER_TOKEN_COST, conn)
        if left is None:
            return f"❌ 예약하려면 🪙 토큰 {ORDER_TOKEN_COST}개가 필요해요. (`%토큰구매`, 퀴즈, 일일 미션)"
        order = await db.add_order(user_id, symbol, side, quantity, price, direction,
                                   db.now() + datetime.timedelta(hours=EXPIRE_HOURS), conn)
    return {**order, "tokens_left": left}


async def execute(o):
    """조건이 맞은 예약 하나를 처리한다. 처리했으면 (거래든 취소든) True"""
    if not await db.delete_order(o["id"]):
        return False            # 그사이 취소됐다
    uid, symbol = o["user_id"], o["symbol"]
    if symbol not in stocks.stock_prices:
        await tell(uid, f"❌ 예약 {describe(o)} — {symbol}이(가) 상장폐지돼서 취소됐어요.")
        return True
    if o["side"] == "buy":
        r = await stocks.buy_shares(uid, symbol, o["quantity"])
        if r is None:
            await tell(uid, f"❌ 예약 {describe(o)} — 돈이 모자라서 취소됐어요.")
        else:
            await tell(uid, f"🤖 예약 구매 완료: **{symbol} {o['quantity']}주** @{num(r['price'])} = {num(r['cost'])} byte (남은 돈 {num(r['balance'])})")
        return True
    held = (await db.get_portfolio(uid)).get(symbol, {}).get("quantity", 0)
    quantity = held if o["quantity"] is None else o["quantity"]
    r = await stocks.sell_shares(uid, {symbol: quantity}) if quantity > 0 else None
    if r is None:
        await tell(uid, f"❌ 예약 {describe(o)} — 팔 주식이 모자라서 취소됐어요.")
    else:
        price = stocks.stock_prices[symbol]["current"]
        await tell(uid, f"🤖 예약 판매 완료: **{symbol} {quantity}주** @{num(price)} → {num(r['earned'])} byte (수수료 {r['fees'][symbol]:.1%})")
    return True


async def check():
    """1분 주가 갱신 직후에 부른다. (처리한 수, 만료된 수)"""
    now = db.now()
    done = expired = 0
    for o in await db.all_orders():
        if o["expires_at"] <= now:
            if await db.delete_order(o["id"]):
                expired += 1
                await tell(o["user_id"], f"⌛ 예약 {describe(o)} — {EXPIRE_HOURS}시간이 지나서 없어졌어요.")
            continue
        price = stocks.stock_prices.get(o["symbol"], {}).get("current")
        if price is None or triggered(o, price):
            done += await execute(o)
    return done, expired


# ───────────── 명령어 ─────────────

async def place_command(ctx, side, args):
    result = await place(ctx.author.id, side, *(list(args) + [None] * 4)[:4])
    if isinstance(result, str):
        await ctx.send(result)
        return
    await ctx.send(
        f"🤖 예약했어요: {describe(result)} (지금 {num(stocks.stock_prices[result['symbol']]['current'])})\n"
        f"🪙 토큰 {ORDER_TOKEN_COST}개 사용 (남은 {result['tokens_left']}개) · {EXPIRE_HOURS}시간 안에 안 되면 없어져요 · `%예약목록`"
    )


@client.command(aliases=["예약구매"])
async def order_buy(ctx, *args):
    await place_command(ctx, "buy", args)


@client.command(aliases=["예약판매"])
async def order_sell(ctx, *args):
    await place_command(ctx, "sell", args)


class OrdersView(View):
    def __init__(self, user_id, orders):
        super().__init__(timeout=180)
        self.user_id = user_id
        menu = Select(
            placeholder="취소할 예약 고르기 (토큰은 돌려받지 못해요)",
            options=[discord.SelectOption(label=f"#{o['id']} {o['symbol']} {'구매' if o['side'] == 'buy' else '판매'}", value=str(o["id"]))
                     for o in orders],
        )
        menu.callback = self.on_cancel
        self.add_item(menu)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await respond.reply(interaction, "❌ 내 예약만 취소할 수 있어요.", ephemeral=True)
            return False
        return True

    async def on_cancel(self, interaction):
        await respond.defer(interaction)
        order_id = int(interaction.data["values"][0])
        ok = await db.delete_order(order_id, user_id=self.user_id)
        await respond.edit(interaction, content=f"🗑️ 예약 #{order_id}을(를) 취소했어요." if ok else "이미 처리되거나 없어진 예약이에요.",
                           embed=None, view=None)


@client.command(aliases=["예약목록"])
async def order_list(ctx):
    orders = await db.user_orders(ctx.author.id)
    lines = []
    for o in orders:
        now_price = stocks.stock_prices.get(o["symbol"], {}).get("current")
        lines.append(f"{describe(o)} · 지금 {num(now_price) if now_price else '?'} · <t:{int(o['expires_at'].timestamp())}:R> 만료")
    embed = discord.Embed(
        title=f"🤖 {ctx.author.display_name}님의 예약 ({len(orders)}/{MAX_ORDERS})",
        description="\n".join(lines) or "예약이 없어요. `%예약구매` / `%예약판매`로 걸어보세요.",
        color=discord.Color.teal(),
    )
    embed.set_footer(text=f"예약 하나에 🪙 {ORDER_TOKEN_COST}개 · {EXPIRE_HOURS}시간 · 1분마다 확인 · 그때 가격으로 거래")
    await ctx.send(embed=embed, view=OrdersView(ctx.author.id, orders) if orders else None)
