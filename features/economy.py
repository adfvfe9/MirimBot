"""돈: 머니 확인/추가/제거, 송금, 머니랭킹, 위로금, 기초수급, 파산"""
import datetime
import random

import discord
from discord import Embed, Interaction
from discord.ext import commands
from discord.ui import Button, View

import database as db
import respond
from bot import client
from fmt import debt_line, num
from features.bank import get_total_loan

# ───────────── 밸런스 설정 ─────────────
WELFARE_BASE = 10000          # 기초수급 첫날 금액
WELFARE_STEP = 2000           # 연속 하루마다 늘어나는 금액
WELFARE_MAX = 20000           # 기초수급 최대 금액 (6일 연속부터)

CONSOLATION_LIMIT = 1000      # 잔액이 이보다 적을 때만 위로금
CONSOLATION_MIN = 1000
CONSOLATION_MAX = 3000

SEND_FEE_RATE = 0.1           # 송금 수수료 10%
SEND_DAILY_LIMIT = 100000     # 하루 송금 한도 (수수료 제외 금액 기준)

BANKRUPTCY_INTERVAL_DAYS = 1  # 파산 간격 (일). 1 이면 하루에 1번


# 머니 확인
@client.command(aliases=['머니확인', '머니'])
async def money(ctx, member: discord.Member = None):
    await ctx.message.delete()  # 명령어 삭제
    member = member or ctx.author
    user = await db.get_user(member.id)

    description = f"**{member.display_name}** 님의 잔액은 **{num(user['money'])} byte**입니다."
    if user["unpaid_amount"] > 0:
        description += (
            f"\n🧾 미납금: **{num(user['unpaid_amount'])} byte**"
            "\n(돈이 들어오면 미납금부터 자동으로 갚아집니다)"
        )

    embed = Embed(
        title="💰 잔액 확인",
        description=description,
        color=discord.Color.gold()
    )
    await ctx.send(embed=embed)

# 머니 추가
@client.command(aliases=['머니추가'])
@commands.has_permissions(administrator=True)
async def moneyadd(ctx, member: discord.Member, amount: int):
    await ctx.message.delete()
    user_id = member.id
    view = View()

    async def confirm_callback(interaction: Interaction):
        await respond.defer(interaction)
        if interaction.user != ctx.author:
            await respond.reply(interaction, "이 버튼은 당신의 것이 아닙니다!", ephemeral=True)
            return

        result = await db.receive(user_id, amount)
        await db.log_money(user_id, "admin_add", amount, f"by {ctx.author.id}")
        embed = Embed(
            description=(
                f"✅ **{member.display_name}** 님에게 **{num(amount)} byte**를 추가했습니다."
                + debt_line(result["collected"])
            ),
            color=discord.Color.green()
        )
        await respond.edit(interaction, embed=embed, view=None)

    async def cancel_callback(interaction: Interaction):
        await respond.defer(interaction)
        embed = Embed(
            description="❌ 작업이 취소되었습니다.",
            color=discord.Color.red()
        )
        await respond.edit(interaction, embed=embed, view=None)

    button_yes = Button(label="확인", style=discord.ButtonStyle.green)
    button_no = Button(label="취소", style=discord.ButtonStyle.red)
    button_yes.callback = confirm_callback
    button_no.callback = cancel_callback
    view.add_item(button_yes)
    view.add_item(button_no)

    embed = Embed(
        description=f"⚠️ **{member.display_name}** 님에게 **{num(amount)} byte**를 추가하시겠습니까?",
        color=discord.Color.orange()
    )
    await ctx.send(embed=embed, view=view)

# 머니 제거
@client.command(aliases=['머니제거'])
@commands.has_permissions(administrator=True)
async def moneydel(ctx, member: discord.Member, amount: int):
    await ctx.message.delete()
    user_id = member.id
    view = View()

    async def confirm_callback(interaction: Interaction):
        await respond.defer(interaction)
        if interaction.user != ctx.author:
            await respond.reply(interaction, "이 버튼은 당신의 것이 아닙니다!", ephemeral=True)
            return

        # 잔액보다 많이 빼면 모자란 만큼은 미납금(빚)이 된다.
        await db.add_money(user_id, -amount)
        await db.log_money(user_id, "admin_remove", -amount, f"by {ctx.author.id}")
        embed = Embed(
            description=f"✅ **{member.display_name}** 님에게서 **{num(amount)} byte**를 제거했습니다.",
            color=discord.Color.green()
        )
        await respond.edit(interaction, embed=embed, view=None)

    async def cancel_callback(interaction: Interaction):
        await respond.defer(interaction)
        embed = Embed(
            description="❌ 작업이 취소되었습니다.",
            color=discord.Color.red()
        )
        await respond.edit(interaction, embed=embed, view=None)

    button_yes = Button(label="확인", style=discord.ButtonStyle.green)
    button_no = Button(label="취소", style=discord.ButtonStyle.red)
    button_yes.callback = confirm_callback
    button_no.callback = cancel_callback
    view.add_item(button_yes)
    view.add_item(button_no)

    embed = Embed(
        description=(
            f"⚠️ **{member.display_name}** 님에게서 **{num(amount)} byte**를 제거하시겠습니까?\n"
            "(잔액보다 많으면 모자란 만큼 미납금이 됩니다)"
        ),
        color=discord.Color.orange()
    )
    await ctx.send(embed=embed, view=view)

