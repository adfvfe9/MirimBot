"""토큰: 토큰 구매/확인/최대교환, 관리자 토큰 추가/제거/구매가"""


import discord
from discord import ButtonStyle
from discord.ext import commands
from discord.ui import Button

import math

import database as db
import respond
from features import abilities
from fmt import ALL, Amount, num, resolve_amount

# ───────────── 토큰 구매가 ─────────────
# 살 때마다 2배가 되고, 마지막으로 산(또는 정해진) 시각부터 하루에 4배씩 다시 떨어진다. (최소 100)
# 🔻 토큰 가격 하락 가속 능력이 있으면 하루 4배 × (1 + N%) 로 더 빨리 떨어진다.
BASE_PRICE = 100
DAILY_DROP = 4


def current_price(user, bonus_pct=0.0):
    """지금 토큰 1개 가격 (정수, 올림)"""
    stored = user["token_price"]
    since = user.get("token_price_at")
    if since is None or stored <= BASE_PRICE:
        return max(BASE_PRICE, int(stored))
    days = max(0.0, (db.now() - since).total_seconds() / 86400)
    drop = DAILY_DROP * (1 + bonus_pct / 100)
    return max(BASE_PRICE, math.ceil(stored / drop ** days))


async def price_of(user_id, user=None, conn=None):
    """(지금 가격, 하루 하락 배율)"""
    user = user or await db.get_user(user_id, conn)
    bonus = await abilities.total(user_id, "token_decay", conn)
    return current_price(user, bonus), DAILY_DROP * (1 + bonus / 100)


def cost_of(price, count):
    """price 부터 count 개를 살 때 총 가격 (1개 살 때마다 2배)"""
    return sum(price * (2 ** i) for i in range(count))


def max_affordable(price, money):
    count, total = 0, 0
    while total + price * (2 ** count) <= money:
        total += price * (2 ** count)
        count += 1
    return count, total


async def purchase_tokens(user_id, count):
    """토큰 count 개를 지금 가격으로 산다. (확인 창을 띄운 뒤 가격이 내려갔으면 내려간 가격으로)
    잔액이 부족하면 None, 성공하면 {"money", "tokens", "price"(다음 가격), "cost"}."""
    async with db.user_tx(user_id) as conn:
        user = await db.get_user(user_id, conn)
        price, _ = await price_of(user_id, user, conn)
        total_cost = cost_of(price, count)
        if user["money"] < total_cost:
            return None

        result = {
            "money": user["money"] - total_cost,
            "tokens": user["tokens"] + count,
            "price": price * (2 ** count),
            "cost": total_cost,
        }
        await db.update_user(
            user_id, conn,
            money=result["money"],
            tokens=result["tokens"],
            token_price=result["price"],
            token_price_at=db.now(),
        )
        await db.log_money(user_id, "token_buy", -total_cost, f"{count}개", conn)
        return result


