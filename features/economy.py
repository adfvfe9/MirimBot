"""돈: 머니 확인/추가/제거, 송금, 머니랭킹, 위로금, 기초수급, 파산"""
import datetime
import math
import random

import discord
from discord import Embed, Interaction
from discord.ext import commands
from discord.ui import Button, View

import database as db
from bot import client


# 머니 확인
@client.command(aliases=['머니확인', '머니'])
async def money(ctx, member: discord.Member = None):
    await ctx.message.delete()  # 명령어 삭제
    member = member or ctx.author
    balance = await db.get_money(member.id)

    embed = Embed(
        title="💰 잔액 확인",
        description=f"**{member.display_name}** 님의 잔액은 **{balance:.2f} byte**입니다.",
        color=discord.Color.gold()
    )
    await ctx.send(embed=embed)

# 머니 추가
@client.command(aliases=['머니추가'])
@commands.has_permissions(administrator=True)
async def moneyadd(ctx, member: discord.Member, amount: int):
    await ctx.message.delete()
    user_id = str(member.id)
    view = View()

    async def confirm_callback(interaction: Interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("이 버튼은 당신의 것이 아닙니다!", ephemeral=True)
            return

        await db.add_money(user_id, amount)
        embed = Embed(
            description=f"✅ **{member.display_name}** 님에게@ **{amount} byte**를 추가했습니다.",
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=embed, view=None)

    async def cancel_callback(interaction: Interaction):
        embed = Embed(
            description="❌ 작업이 취소되었습니다.",
            color=discord.Color.red()
        )
        await interaction.response.edit_message(embed=embed, view=None)

    button_yes = Button(label="확인", style=discord.ButtonStyle.green)
    button_no = Button(label="취소", style=discord.ButtonStyle.red)
    button_yes.callback = confirm_callback
    button_no.callback = cancel_callback
    view.add_item(button_yes)
    view.add_item(button_no)

    embed = Embed(
        description=f"⚠️ **{member.display_name}** 님에게 **{amount} byte**를 추가하시겠습니까?",
        color=discord.Color.orange()
    )
    await ctx.send(embed=embed, view=view)

# 머니 제거
@client.command(aliases=['머니제거'])
@commands.has_permissions(administrator=True)
async def moneydel(ctx, member: discord.Member, amount: int):
    await ctx.message.delete()
    user_id = str(member.id)
    view = View()

    async def confirm_callback(interaction: Interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("이 버튼은 당신의 것이 아닙니다!", ephemeral=True)
            return

        await db.add_money(user_id, -amount)
        embed = Embed(
            description=f"✅ **{member.display_name}** 님에게서 **{amount} byte**를 제거했습니다.",
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=embed, view=None)

    async def cancel_callback(interaction: Interaction):
        embed = Embed(
            description="❌ 작업이 취소되었습니다.",
            color=discord.Color.red()
        )
        await interaction.response.edit_message(embed=embed, view=None)

    button_yes = Button(label="확인", style=discord.ButtonStyle.green)
    button_no = Button(label="취소", style=discord.ButtonStyle.red)
    button_yes.callback = confirm_callback
    button_no.callback = cancel_callback
    view.add_item(button_yes)
    view.add_item(button_no)

    embed = Embed(
        description=f"⚠️ **{member.display_name}** 님에게서 **{amount} byte**를 제거하시겠습니까?",
        color=discord.Color.orange()
    )
    await ctx.send(embed=embed, view=view)

# 송금
@client.command(aliases=['송금'])
async def send(ctx, member: discord.Member, amount: int):
    await ctx.message.delete()
    sender_id = str(ctx.author.id)
    receiver_id = str(member.id)
    fee = int(amount * 0.1)
    total_cost = amount + fee

    if await db.get_money(sender_id) < total_cost:
        embed = Embed(
            description="❌ 잔액이 부족합니다! (10% 수수료 포함)",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    if amount <= 0:
        embed = Embed(
            description="❌ 송금 금액은 0보다 커야 합니다.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    view = View()

    async def confirm_callback(interaction: Interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("이 버튼은 당신의 것이 아닙니다!", ephemeral=True)
            return

        # 확인 버튼을 누른 시점의 잔액으로 다시 검사하고, 두 사람의 돈을 한 번에 바꾼다.
        async with db.user_tx(sender_id, receiver_id) as conn:
            enough = await db.get_money(sender_id, conn) >= total_cost
            if enough:
                await db.add_money(sender_id, -total_cost, conn)
                await db.add_money(receiver_id, amount, conn)

        if not enough:
            embed = Embed(
                description="❌ 잔액이 부족합니다! (10% 수수료 포함)",
                color=discord.Color.red()
            )
            await interaction.response.edit_message(embed=embed, view=None)
            return

        embed = Embed(
            description=f"💸 **{ctx.author.display_name}** 님이 **{member.display_name}** 님에게 **{amount} byte**를 송금했습니다! (수수료 {fee} byte)",
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=embed, view=None)

    async def cancel_callback(interaction: Interaction):
        embed = Embed(
            description="❌ 송금이 취소되었습니다.",
            color=discord.Color.red()
        )
        await interaction.response.edit_message(embed=embed, view=None)

    button_yes = Button(label="확인", style=discord.ButtonStyle.green)
    button_no = Button(label="취소", style=discord.ButtonStyle.red)
    button_yes.callback = confirm_callback
    button_no.callback = cancel_callback
    view.add_item(button_yes)
    view.add_item(button_no)

    embed = Embed(
        description=f"⚠️ **{member.display_name}** 님에게 **{amount} byte**를 송금하시겠습니까?\n(💸 수수료 {fee} byte 포함)",
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
        description="현재 보유한 byte 기준 랭킹입니다.",
        color=discord.Color.gold()
    )

    for i, (user_id, amount) in enumerate(top, start=1):
        member = ctx.guild.get_member(user_id)
        name = member.display_name if member else f"알 수 없음 ({user_id})"
        embed.add_field(name=f"{i}위: {name}", value=f"{amount:.2f} byte", inline=False)

    await ctx.send(embed=embed)


@client.command(aliases=["위로금"])
async def consolation(ctx):
    await ctx.message.delete()
    user_id = ctx.author.id
    today = db.today()

    async with db.user_tx(user_id) as conn:
        user = await db.get_user(user_id, conn)
        already_claimed = user["consolation_date"] == today

        if not already_claimed:
            base_amount = random.randint(1, 1000)
            bonus_amount = 0

            # ✅ 머니가 마이너스일 경우 추가 위로금 지급
            money_balance = user["money"]
            if money_balance < 0:
                debt = abs(money_balance)
                bonus_amount = int(500 * math.sqrt(debt))

            total_amount = base_amount + bonus_amount
            await db.update_user(
                user_id, conn,
                money=money_balance + total_amount,
                consolation_date=today,
            )

    if already_claimed:
        await ctx.send("❌ 이미 오늘 위로금을 받으셨습니다. 내일 다시 시도해주세요.")
        return

    # ✅ 메시지 출력
    description = f"{ctx.author.mention}님께 {base_amount} byte를 지급했습니다!"
    if bonus_amount > 0:
        description += f"\n💸 추가 위로금 +{bonus_amount} byte (머니 {money_balance + total_amount:.2f} byte)"

    embed = discord.Embed(
        title="💸 위로금 지급 완료!",
        description=description,
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
            # 연속 수급 여부 확인
            yesterday = today - datetime.timedelta(days=1)
            if last_claim_date == yesterday:
                streak = user["welfare_streak"] + 1
            else:
                streak = 0

            bonus_times = min(streak, 20)
            amount = 10000 * (4 ** bonus_times)

            # 지급 + 수급 정보 저장
            await db.update_user(
                user_id, conn,
                money=user["money"] + amount,
                welfare_last_date=today,
                welfare_streak=streak,
            )

    if already_claimed:
        embed = discord.Embed(
            title="📛 수급 불가",
            description="오늘은 이미 기초수급을 받으셨습니다.",
            color=discord.Color.red()
        )
        embed.set_footer(text="내일 다시 이용해주세요.")
        return await ctx.send(embed=embed)

    embed = discord.Embed(
        title="✅ 기초수급 지급 완료!",
        color=discord.Color.green()
    )
    embed.add_field(name="💰 지급 금액", value=f"{amount} byte", inline=True)
    embed.add_field(name="📆 연속 수급", value=f"{streak + 1}일차", inline=True)
    embed.set_footer(text="내일 다시 오시면 2배 보너스를 받을 수 있어요!")
    embed.set_author(name=str(ctx.author), icon_url=ctx.author.avatar.url if ctx.author.avatar else None)

    await ctx.send(embed=embed)

@client.command()
async def 파산(ctx):
    await ctx.message.delete()

    user_id = ctx.author.id
    user = await db.get_user(user_id)
    money = user["money"]
    today = db.today()

    if user["bankruptcy_date"] == today:
        embed = discord.Embed(
            title="📛 파산 불가",
            description="오늘은 이미 파산했습니다.",
            color=discord.Color.red()
        )
        embed.set_footer(text="내일 다시 이용해주세요.")
        return await ctx.send(embed=embed)

    embed = discord.Embed(
        title="⚠️ 파산 확인",
        description=(
            f"현재 보유한 돈이 **{money:,} byte** 있습니다.\n\n"
            "정말 파산하시겠습니까?\n"
            "파산하면 보유한 돈이 전부 **0 byte**로 초기화됩니다."
        ),
        color=discord.Color.orange()
    )

    class BankruptcyView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=30)

        async def interaction_check(self, interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message(
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
            try:
                await db.update_user(
                    user_id,
                    money=0,
                    bankruptcy_date=db.today(),
                )

                for item in self.children:
                    item.disabled = True

                result_embed = discord.Embed(
                    title="💸 파산 완료",
                    description=(
                        f"기존 보유 금액: **{money:,} byte**\n"
                        "현재 보유 금액: **0 byte**\n\n"
                        "모든 돈을 잃었습니다. 다시 열심히 모아보세요!"
                    ),
                    color=discord.Color.red()
                )

                await interaction.response.edit_message(
                    embed=result_embed,
                    view=self
                )

            except Exception as e:
                print(f"[파산 버튼 오류] {type(e).__name__}: {e}")

                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ 파산 처리 중 오류가 발생했습니다. 관리자에게 문의해주세요.",
                        ephemeral=True
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
            for item in self.children:
                item.disabled = True

            cancel_embed = discord.Embed(
                title="✅ 파산 취소",
                description="파산을 취소했습니다. 기존 자산은 그대로 유지됩니다.",
                color=discord.Color.green()
            )

            await interaction.response.edit_message(
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