# 송금
def sent_today(user, today):
    """오늘 이미 보낸 금액"""
    return user["send_total"] if user["send_date"] == today else 0.0


@client.command(aliases=['송금'])
async def send(ctx, member: discord.Member, amount: int):
    await ctx.message.delete()
    sender_id = ctx.author.id
    receiver_id = member.id
    fee = int(amount * SEND_FEE_RATE)
    total_cost = amount + fee

    if amount <= 0:
        await ctx.send(embed=Embed(description="❌ 송금 금액은 0보다 커야 합니다.", color=discord.Color.red()))
        return
    if receiver_id == sender_id:
        await ctx.send(embed=Embed(description="❌ 자기 자신에게는 송금할 수 없습니다.", color=discord.Color.red()))
        return

    sender = await db.get_user(sender_id)
    remaining_limit = SEND_DAILY_LIMIT - sent_today(sender, db.today())

    if amount > remaining_limit:
        await ctx.send(embed=Embed(
            description=(
                f"❌ 하루 송금 한도는 **{num(SEND_DAILY_LIMIT)} byte**입니다.\n"
                f"오늘 더 보낼 수 있는 금액: **{num(max(0, remaining_limit))} byte**"
            ),
            color=discord.Color.red()
        ))
        return
    if sender["money"] < total_cost:
        await ctx.send(embed=Embed(description="❌ 잔액이 부족합니다! (10% 수수료 포함)", color=discord.Color.red()))
        return

    view = View()

    async def confirm_callback(interaction: Interaction):
        await respond.defer(interaction)
        if interaction.user != ctx.author:
            await respond.reply(interaction, "이 버튼은 당신의 것이 아닙니다!", ephemeral=True)
            return

        # 확인 버튼을 누른 시점의 잔액/한도로 다시 검사하고, 두 사람의 돈을 한 번에 바꾼다.
        today = db.today()
        error = None
        async with db.user_tx(sender_id, receiver_id) as conn:
            user = await db.get_user(sender_id, conn)
            total_sent = sent_today(user, today)

            if total_sent + amount > SEND_DAILY_LIMIT:
                error = f"❌ 하루 송금 한도({num(SEND_DAILY_LIMIT)} byte)를 넘습니다."
            elif user["money"] < total_cost:
                error = "❌ 잔액이 부족합니다! (10% 수수료 포함)"
            else:
                await db.update_user(
                    sender_id, conn,
                    money=user["money"] - total_cost,
                    send_date=today,
                    send_total=total_sent + amount,
                )
                result = await db.receive(receiver_id, amount, conn)
                await db.log_money(sender_id, "transfer_send", -total_cost, f"to {receiver_id}", conn)
                await db.log_money(receiver_id, "transfer_recv", amount, f"from {sender_id}", conn)

        if error:
            await respond.edit(interaction,
                embed=Embed(description=error, color=discord.Color.red()), view=None
            )
            return

        description = (
            f"💸 **{ctx.author.display_name}** 님이 **{member.display_name}** 님에게 "
            f"**{num(amount)} byte**를 송금했습니다! (수수료 {num(fee)} byte)"
        )
        if result["collected"] > 0:
            description += f"\n🧾 받는 사람의 미납금 **{num(result['collected'])} byte**가 징수되었습니다."
        await respond.edit(interaction,
            embed=Embed(description=description, color=discord.Color.green()), view=None
        )

    async def cancel_callback(interaction: Interaction):
        await respond.defer(interaction)
        embed = Embed(
            description="❌ 송금이 취소되었습니다.",
            color=discord.Color.red()
        )
        await respond.edit(interaction, embed=embed, view=None)

    button_yes = Button(label="확인", style=discord.ButtonStyle.green)
    button_no = Button(label="취소", style=discord.ButtonStyle.red)
    button_yes.callback = confirm_callback
    button_no.callback = cancel_callback
    view.add_item(button_yes)
    view.add_item(button_no)

    embed = Embed(
        description=(
            f"⚠️ **{member.display_name}** 님에게 **{num(amount)} byte**를 송금하시겠습니까?\n"
            f"(💸 수수료 {num(fee)} byte 포함, 오늘 남은 한도 {num(remaining_limit)} byte)"
        ),
        color=discord.Color.orange()
    )
    await ctx.send(embed=embed, view=view)