@commands.command(name="구매", usage="[개수 | 최대 | 절반]")
async def buy_token(ctx, amount: Amount = 1):
    if amount == ALL:
        return await buy_token_max(ctx)
    respond.delete_soon(ctx.message)
    user_id = ctx.author.id

    user = await db.get_user(user_id)
    price, drop = await price_of(user_id, user)
    amount = resolve_amount(amount, max_affordable(price, user["money"])[0])   # 절반: 살 수 있는 개수의 절반
    if amount <= 0:
        await ctx.send("❌ 1 이상의 수량을 입력해주세요.")
        return
    total_cost = cost_of(price, amount)

    if user["money"] < total_cost:
        shortfall = total_cost - user["money"]
        await ctx.send(f"❌ 잔액이 부족합니다. 부족한 금액: **{num(shortfall)} byte**")
        return

    # 확인 임베드 및 버튼
    embed = discord.Embed(
        title="🎫 토큰 구매 확인",
        description=f"{ctx.author.mention}님, 아래 내용을 확인해주세요.",
        color=discord.Color.teal()
    )
    embed.add_field(name="구매 수량", value=f"{amount} 개", inline=True)
    embed.add_field(name="총 가격", value=f"{num(total_cost)} byte", inline=True)
    embed.set_footer(text=f"※ 토큰 가격은 살 때마다 2배가 되고, 하루에 {num(drop)}배씩 다시 떨어져요. (최소 {BASE_PRICE})")

    view = respond.ConfirmView(ctx.author)

    async def confirm_callback(interaction):
        await respond.defer(interaction)

        # 결제 및 토큰 증가 (확인을 누른 순간의 가격)
        user_tokens = await purchase_tokens(user_id, amount)
        if user_tokens is None:
            await respond.edit(interaction,
                embed=discord.Embed(
                    title="❌ 구매 실패",
                    description="잔액이 부족합니다. 명령어를 다시 실행해주세요.",
                    color=discord.Color.red()
                ),
                view=None
            )
            return

        result = discord.Embed(
            title="✅ 토큰 구매 완료",
            description=f"{amount}개의 토큰을 구매하였습니다!",
            color=discord.Color.green()
        )
        result.add_field(name="보유 토큰", value=f"{user_tokens['tokens']} 개", inline=True)
        result.add_field(name="소모한 금액", value=f"{num(user_tokens['cost'])} byte", inline=True)
        result.add_field(name="다음 구매 가격", value=f"{num(user_tokens['price'])} byte", inline=True)

        await respond.edit(interaction, embed=result, view=None)

    async def cancel_callback(interaction):
        await respond.defer(interaction)
        await respond.edit(interaction,
            embed=discord.Embed(title="❌ 구매 취소", description="구매가 취소되었습니다.", color=discord.Color.red()),
            view=None
        )

    button_yes = Button(label="확인", style=ButtonStyle.green)
    button_no = Button(label="취소", style=ButtonStyle.red)
    button_yes.callback = confirm_callback
    button_no.callback = cancel_callback

    view.add_item(button_yes)
    view.add_item(button_no)

    await ctx.send(embed=embed, view=view)

@commands.command(name="확인")
async def check_token(ctx, member: discord.Member = None):
    respond.delete_soon(ctx.message)
    member = member or ctx.author
    data = await db.get_user(member.id)

    embed = discord.Embed(
        title="🎫 토큰 현황",
        description=f"{member.display_name}님의 토큰 정보입니다.",
        color=discord.Color.purple()
    )
    price, drop = await price_of(member.id, data)
    embed.add_field(name="보유 토큰", value=f"{data['tokens']} 개", inline=True)
    embed.add_field(name="지금 구매 가격", value=f"{num(price)} byte", inline=True)
    embed.set_footer(
        text=f"살 때마다 2배, 하루에 {num(drop)}배씩 떨어져요 (최소 {BASE_PRICE}) · 토큰은 %강화 리롤에 쓰고 %강화 암시장에서 사고팔 수 있어요"
    )

    await ctx.send(embed=embed)

