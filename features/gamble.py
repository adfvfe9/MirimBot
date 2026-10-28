"""도박: 도박, 도박올인, 도박랭킹, 가위바위보"""
import math
import random
import time

import discord

import database as db
import respond
from bot import client
from features import abilities, digest
from fmt import debt_line, num


# ───────────── 도박 ─────────────
GAMBLE_COOLDOWN = 10      # 초
GAMBLE_MAX_BET = 100000    # 1회 최대 판돈 (%도박올인 도 이 금액까지만, 🎲 능력만큼 늘어난다)

# (배율, 확률 %) — 판돈 × 배율 을 돌려받는다. 기대값 = 0.95 (평균적으로 판돈의 5% 손해)
# 아무리 져도 판돈만 잃는다. (빚이 생기지 않음)
GAMBLE_TABLE = [
    (0.0, 50),   # 꽝: 판돈을 잃음
    (1.5, 30),
    (2.0, 14),
    (3.0, 5),
    (7.0, 1),    # 잭팟
]


async def max_bet(user_id, conn=None):
    """이 사람의 1회 최대 판돈 (🎲 능력 포함)"""
    return GAMBLE_MAX_BET * (1 + await abilities.total(user_id, "gamble_max", conn) / 100)


async def play_gamble(user_id, amount=None):
    """도박 1회 처리. amount 가 None 이면 올인 (최대 판돈까지).
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
                remain = int(GAMBLE_COOLDOWN - elapsed) + 1
                return f"⏳ 아직 도박할 수 없어요! 다시 시도하려면 **{remain}초** 기다려주세요."

        limit = await max_bet(user_id, conn)
        if amount is None:
            amount = min(current_money, limit)  # 올인!
        elif amount <= 0:
            return "❌ 1 이상의 금액을 입력해주세요."
        elif amount > limit:
            return f"❌ 한 번에 걸 수 있는 최대 금액은 **{num(limit)} byte**입니다."
        elif current_money < amount:
            return "❌ 잔액이 부족합니다."

        multiplier = random.choices(
            [m for m, _ in GAMBLE_TABLE], weights=[w for _, w in GAMBLE_TABLE]
        )[0]
        payout = amount * multiplier
        refund = 0.0
        if multiplier == 0:
            # 🎰 도박 꽝 환급 (기대값 0.95 + 0.5 × 환급%. 10%를 넘으면 도박이 이득이 된다)
            refund = amount * await abilities.total(user_id, "gamble_refund", conn) / 100
            payout = refund
        net_change = payout - amount
        new_balance = current_money + net_change

        # 잔액, 도박 통계, 쿨타임을 한 번에 저장
        await db.update_user(
            user_id, conn,
            money=new_balance,
            gamble_net=user["gamble_net"] + net_change,
            gamble_last_at=now,
        )
        await db.log_money(user_id, "gamble", net_change, f"bet {amount} x{multiplier}", conn)

    if multiplier >= 7:
        digest.jackpot(user_id, amount, payout)     # 🎰 소식 채널에 자랑

    return {
        "amount": amount,
        "multiplier": multiplier,
        "payout": payout,
        "refund": refund,
        "net_change": net_change,
        "balance": new_balance,
        "max_bet": limit,
    }


def gamble_odds_text():
    return " / ".join(
        f"{'꽝' if m == 0 else f'{num(m)}배'} {w}%" for m, w in GAMBLE_TABLE
    )


def gamble_embed(result, title, description):
    multiplier = result["multiplier"]
    net_change = result["net_change"]

    # 결과 메시지
    color = 0x2ecc71 if net_change > 0 else 0xe74c3c
    outcome = (
        "🎉 잭팟!" if multiplier >= 7 else
        "👍 성공!" if net_change > 0 else
        "😢 꽝..."
    )
    net_symbol = "📈" if net_change > 0 else "📉"

    embed = discord.Embed(
        title=title,
        description=description,
        color=color
    )
    embed.add_field(
        name="배율",
        value=(f"꽝 (🎰 환급 {num(result['refund'])})" if result.get("refund") else "꽝") if multiplier == 0 else f"{num(multiplier)}배",
        inline=True
    )
    embed.add_field(name="돌려받은 금액", value=f"{num(result['payout'])} byte", inline=True)
    embed.add_field(name="순이익", value=f"{net_symbol} {num(net_change, sign=True)} byte", inline=True)
    embed.add_field(name="현재 잔액", value=f"{num(result['balance'])} byte", inline=False)
    embed.set_footer(text=f"{outcome}  |  확률: {gamble_odds_text()}")
    return embed


@client.command(aliases=["도박"])
async def gamble(ctx, amount: int):
    respond.delete_soon(ctx.message)

    result = await play_gamble(ctx.author.id, amount)
    if isinstance(result, str):
        await ctx.send(result)
        return

    await ctx.send(embed=gamble_embed(
        result, "🎲 도박 결과", f"{ctx.author.mention}님이 **{num(amount)} byte**를 걸었습니다!"
    ))


@client.command(aliases=["도박랭킹"])
async def gamble_rank(ctx):
    respond.delete_soon(ctx.message)
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
        embed.add_field(name=f"{i}위: {name}", value=f"{symbol} {num(profit, sign=True)} byte", inline=False)

    await ctx.send(embed=embed)


@client.command(aliases=["도박올인"])
async def gamble_allin(ctx):
    respond.delete_soon(ctx.message)

    result = await play_gamble(ctx.author.id)
    if isinstance(result, str):
        await ctx.send(result)
        return

    await ctx.send(embed=gamble_embed(
        result, "🎲 도박 올인 결과",
        f"{ctx.author.mention}님이 **{num(result['amount'])} byte**를 올인했습니다! "
        f"(최대 {num(result['max_bet'])} byte)"
    ))


# ───────────── 가위바위보 ─────────────
# 이기면 보상이 2배씩 커진다: 5천 → 1만 → 2만 → 4만 ... (k번째 승리 보상 = 5,000 × 2^(k-1))
# 지면 누적 보상을 전부 잃는다. 어디서 멈춰도 기대값은 비슷해서 "고 or 스탑" 배짱 싸움이 된다.
# (무승부는 다시 하니까 한 판의 기대값은 RPS_BASE_REWARD 보다 조금 작다. ✊ 부활 능력이 높으면 이보다 커진다)
# 하루 30판을 다 하는 사람이 없어서 5판으로 줄이고 보상을 5배로 (1천 → 5천)
RPS_BASE_REWARD = 5000
RPS_MAX_STREAK = 10       # 10연승하면 자동으로 수령하고 끝 (누적 5,115,000)
RPS_DAILY_LIMIT = 5       # 하루 최대 판수 (✌️ 능력만큼 늘어난다)
RPS_COOLDOWN = 60         # 판 사이 쿨타임 (초)

rps_streaks = {}
rps_cooldowns = {}


def rps_reward(streak):
    """streak 번째 승리의 보상"""
    return RPS_BASE_REWARD * 2 ** (streak - 1)


async def rps_daily_limit(user_id, conn=None):
    """이 사람의 가위바위보 하루 판수 (✌️ 능력 포함)"""
    return RPS_DAILY_LIMIT + int(await abilities.total(user_id, "rps_games", conn))


def rps_limit_text(limit):
    return f"❌ 오늘은 가위바위보를 {limit}판 모두 했어요. 내일 다시 도전하세요!"


async def start_rps_game(user_id):
    """오늘 판수를 하나 쓴다. 한도를 넘었으면 False."""
    today = db.today()
    async with db.user_tx(user_id) as conn:
        user = await db.get_user(user_id, conn)
        count = user["rps_count"] if user["rps_date"] == today else 0
        if count >= await rps_daily_limit(user_id, conn):
            return False
        await db.update_user(user_id, conn, rps_date=today, rps_count=count + 1)
        return True


async def rps_games_left(user_id):
    user = await db.get_user(user_id)
    count = user["rps_count"] if user["rps_date"] == db.today() else 0
    return await rps_daily_limit(user_id) - count


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
            await respond.reply(interaction,
                "❌ 다른 사람의 가위바위보 게임입니다! "
                "본인이 시작한 게임의 버튼만 누를 수 있습니다.",
                ephemeral=True
            )
            return False

        # 종료된 게임의 버튼 클릭 차단
        if self.finished:
            await respond.reply(interaction,
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
            value=f"**{num(self.pending_reward)} Byte**",
            inline=True
        )

        next_reward = rps_reward(self.streak + 1)

        embed.add_field(
            name="🎁 다음 승리 보상",
            value=f"**+{num(next_reward)} Byte** (최대 {RPS_MAX_STREAK}연승)",
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
        await respond.defer(interaction)
        if not self.waiting_for_choice:
            await respond.reply(interaction,
                "먼저 계속하기 버튼을 눌러 다음 판을 시작해 주세요.",
                ephemeral=True
            )
            return

        user_id = str(self.player_id)
        now = time.time()

        # 첫 판 시작 시에만 쿨타임 / 하루 판수 검사
        if not self.played:
            last_play = rps_cooldowns.get(user_id, 0)
            remaining = RPS_COOLDOWN - (now - last_play)

            if remaining > 0:
                await respond.reply(interaction,
                    f"⏳ 쿨타임이 **{math.ceil(remaining)}초** 남았습니다.",
                    ephemeral=True
                )
                return

            if not await start_rps_game(self.player_id):
                await respond.reply(interaction,
                    rps_limit_text(await rps_daily_limit(self.player_id)),
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

            reward = rps_reward(self.streak)
            self.pending_reward += reward

            embed.color = discord.Color.green()

            embed.add_field(
                name="🎉 승리!",
                value=(
                    f"이번 승리 보상: **{num(reward)} Byte**\n"
                    f"누적 보상: **{num(self.pending_reward)} Byte**"
                ),
                inline=False
            )

            # 최대 연승에 도달하면 자동으로 수령하고 끝
            if self.streak >= RPS_MAX_STREAK:
                await self.pay_out(interaction, title=f"🏆 {RPS_MAX_STREAK}연승 달성! 자동 수령")
                return

        # ✊ 가위바위보 부활: 졌지만 확률로 무효 (무승부처럼 연승과 누적 보상 유지)
        elif abilities.chance(await abilities.total(self.player_id, "rps_revive")):
            embed.color = discord.Color.gold()
            embed.add_field(
                name="✊ 부활!",
                value="졌지만 **가위바위보 부활** 능력이 발동해서 무효가 됐어요. 연승과 누적 보상이 유지됩니다.",
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

            await respond.edit(interaction,
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

        await respond.edit(interaction,
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
        await respond.defer(interaction)
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
        await respond.defer(interaction)
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
        await respond.defer(interaction)
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
        await respond.defer(interaction)
        if not self.played:
            await respond.reply(interaction,
                "먼저 가위바위보를 진행해 주세요.",
                ephemeral=True
            )
            return

        if self.waiting_for_choice:
            await respond.reply(interaction,
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

        await respond.edit(interaction,
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
        await respond.defer(interaction)
        if self.pending_reward <= 0:
            await respond.reply(interaction,
                "수령할 보상이 없습니다.",
                ephemeral=True
            )
            return

        await self.pay_out(interaction)

    async def pay_out(self, interaction, title="💰 보상 수령 완료!"):
        await respond.defer(interaction)
        reward = self.pending_reward
        self.finished = True

        # 보상 지급 및 저장 (미납금이 있으면 자동 징수)
        result = await db.receive(self.player_id, reward)
        await db.log_money(self.player_id, "rps", reward, f"streak {self.streak}")
        if reward > 0:
            digest.rps_streak(self.player_id, self.streak, reward)

        for button in self.children:
            button.disabled = True

        embed = discord.Embed(
            title=title,
            description=(
                f"수령 보상: **+{num(reward)} Byte**\n"
                f"현재 잔액: **{num(result['balance'])} Byte**\n"
                f"최종 연승: **{self.streak}연승**"
                + debt_line(result["collected"])
            ),
            color=discord.Color.green()
        )

        embed.set_footer(text="가위바위보 게임 종료")

        await respond.edit(interaction,
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
    remaining = RPS_COOLDOWN - (
        time.time() - rps_cooldowns.get(user_id, 0)
    )

    if remaining > 0:
        await ctx.send(
            f"⏳ 가위바위보 쿨타임이 **{math.ceil(remaining)}초** 남았습니다."
        )
        return

    games_left = await rps_games_left(ctx.author.id)
    if games_left <= 0:
        await ctx.send(rps_limit_text(await rps_daily_limit(ctx.author.id)))
        return

    view = RPSView(ctx.author.id)

    embed = discord.Embed(
        title="✊ 가위바위보",
        description=(
            "아래 버튼을 눌러 봇과 대결하세요!\n\n"
            "✌️ **가위** · ✊ **바위** · ✋ **보**\n\n"
            f"이길 때마다 보상이 2배! (5천 → 1만 → 2만 …, 최대 {RPS_MAX_STREAK}연승)\n"
            "지면 누적 보상을 전부 잃어요. 언제 멈출지가 승부!"
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
        text=f"{ctx.author.display_name}의 가위바위보  |  오늘 남은 판수: {games_left}판"
    )

    view.message = await ctx.send(
        embed=embed,
        view=view
    )