@client.command(aliases=["머니랭킹"])
async def money_rank(ctx):
    await ctx.message.delete()
    top = await db.top_money(10)
    if not top:
        await ctx.send("❌ 데이터가 없습니다.")
        return

    embed = discord.Embed(
        title="💰 머니 랭킹 TOP 10",
        description="현재 보유한 현금 기준 랭킹입니다. (주식·적금까지 합친 순위는 `%자산랭킹`)",
        color=discord.Color.gold()
    )

    for i, (user_id, amount) in enumerate(top, start=1):
        member = ctx.guild.get_member(user_id)
        name = member.display_name if member else f"알 수 없음 ({user_id})"
        embed.add_field(name=f"{i}위: {name}", value=f"{num(amount)} byte", inline=False)

    await ctx.send(embed=embed)


@client.command(aliases=["위로금"])
async def consolation(ctx):
    await ctx.message.delete()
    user_id = ctx.author.id
    today = db.today()
    error = None

    async with db.user_tx(user_id) as conn:
        user = await db.get_user(user_id, conn)

        if user["consolation_date"] == today:
            error = "❌ 이미 오늘 위로금을 받으셨습니다. 내일 다시 시도해주세요."
        elif user["money"] >= CONSOLATION_LIMIT:
            error = f"❌ 위로금은 잔액이 **{num(CONSOLATION_LIMIT)} byte 미만**일 때만 받을 수 있어요."
        else:
            amount = random.randint(CONSOLATION_MIN, CONSOLATION_MAX)
            await db.update_user(user_id, conn, consolation_date=today)
            result = await db.receive(user_id, amount, conn)
            await db.log_money(user_id, "consolation", amount, conn=conn)

    if error:
        await ctx.send(error)
        return

    embed = discord.Embed(
        title="💸 위로금 지급 완료!",
        description=(
            f"{ctx.author.mention}님께 **{num(amount)} byte**를 지급했습니다!"
            + debt_line(result["collected"])
        ),
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)


@client.command(aliases=["기초수급"])
async def welfare(ctx):
    await ctx.message.delete()
    user_id = ctx.author.id
    today = db.today()

    async with db.user_tx(user_id) as conn:
        user = await db.get_user(user_id, conn)
        last_claim_date = user["welfare_last_date"]
        already_claimed = last_claim_date == today

        if not already_claimed:
            # 연속 수급 여부 확인 (어제 받았으면 +1, 아니면 처음부터)
            yesterday = today - datetime.timedelta(days=1)
            if last_claim_date == yesterday:
                streak = user["welfare_streak"] + 1
            else:
                streak = 0

            amount = min(WELFARE_BASE + WELFARE_STEP * streak, WELFARE_MAX)

            # 수급 정보 저장 + 지급 (미납금이 있으면 자동 징수)
            await db.update_user(
                user_id, conn,
                welfare_last_date=today,
                welfare_streak=streak,
            )
            result = await db.receive(user_id, amount, conn)
            await db.log_money(user_id, "welfare", amount, f"streak {streak}", conn)

    if already_claimed:
        embed = discord.Embed(
            title="📛 수급 불가",
            description="오늘은 이미 기초수급을 받으셨습니다.",
            color=discord.Color.red()
        )
        embed.set_footer(text="내일 다시 이용해주세요.")
        return await ctx.send(embed=embed)

    next_amount = min(amount + WELFARE_STEP, WELFARE_MAX)
    embed = discord.Embed(
        title="✅ 기초수급 지급 완료!",
        description=debt_line(result["collected"]).strip() or None,
        color=discord.Color.green()
    )
    embed.add_field(name="💰 지급 금액", value=f"{num(amount)} byte", inline=True)
    embed.add_field(name="📆 연속 수급", value=f"{streak + 1}일차", inline=True)
    embed.set_footer(
        text=f"내일도 오면 {num(next_amount)} byte! (하루라도 빠지면 {num(WELFARE_BASE)}부터 다시)"
    )
    embed.set_author(name=str(ctx.author), icon_url=ctx.author.avatar.url if ctx.author.avatar else None)

    await ctx.send(embed=embed)