async def buy_token_max(ctx):
    respond.delete_soon(ctx.message)
    user_id = ctx.author.id

    user = await db.get_user(user_id)
    current_money = user["money"]

    start_price, _ = await price_of(user_id, user)
    # 보유 머니로 교환 가능한 최대 수량
    max_tokens, total_cost = max_affordable(start_price, current_money)

    if max_tokens == 0:
        await ctx.send(f"{ctx.author.mention} ❌ 보유 금액으로는 토큰을 구매할 수 없습니다.")
        return

    embed = discord.Embed(
        title="💸 최대 토큰 교환 확인",
        description=f"{ctx.author.mention}님이 보유한 금액으로 교환 가능한 최대 토큰 수는 다음과 같습니다.",
        color=discord.Color.blue()
    )
    embed.add_field(name="최대 교환 수량", value=f"{max_tokens} 개", inline=True)
    embed.add_field(name="총 필요 금액", value=f"{num(total_cost)} byte", inline=True)
    embed.set_footer(text="※ 확인을 누르면 바로 교환이 진행됩니다.")

    view = respond.ConfirmView(ctx.author)

    async def confirm_callback(interaction):
        await respond.defer(interaction)

        # 교환 처리
        user_tokens = await purchase_tokens(user_id, max_tokens)
        if user_tokens is None:
            await respond.edit(interaction,
                embed=discord.Embed(
                    title="❌ 교환 실패",
                    description="잔액이 바뀌었습니다. 명령어를 다시 실행해주세요.",
                    color=discord.Color.red()
                ),
                view=None
            )
            return

        result = discord.Embed(
            title="✅ 최대 토큰 교환 완료",
            description=f"{max_tokens}개의 토큰을 교환했습니다!",
            color=discord.Color.green()
        )
        result.add_field(name="남은 금액", value=f"{num(user_tokens['money'])} byte", inline=True)
        result.add_field(name="보유 토큰", value=f"{user_tokens['tokens']} 개", inline=True)
        result.add_field(name="소모한 금액", value=f"{num(user_tokens['cost'])} byte", inline=True)
        result.add_field(name="다음 가격", value=f"{num(user_tokens['price'])} byte", inline=True)

        await respond.edit(interaction, embed=result, view=None)

    async def cancel_callback(interaction):
        await respond.defer(interaction)
        await respond.edit(interaction,
            embed=discord.Embed(
                title="❌ 교환 취소",
                description="최대 교환이 취소되었습니다.",
                color=discord.Color.red()
            ),
            view=None
        )

    button_yes = Button(label="확인", style=discord.ButtonStyle.green)
    button_no = Button(label="취소", style=discord.ButtonStyle.red)
    button_yes.callback = confirm_callback
    button_no.callback = cancel_callback
    view.add_item(button_yes)
    view.add_item(button_no)

    await ctx.send(embed=embed, view=view)

@commands.command(name="토큰추가", usage="<@유저> <개수>")
@commands.has_permissions(administrator=True)
async def add_token(ctx, member: discord.Member, amount: int):
    respond.delete_soon(ctx.message)
    if amount <= 0:
        await ctx.send("❌ 1 이상의 수량을 입력해주세요.")
        return

    user_id = member.id

    embed = discord.Embed(
        title="🟢 토큰 추가 확인",
        description=(
            f"{member.mention}님에게 **{amount}개**의 토큰을 추가하려고 합니다.\n"
            f"확인을 누르면 즉시 적용됩니다."
        ),
        color=discord.Color.teal()
    )

    view = respond.ConfirmView(ctx.author)

    async def confirm_callback(interaction):
        await respond.defer(interaction)

        tokens = await db.add_tokens(user_id, amount)

        result = discord.Embed(
            title="✅ 토큰 추가 완료",
            description=f"{member.display_name}님에게 **{amount}개**의 토큰을 지급했습니다.",
            color=discord.Color.green()
        )
        result.add_field(name="총 보유 토큰", value=f"{tokens} 개", inline=False)
        await respond.edit(interaction, embed=result, view=None)

    async def cancel_callback(interaction):
        await respond.defer(interaction)
        await respond.edit(interaction,
            embed=discord.Embed(title="❌ 작업 취소", description="토큰 추가가 취소되었습니다.", color=discord.Color.red()),
            view=None
        )

    button_yes = Button(label="확인", style=discord.ButtonStyle.green)
    button_no = Button(label="취소", style=discord.ButtonStyle.red)
    button_yes.callback = confirm_callback
    button_no.callback = cancel_callback
    view.add_item(button_yes)
    view.add_item(button_no)

    await ctx.send(embed=embed, view=view)

