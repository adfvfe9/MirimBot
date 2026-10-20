"""도박: 도박, 도박올인, 도박랭킹, 가위바위보"""
import math
import random
import time

import discord

import database as db
from bot import client


# ───────────── 도박 ─────────────
GAMBLE_COOLDOWN = 10  # 초

async def play_gamble(user_id, amount=None):
    """도박 1회 처리. amount 가 None 이면 올인.
    실패하면 안내 메시지(str), 성공하면 결과 dict 를 돌려준다."""
    now = db.now()

    async with db.user_tx(user_id) as conn:
        user = await db.get_user(user_id, conn)
        current_money = user["money"]

        if amount is None and current_money <= 0:
            return "❌ 잔액이 부족합니다."

        # 쿨타임 체크
        last_time = user["gamble_last_at"]
        if last_time:
            elapsed = (now - last_time).total_seconds()
            if elapsed < GAMBLE_COOLDOWN:
                remain = int(GAMBLE_COOLDOWN - elapsed)
                return f"⏳ 아직 도박할 수 없어요! 다시 시도하려면 **{remain}초** 기다려주세요."

        if amount is None:
            amount = current_money  # 올인!
        elif amount <= 0:
            return "❌ 1 이상의 금액을 입력해주세요."
        elif current_money < amount:
            return "❌ 잔액이 부족합니다."

        # -1000% ~ +1000%
        multiplier = random.uniform(-10.0, 10.0)
        # 실제 도박 결과 계산 (float 유지)
        profit = round(amount * multiplier, 2)
        net_change = profit - amount
        new_balance = round(current_money - amount + profit, 2)

        # 잔액, 도박 통계, 쿨타임을 한 번에 저장
        await db.update_user(
            user_id, conn,
            money=new_balance,
            gamble_net=round(user["gamble_net"] + net_change, 2),
            gamble_last_at=now,
        )

    return {
        "amount": amount,
        "multiplier": multiplier,
        "profit": profit,
        "net_change": net_change,
        "balance": new_balance,
    }


def gamble_embed(result, title, description):
    amount = result["amount"]
    multiplier = result["multiplier"]
    profit = result["profit"]
    net_change = result["net_change"]

    # 결과 메시지
    color = 0x2ecc71 if profit > amount else (0xe74c3c if profit < amount else 0x95a5a6)
    outcome = "🎉 잭팟!" if multiplier > 5 else "👍 성공!" if profit > amount else "😢 손해..." if profit < amount else "💸 본전"
    net_symbol = "📈" if net_change > 0 else "📉" if net_change < 0 else "💸"

    embed = discord.Embed(
        title=title,
        description=description,
        color=color
    )
    embed.add_field(name="배율", value=f"{multiplier:.2f}배", inline=True)
    embed.add_field(name="획득 금액", value=f"{profit:.2f} byte", inline=True)
    embed.add_field(name="순이익", value=f"{net_symbol} {net_change:+.2f} byte", inline=True)
    embed.add_field(name="현재 잔액", value=f"{result['balance']:.2f} byte", inline=False)
    embed.set_footer(text=outcome)
    return embed


@client.command(aliases=["도박"])
async def gamble(ctx, amount: int):
    await ctx.message.delete()

    result = await play_gamble(ctx.author.id, amount)
    if isinstance(result, str):
        await ctx.send(result)
        return

    await ctx.send(embed=gamble_embed(
        result, "🎲 도박 결과", f"{ctx.author.mention}님이 **{amount} byte**를 도박했습니다!"
    ))


@client.command(aliases=["도박랭킹"])
async def gamble_rank(ctx):
    await ctx.message.delete()
    top = await db.top_gamble(10)
    if not top:
        await ctx.send("❌ 아직 도박 기록이 없습니다.")
        return

    embed = discord.Embed(
        title="🎰 도박 수익 랭킹 TOP 10",
        description="도박으로 가장 많이 벌거나 잃은 유저 순위입니다.",
        color=discord.Color.purple()
    )

    for i, (user_id, profit) in enumerate(top, start=1):
        member = ctx.guild.get_member(user_id)
        name = member.display_name if member else f"알 수 없음 ({user_id})"
        symbol = "📈" if profit > 0 else "📉" if profit < 0 else "💸"
        embed.add_field(name=f"{i}위: {name}", value=f"{symbol} {profit:+.2f} byte", inline=False)

    await ctx.send(embed=embed)


@client.command(aliases=["도박올인"])
async def gamble_allin(ctx):
    await ctx.message.delete()

    result = await play_gamble(ctx.author.id)
    if isinstance(result, str):
        await ctx.send(result)
        return

    await ctx.send(embed=gamble_embed(
        result, "🎲 도박 올인 결과", f"{ctx.author.mention}님이 **{result['amount']:.2f} byte**를 올인했습니다!"
    ))