async def total_debt(user_id, user, conn=None):
    """파산 대상 빚: 미납금 + 아직 안 갚은 은행 대출(이자 포함)"""
    loans = await db.get_loans(user_id, conn)
    return user["unpaid_amount"] + get_total_loan(loans)


@client.command()
async def 파산(ctx):
    await ctx.message.delete()

    user_id = ctx.author.id
    user = await db.get_user(user_id)
    today = db.today()
    last = user["bankruptcy_date"]
    debt = await total_debt(user_id, user)

    if debt <= 0:
        embed = discord.Embed(
            title="📛 파산 불가",
            description="파산은 **빚(은행 대출 또는 미납금)이 있을 때만** 할 수 있어요.",
            color=discord.Color.red()
        )
        return await ctx.send(embed=embed)

    if last and (today - last).days < BANKRUPTCY_INTERVAL_DAYS:
        next_day = last + datetime.timedelta(days=BANKRUPTCY_INTERVAL_DAYS)
        embed = discord.Embed(
            title="📛 파산 불가",
            description=f"파산은 {BANKRUPTCY_INTERVAL_DAYS}일에 1번만 할 수 있어요.",
            color=discord.Color.red()
        )
        embed.set_footer(text=f"다음 파산 가능일: {next_day.strftime('%m월 %d일')}")
        return await ctx.send(embed=embed)

    embed = discord.Embed(
        title="⚠️ 파산 확인",
        description=(
            f"빚 **{num(debt)} byte**(대출 + 미납금)가 사라지는 대신,\n"
            "**가진 것을 전부 잃습니다.**\n\n"
            "• 현금 → 0\n"
            "• 대출, 적금 → 정리\n"
            "• 보유 주식, 레버리지 포지션 → 삭제\n"
            "• 강화 아이템 → 삭제\n\n"
            f"정말 파산하시겠습니까? (다음 파산은 {BANKRUPTCY_INTERVAL_DAYS}일 뒤부터 가능)"
        ),
        color=discord.Color.orange()
    )

    class BankruptcyView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=30)

        async def interaction_check(self, interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await respond.reply(interaction,
                    "❌ 명령어를 실행한 사람만 선택할 수 있습니다.",
                    ephemeral=True
                )
                return False
            return True

        @discord.ui.button(
            label="파산하기",
            style=discord.ButtonStyle.danger,
            emoji="💸"
        )
        async def confirm(
            self,
            interaction: discord.Interaction,
            button: discord.ui.Button
        ):
            await respond.defer(interaction)
            for item in self.children:
                item.disabled = True

            # 확인 버튼을 누른 시점에 조건을 다시 검사
            async with db.user_tx(user_id) as conn:
                current = await db.get_user(user_id, conn)
                day = db.today()
                last_now = current["bankruptcy_date"]
                debt_now = await total_debt(user_id, current, conn)
                allowed = debt_now > 0 and not (
                    last_now and (day - last_now).days < BANKRUPTCY_INTERVAL_DAYS
                )
                if allowed:
                    await db.bankrupt(user_id, day, conn)

            if not allowed:
                await respond.edit(interaction,
                    embed=discord.Embed(
                        title="📛 파산 불가",
                        description="파산 조건이 바뀌었습니다. 다시 확인해주세요.",
                        color=discord.Color.red()
                    ),
                    view=self
                )
                return

            result_embed = discord.Embed(
                title="💸 파산 완료",
                description=(
                    f"빚 **{num(debt_now)} byte**가 사라졌습니다.\n"
                    "가진 것도 모두 정리되었습니다. 처음부터 다시 시작해보세요!"
                ),
                color=discord.Color.red()
            )

            await respond.edit(interaction,
                embed=result_embed,
                view=self
            )

        @discord.ui.button(
            label="취소",
            style=discord.ButtonStyle.secondary,
            emoji="❌"
        )
        async def cancel(
            self,
            interaction: discord.Interaction,
            button: discord.ui.Button
        ):
            await respond.defer(interaction)
            for item in self.children:
                item.disabled = True

            cancel_embed = discord.Embed(
                title="✅ 파산 취소",
                description="파산을 취소했습니다. 기존 자산은 그대로 유지됩니다.",
                color=discord.Color.green()
            )

            await respond.edit(interaction,
                embed=cancel_embed,
                view=self
            )

        async def on_timeout(self):
            for item in self.children:
                item.disabled = True

            # 메시지가 이미 삭제되었거나 수정할 수 없으면 무시
            try:
                if self.message:
                    await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    view = BankruptcyView()
    message = await ctx.send(embed=embed, view=view)
    view.message = message