@commands.command(name="토큰제거", usage="<@유저> <개수>")
@commands.has_permissions(administrator=True)
async def remove_token(ctx, member: discord.Member, amount: int):
    respond.delete_soon(ctx.message)
    if amount <= 0:
        await ctx.send("❌ 1 이상의 수량을 입력해주세요.")
        return

    user_id = member.id

    if (await db.get_user(user_id))["tokens"] < amount:
        await ctx.send("❌ 해당 유저의 토큰 수가 부족합니다.")
        return

    embed = discord.Embed(
        title="🔴 토큰 제거 확인",
        description=(
            f"{member.mention}님에게서 **{amount}개**의 토큰을 제거하려고 합니다.\n"
            f"확인을 누르면 즉시 적용됩니다."
        ),
        color=discord.Color.orange()
    )

    view = respond.ConfirmView(ctx.author)

    async def confirm_callback(interaction):
        await respond.defer(interaction)

        tokens = await db.add_tokens(user_id, -amount)
        if tokens is None:
            await respond.edit(interaction,
                embed=discord.Embed(
                    title="❌ 토큰 제거 실패",
                    description="해당 유저의 토큰 수가 부족합니다.",
                    color=discord.Color.red()
                ),
                view=None
            )
            return

        result = discord.Embed(
            title="🗑️ 토큰 제거 완료",
            description=f"{member.display_name}님에게서 **{amount}개**의 토큰을 제거했습니다.",
            color=discord.Color.red()
        )
        result.add_field(name="남은 토큰", value=f"{tokens} 개", inline=False)
        await respond.edit(interaction, embed=result, view=None)

    async def cancel_callback(interaction):
        await respond.defer(interaction)
        await respond.edit(interaction,
            embed=discord.Embed(title="❌ 작업 취소", description="토큰 제거가 취소되었습니다.", color=discord.Color.red()),
            view=None
        )

    button_yes = Button(label="확인", style=discord.ButtonStyle.green)
    button_no = Button(label="취소", style=discord.ButtonStyle.red)
    button_yes.callback = confirm_callback
    button_no.callback = cancel_callback
    view.add_item(button_yes)
    view.add_item(button_no)

    await ctx.send(embed=embed, view=view)

@commands.command(name="토큰구매가")
@commands.has_permissions(administrator=True)
async def set_token_price(ctx, member: discord.Member, new_price: int = 100):
    respond.delete_soon(ctx.message)

    if new_price <= 0:
        await ctx.send("❌ 가격은 1 이상이어야 합니다.")
        return

    user_id = member.id
    old_price, _ = await price_of(user_id)

    embed = discord.Embed(
        title="⚙️ 토큰 구매가 설정 확인",
        description=(
            f"{member.mention}님의 토큰 **구매가를 {old_price} → {new_price}** byte로 변경하려고 합니다.\n"
            f"확인을 누르면 즉시 적용됩니다."
        ),
        color=discord.Color.blurple()
    )

    view = respond.ConfirmView(ctx.author)

    async def confirm_callback(interaction):
        await respond.defer(interaction)

        await db.update_user(user_id, token_price=new_price, token_price_at=db.now())  # 지금부터 다시 떨어진다

        result = discord.Embed(
            title="✅ 토큰 구매가 설정 완료",
            description=(
                f"{member.display_name}님의 토큰 구매가를 **{num(new_price)} byte**로 설정했습니다."
            ),
            color=discord.Color.green()
        )
        await respond.edit(interaction, embed=result, view=None)

    async def cancel_callback(interaction):
        await respond.defer(interaction)
        await respond.edit(interaction,
            embed=discord.Embed(title="❌ 작업 취소", description="구매가 설정이 취소되었습니다.", color=discord.Color.red()),
            view=None
        )

    button_yes = Button(label="확인", style=discord.ButtonStyle.green)
    button_no = Button(label="취소", style=discord.ButtonStyle.red)
    button_yes.callback = confirm_callback
    button_no.callback = cancel_callback
    view.add_item(button_yes)
    view.add_item(button_no)

    await ctx.send(embed=embed, view=view)