rps_streaks = {}
rps_cooldowns = {}


class RPSView(discord.ui.View):
    def __init__(self, player_id: int):
        super().__init__(timeout=600)

        self.player_id = player_id
        self.streak = 0
        self.pending_reward = 0
        self.finished = False
        self.played = False
        self.waiting_for_choice = True

        # 처음에는 가위바위보 버튼만 사용 가능
        self.continue_game.disabled = True
        self.cash_out.disabled = True

    async def interaction_check(
        self,
        interaction: discord.Interaction
    ) -> bool:
        # 다른 유저의 버튼 클릭 차단
        if interaction.user.id != self.player_id:
            await interaction.response.send_message(
                "❌ 다른 사람의 가위바위보 게임입니다! "
                "본인이 시작한 게임의 버튼만 누를 수 있습니다.",
                ephemeral=True
            )
            return False

        # 종료된 게임의 버튼 클릭 차단
        if self.finished:
            await interaction.response.send_message(
                "이미 종료된 게임입니다.",
                ephemeral=True
            )
            return False

        return True

    def make_embed(
        self,
        title: str,
        description: str,
        color=discord.Color.blurple()
    ):
        embed = discord.Embed(
            title=title,
            description=description,
            color=color
        )

        embed.add_field(
            name="🔥 현재 연승",
            value=f"**{self.streak}연승**",
            inline=True
        )

        embed.add_field(
            name="💰 누적 보상",
            value=f"**{self.pending_reward:,} Byte**",
            inline=True
        )

        next_reward = 1000 * math.factorial(self.streak + 1)

        embed.add_field(
            name="🎁 다음 승리 보상",
            value=f"**+{next_reward:,} Byte**",
            inline=False
        )

        embed.set_footer(
            text="그만하고 수령을 누르면 누적 보상을 받을 수 있습니다."
        )

        return embed

    async def play(
        self,
        interaction: discord.Interaction,
        choice: str
    ):
        if not self.waiting_for_choice:
            await interaction.response.send_message(
                "먼저 계속하기 버튼을 눌러 다음 판을 시작해 주세요.",
                ephemeral=True
            )
            return

        user_id = str(self.player_id)
        now = time.time()

        # 첫 판 시작 시에만 쿨타임 검사
        if not self.played:
            last_play = rps_cooldowns.get(user_id, 0)
            remaining = 60 - (now - last_play)

            if remaining > 0:
                await interaction.response.send_message(
                    f"⏳ 쿨타임이 **{math.ceil(remaining)}초** 남았습니다.",
                    ephemeral=True
                )
                return

            rps_cooldowns[user_id] = now
            self.played = True

        # 선택 중복 방지
        self.waiting_for_choice = False

        # 이번 판의 선택 버튼 비활성화
        self.scissors.disabled = True
        self.rock.disabled = True
        self.paper.disabled = True

        bot_choice = random.choice(["가위", "바위", "보"])

        embed = discord.Embed(
            title="✊ 가위바위보 결과",
            description=(
                f"👤 **내 선택:** {choice}\n"
                f"🤖 **봇 선택:** {bot_choice}"
            ),
            color=discord.Color.blurple()
        )

        # 무승부: 연승과 누적 보상 유지
        if choice == bot_choice:
            embed.color = discord.Color.gold()

            embed.add_field(
                name="🤝 무승부!",
                value="연승과 누적 보상이 유지됩니다.",
                inline=False
            )

        # 승리
        elif (
            (choice == "가위" and bot_choice == "보")
            or (choice == "바위" and bot_choice == "가위")
            or (choice == "보" and bot_choice == "바위")
        ):
            self.streak += 1

            reward = 1000 * math.factorial(self.streak)
            self.pending_reward += reward

            embed.color = discord.Color.green()

            embed.add_field(
                name="🎉 승리!",
                value=(
                    f"이번 승리 보상: **{reward:,} Byte**\n"
                    f"누적 보상: **{self.pending_reward:,} Byte**"
                ),
                inline=False
            )

        # 패배: 연승과 누적 보상 초기화
        else:
            self.streak = 0
            self.pending_reward = 0
            self.finished = True

            rps_streaks[user_id] = 0

            for button in self.children:
                button.disabled = True

            embed.color = discord.Color.red()

            embed.add_field(
                name="💀 패배!",
                value="연승이 초기화되었고 누적 보상을 잃었습니다.",
                inline=False
            )

            embed.set_footer(text="게임 종료")

            await interaction.response.edit_message(
                embed=embed,
                view=self
            )
            return

        rps_streaks[user_id] = self.streak

        # 결과가 나온 뒤에만 계속하기/수령 버튼 활성화
        self.continue_game.disabled = False
        self.cash_out.disabled = self.pending_reward <= 0

        embed.add_field(
            name="❓ 계속하시겠습니까?\n",
            value=(
                "🎲 **계속하기:** 다음 판에 도전합니다.\n"
                "💰 **그만하고 수령:** 누적 보상을 받습니다."
            ),
            inline=False
        )

        await interaction.response.edit_message(
            embed=embed,
            view=self
        )

    # ==============================
    # 가위바위보 선택 버튼
    # ==============================

    @discord.ui.button(
        label="가위",
        emoji="✌️",
        style=discord.ButtonStyle.primary,
        row=0
    )
    async def scissors(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await self.play(interaction, "가위")

    @discord.ui.button(
        label="바위",
        emoji="✊",
        style=discord.ButtonStyle.primary,
        row=0
    )
    async def rock(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await self.play(interaction, "바위")

    @discord.ui.button(
        label="보",
        emoji="✋",
        style=discord.ButtonStyle.primary,
        row=0
    )
    async def paper(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await self.play(interaction, "보")

    # ==============================
    # 다음 판 진행 버튼
    # ==============================

    @discord.ui.button(
        label="계속하기",
        emoji="🎲",
        style=discord.ButtonStyle.success,
        row=1
    )
    async def continue_game(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not self.played:
            await interaction.response.send_message(
                "먼저 가위바위보를 진행해 주세요.",
                ephemeral=True
            )
            return

        if self.waiting_for_choice:
            await interaction.response.send_message(
                "이미 다음 판을 진행할 수 있는 상태입니다.",
                ephemeral=True
            )
            return

        self.waiting_for_choice = True

        # 다음 판을 위해 선택 버튼 활성화
        self.scissors.disabled = False
        self.rock.disabled = False
        self.paper.disabled = False

        self.continue_game.disabled = True
        self.cash_out.disabled = True

        embed = self.make_embed(
            "✊ 다음 판!",
            "가위·바위·보 중 하나를 선택하세요."
        )

        await interaction.response.edit_message(
            embed=embed,
            view=self
        )

    # ==============================
    # 누적 보상 수령 버튼
    # ==============================

    @discord.ui.button(
        label="그만하고 수령",
        emoji="💰",
        style=discord.ButtonStyle.danger,
        row=1
    )
    async def cash_out(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        user_id = str(self.player_id)

        if self.pending_reward <= 0:
            await interaction.response.send_message(
                "수령할 보상이 없습니다.",
                ephemeral=True
            )
            return

        reward = self.pending_reward

        # 보상 지급 및 저장
        balance = await db.add_money(user_id, reward)

        self.finished = True

        for button in self.children:
            button.disabled = True

        embed = discord.Embed(
            title="💰 보상 수령 완료!",
            description=(
                f"수령 보상: **+{reward:,} Byte**\n"
                f"현재 잔액: **{balance:,} Byte**\n"
                f"최종 연승: **{self.streak}연승**"
            ),
            color=discord.Color.green()
        )

        embed.set_footer(text="가위바위보 게임 종료")

        await interaction.response.edit_message(
            embed=embed,
            view=self
        )

    # ==============================
    # 시간 초과 처리
    # ==============================

    async def on_timeout(self):
        if self.finished:
            return

        self.finished = True

        for button in self.children:
            button.disabled = True

        # 시간 초과 시 미수령 보상은 지급하지 않음
        try:
            if hasattr(self, "message") and self.message:
                await self.message.edit(view=self)
        except discord.HTTPException:
            pass


# ==============================
# 가위바위보 명령어
# ==============================

@client.command(aliases=["가위바위보", "가위바위보게임", "ㄱㅇㅂㅇㅂ", "짱깨뽀"])
async def rps(ctx):
    user_id = str(ctx.author.id)

    # 새 게임 시작 쿨타임 확인
    remaining = 60 - (
        time.time() - rps_cooldowns.get(user_id, 0)
    )

    if remaining > 0:
        await ctx.send(
            f"⏳ 가위바위보 쿨타임이 **{math.ceil(remaining)}초** 남았습니다."
        )
        return

    view = RPSView(ctx.author.id)

    embed = discord.Embed(
        title="✊ 가위바위보",
        description=(
            "아래 버튼을 눌러 봇과 대결하세요!\n\n"
            "✌️ **가위** · ✊ **바위** · ✋ **보**\n\n"
        ),
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="🔥 현재 연승",
        value="**0연승**",
        inline=True
    )

    embed.add_field(
        name="💰 누적 보상",
        value="**0 Byte**",
        inline=True
    )

    embed.set_footer(
        text=f"{ctx.author.display_name}의 가위바위보"
    )

    view.message = await ctx.send(
        embed=embed,
        view=view
    )
