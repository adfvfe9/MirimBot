"""은행: 대출, 상환, 적금, 출금, 연체 처리

대출
- 한 사람이 동시에 빌릴 수 있는 원금은 최대 LOAN_LIMIT.
- 빌린 순간 이자 10% 가 붙는다. (1만 빌리면 1.1만을 갚아야 함)
- 24시간 안에 갚지 못하면 남은 상환액의 1.5배가 미납금(빚)이 된다.
- 미납금은 잔액에서 0 이 될 때까지 바로 징수되고, 모자란 만큼은 남아 있다가
  나중에 돈이 들어올 때마다 (기초수급, 주식 판매 등) 자동으로 징수된다. (schema.sql 트리거)

적금
- 하루 1.5% 단리, 최대 14일치까지만 이자가 붙는다. 원금은 최대 DEPOSIT_LIMIT.
"""
import datetime
import math

import discord
from discord import ButtonStyle
from discord.ext import tasks
from discord.ui import Button, Modal, TextInput, View

import database as db
from bot import client
from fmt import debt_line, num

# ───────────── 밸런스 설정 ─────────────
LOAN_LIMIT = 50000            # 동시에 빌릴 수 있는 원금 한도
LOAN_INTEREST = 0.10          # 대출 이자 10%
LOAN_DEADLINE_HOURS = 24      # 상환 기한
LOAN_PENALTY = 1.5            # 연체 시 남은 상환액 × 1.5 가 미납금으로

DEPOSIT_RATE = 0.015          # 적금 하루 이자 1.5% (단리)
DEPOSIT_MAX_DAYS = 14         # 이자가 붙는 최대 일수
DEPOSIT_LIMIT = 200000        # 적금 원금 한도

COLLECTION_INTERVAL_SECONDS = 60


def get_total_loan(loans):
    """아직 연체 처리되지 않은 대출의 남은 상환액 합계."""
    return sum(
        max(0.0, float(loan["amount"]))
        for loan in loans
        if not loan["collected"]
    )


def deposit_multiplier(start, now=None):
    """적금 원금에 곱할 값. 하루 1.5% 단리, 최대 14일."""
    if not start:
        return 1.0
    days = max(((now or db.now()) - start).days, 0)
    return 1 + DEPOSIT_RATE * min(days, DEPOSIT_MAX_DAYS)


def deposit_value(user, now=None):
    """적금의 현재 가치 (원금 + 이자)"""
    return user["deposit_amount"] * deposit_multiplier(user["deposit_start"], now)


def parse_amount(value):
    try:
        amount = float(value.replace(",", "").strip())

        if not math.isfinite(amount):
            return None

        return amount

    except (ValueError, AttributeError, TypeError):
        return None


# =========================
# 연체 처리
# =========================

async def collect_overdue(user_id):
    """
    기한(24시간)이 지난 대출을 연체 처리한다.

    남은 상환액 × 1.5 를 미납금에 더하고, 잔액에서 갚을 수 있는 만큼 바로 징수한다.
    이미 처리한 대출은 다시 처리하지 않는다.
    """
    now = db.now()
    messages = []

    async with db.user_tx(user_id) as conn:
        user = await db.get_user(user_id, conn)
        penalty_total = 0.0

        for loan in await db.get_loans(user_id, conn):
            if loan["collected"]:
                continue

            deadline = loan["taken_at"] + datetime.timedelta(hours=LOAN_DEADLINE_HOURS)
            if now < deadline:
                continue

            penalty = loan["amount"] * LOAN_PENALTY
            penalty_total += penalty

            await db.update_loan(
                loan["id"], conn,
                collected=True,
                collection_amount=penalty,
                collected_at=now,
            )
            messages.append(
                f"연체된 상환액 {num(loan['amount'])} Byte → 미납금 {num(penalty)} Byte"
            )

        if penalty_total > 0:
            # 미납금이 늘면 트리거가 잔액에서 바로 징수한다.
            await db.update_user(user_id, conn, unpaid_amount=user["unpaid_amount"] + penalty_total)
            after = await db.get_user(user_id, conn)
            collected = user["money"] - after["money"]
            messages.append(
                f"잔액에서 {num(collected)} Byte 징수, 남은 미납금 {num(after['unpaid_amount'])} Byte"
            )

    return messages


async def collect_all_overdue():
    """
    기한이 지난 대출이 있는 모든 유저를 처리한다.
    은행 명령어를 사용하지 않은 유저의 연체도 처리한다.
    """
    all_messages = []
    deadline = db.now() - datetime.timedelta(hours=LOAN_DEADLINE_HOURS)

    for user_id in await db.users_with_overdue_loans(deadline):
        messages = await collect_overdue(user_id)

        if messages:
            all_messages.append((user_id, messages))

    return all_messages


# =========================
# 자동 연체 처리 작업
# =========================

@tasks.loop(seconds=COLLECTION_INTERVAL_SECONDS)
async def bank_collection_loop():
    try:
        results = await collect_all_overdue()

        for user_id, messages in results:
            print(
                f"[은행 연체 처리] 유저 {user_id}: "
                + " / ".join(messages)
            )

    except Exception as e:
        print(f"[은행 연체 처리 오류] {e}")


@bank_collection_loop.before_loop
async def before_bank_collection_loop():
    await client.wait_until_ready()


@client.listen("on_ready")
async def start_bank_collection_loop():
    # 봇이 꺼져 있던 동안 생긴 연체도 루프 첫 실행 때 바로 처리된다.
    if not bank_collection_loop.is_running():
        bank_collection_loop.start()


# =========================
# 은행 명령어
# =========================

@client.command(aliases=["은행"])
async def bank(ctx):
    await ctx.message.delete()

    user_id = ctx.author.id

    # 명령어 실행 시에도 즉시 연체 확인
    collection_messages = await collect_overdue(user_id)

    user = await db.get_user(user_id)
    loans = await db.get_loans(user_id)

    total_owed = get_total_loan(loans)
    loan_room = max(0.0, LOAN_LIMIT - total_owed / (1 + LOAN_INTEREST))

    deadline_lines = []

    for index, loan in enumerate([l for l in loans if not l["collected"]], start=1):
        deadline = loan["taken_at"] + datetime.timedelta(hours=LOAN_DEADLINE_HOURS)
        remain = deadline - db.now()

        if remain.total_seconds() > 0:
            total_seconds = int(remain.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            deadline_text = f"{hours}시간 {minutes}분 남음"
        else:
            deadline_text = "연체 처리 대기"

        deadline_lines.append(
            f"대출 {index}: 갚을 돈 {num(loan['amount'])} Byte ({deadline_text})"
        )

    embed = discord.Embed(
        title="🏦 은행 시스템",
        description="버튼을 눌러 기능을 선택하세요.",
        color=discord.Color.teal()
    )

    embed.add_field(
        name="💳 갚을 대출금",
        value=f"{num(total_owed)} Byte\n(이자 {int(LOAN_INTEREST * 100)}% 포함)",
        inline=True
    )

    embed.add_field(
        name="🏦 추가 대출 가능",
        value=f"{num(loan_room)} Byte\n(한도 {num(LOAN_LIMIT)})",
        inline=True
    )

    embed.add_field(
        name="⚠️ 미납금",
        value=f"{num(user['unpaid_amount'])} Byte",
        inline=True
    )

    days = (
        min(max((db.now() - user["deposit_start"]).days, 0), DEPOSIT_MAX_DAYS)
        if user["deposit_start"] else 0
    )
    embed.add_field(
        name="💰 적금",
        value=(
            f"원금 {num(user['deposit_amount'])} Byte\n"
            f"현재 {num(deposit_value(user))} Byte ({days}일째, 하루 {num(DEPOSIT_RATE * 100)}%)"
        ),
        inline=False
    )

    embed.add_field(
        name=f"📆 상환 기한 ({LOAN_DEADLINE_HOURS}시간, 넘기면 {num(LOAN_PENALTY)}배가 미납금)",
        value=(
            "\n".join(deadline_lines)
            if deadline_lines
            else "진행 중인 대출 없음"
        ),
        inline=False
    )

    embed.set_footer(
        text=f"요청자: {ctx.author}",
        icon_url=ctx.author.avatar.url if ctx.author.avatar else None
    )

    if collection_messages:
        embed.add_field(
            name="🚨 연체 처리 결과",
            value="\n".join(collection_messages),
            inline=False
        )

    view = View(timeout=300)

    loan_button = Button(
        label="💵 대출",
        style=ButtonStyle.green
    )
    repay_button = Button(
        label="✅ 상환",
        style=ButtonStyle.primary
    )
    deposit_button = Button(
        label="💰 적금",
        style=ButtonStyle.secondary
    )
    withdraw_button = Button(
        label="💳 출금",
        style=ButtonStyle.red
    )

    async def loan_callback(interaction):
        if interaction.user.id != user_id:
            return await interaction.response.send_message(
                "이 버튼은 당신의 것이 아닙니다.",
                ephemeral=True
            )

        await interaction.response.send_modal(LoanModal(user_id))

    async def repay_callback(interaction):
        if interaction.user.id != user_id:
            return await interaction.response.send_message(
                "이 버튼은 당신의 것이 아닙니다.",
                ephemeral=True
            )

        await interaction.response.send_modal(RepayModal(user_id))

    async def deposit_callback(interaction):
        if interaction.user.id != user_id:
            return await interaction.response.send_message(
                "이 버튼은 당신의 것이 아닙니다.",
                ephemeral=True
            )

        await interaction.response.send_modal(DepositModal(user_id))

    async def withdraw_callback(interaction):
        if interaction.user.id != user_id:
            return await interaction.response.send_message(
                "이 버튼은 당신의 것이 아닙니다.",
                ephemeral=True
            )

        await interaction.response.send_modal(WithdrawModal(user_id))

    loan_button.callback = loan_callback
    repay_button.callback = repay_callback
    deposit_button.callback = deposit_callback
    withdraw_button.callback = withdraw_callback

    view.add_item(loan_button)
    view.add_item(repay_button)
    view.add_item(deposit_button)
    view.add_item(withdraw_button)

    await ctx.send(embed=embed, view=view)


# =========================
# 대출
# =========================

class LoanModal(Modal, title="💵 대출 금액 입력"):
    amount = TextInput(
        label="대출할 금액 (이자 10%, 24시간 안에 상환)",
        placeholder="숫자만 입력",
        required=True
    )

    def __init__(self, user_id):
        super().__init__()
        self.user_id = user_id

    async def on_submit(self, interaction):
        amount = parse_amount(self.amount.value)

        if amount is None or amount <= 0:
            return await interaction.response.send_message(
                "❌ 올바른 대출 금액을 입력하세요.",
                ephemeral=True
            )

        # 신청자 본인의 연체 대출부터 처리
        await collect_overdue(self.user_id)

        error = None
        async with db.user_tx(self.user_id) as conn:
            user = await db.get_user(self.user_id, conn)
            loans = await db.get_loans(self.user_id, conn)
            borrowed = get_total_loan(loans) / (1 + LOAN_INTEREST)
            room = max(0.0, LOAN_LIMIT - borrowed)

            if user["unpaid_amount"] > 0:
                error = "❌ 미납금이 있으면 대출할 수 없어요. 미납금을 먼저 갚아주세요."
            elif amount > room:
                error = (
                    f"❌ 대출 한도를 초과했습니다.\n"
                    f"대출 한도: {num(LOAN_LIMIT)} Byte\n"
                    f"추가 대출 가능 금액: {num(room)} Byte"
                )
            else:
                owed = amount * (1 + LOAN_INTEREST)
                await db.add_loan(self.user_id, owed, db.now(), conn)
                await db.receive(self.user_id, amount, conn)

        if error:
            return await interaction.response.send_message(error, ephemeral=True)

        await interaction.response.send_message(
            f"✅ {num(amount)} Byte 대출 완료!\n"
            f"갚아야 할 돈: **{num(owed)} Byte** (이자 {int(LOAN_INTEREST * 100)}%)\n"
            f"⏰ {LOAN_DEADLINE_HOURS}시간 안에 갚지 않으면 "
            f"{num(owed * LOAN_PENALTY)} Byte가 미납금이 되어 돈이 들어올 때마다 징수됩니다.",
            ephemeral=True
        )


# =========================
# 상환
# =========================

class RepayModal(Modal, title="✅ 상환 금액 입력"):
    amount = TextInput(
        label="상환할 금액 (전액은 '전액')",
        placeholder="예: 1000 또는 전액",
        required=True
    )

    def __init__(self, user_id):
        super().__init__()
        self.user_id = user_id

    async def on_submit(self, interaction):
        raw = self.amount.value.strip()
        error = None

        async with db.user_tx(self.user_id) as conn:
            balance = await db.get_money(self.user_id, conn)
            loans = [l for l in await db.get_loans(self.user_id, conn) if not l["collected"]]
            total_loan = get_total_loan(loans)

            if raw.lower() in ("전액", "전체", "all", "max"):
                amount = total_loan
            else:
                amount = parse_amount(raw)

            if amount is None or amount <= 0:
                error = "❌ 올바른 상환 금액을 입력하세요."
            elif total_loan <= 0:
                error = "❌ 상환할 대출이 없습니다."
            elif amount > total_loan:
                error = f"❌ 갚을 대출금은 {num(total_loan)} Byte입니다."
            elif amount > balance:
                error = "❌ 잔액이 부족합니다."
            else:
                remaining = amount

                # 오래된 대출부터 상환
                for loan in loans:
                    if remaining <= 0:
                        break

                    paid = min(loan["amount"], remaining)
                    loan["amount"] -= paid
                    remaining -= paid

                    # 다 갚은 대출은 삭제
                    if loan["amount"] > 0.001:
                        await db.update_loan(loan["id"], conn, amount=loan["amount"])
                    else:
                        await db.delete_loan(loan["id"], conn)

                await db.update_user(self.user_id, conn, money=balance - amount)
                remaining_loan = get_total_loan([l for l in loans if l["amount"] > 0.001])

        if error:
            return await interaction.response.send_message(error, ephemeral=True)

        await interaction.response.send_message(
            f"✅ {num(amount)} Byte 상환 완료!\n"
            f"남은 대출금: {num(remaining_loan)} Byte",
            ephemeral=True
        )


# =========================
# 적금
# =========================

class DepositModal(Modal, title="💰 적금 금액 입력"):
    amount = TextInput(
        label="적금할 금액 (하루 1.5%, 최대 14일)",
        placeholder="숫자만 입력",
        required=True
    )

    def __init__(self, user_id):
        super().__init__()
        self.user_id = user_id

    async def on_submit(self, interaction):
        amount = parse_amount(self.amount.value)

        if amount is None or amount <= 0:
            return await interaction.response.send_message(
                "❌ 올바른 적금 금액을 입력하세요.",
                ephemeral=True
            )

        error = None
        async with db.user_tx(self.user_id) as conn:
            user = await db.get_user(self.user_id, conn)
            # 지금까지 붙은 이자를 원금에 합치고, 오늘부터 다시 센다.
            new_principal = deposit_value(user) + amount

            if user["money"] < amount:
                error = "❌ 잔액이 부족합니다."
            elif new_principal > DEPOSIT_LIMIT:
                error = (
                    f"❌ 적금 원금은 최대 {num(DEPOSIT_LIMIT)} Byte까지예요.\n"
                    f"더 넣을 수 있는 금액: {num(max(0, DEPOSIT_LIMIT - deposit_value(user)))} Byte"
                )
            else:
                await db.update_user(
                    self.user_id, conn,
                    money=user["money"] - amount,
                    deposit_amount=new_principal,
                    deposit_start=db.now(),
                )

        if error:
            return await interaction.response.send_message(error, ephemeral=True)

        await interaction.response.send_message(
            f"✅ {num(amount)} Byte 적금 완료!\n"
            f"현재 적금 원금: {num(new_principal)} Byte\n"
            f"(그동안 붙은 이자는 원금에 합쳐지고, 오늘부터 다시 하루 {num(DEPOSIT_RATE * 100)}%씩 붙어요)",
            ephemeral=True
        )


# =========================
# 적금 부분 출금 / 전액 출금
# =========================

class WithdrawModal(Modal, title="💳 적금 출금"):
    amount = TextInput(
        label="출금할 금액 (전액은 '전액')",
        placeholder="예: 1000 또는 전액",
        required=True
    )

    def __init__(self, user_id):
        super().__init__()
        self.user_id = user_id

    async def on_submit(self, interaction):
        error = None

        async with db.user_tx(self.user_id) as conn:
            user = await db.get_user(self.user_id, conn)
            total_value = deposit_value(user)

            if user["deposit_amount"] <= 0:
                error = "❌ 적금이 없습니다."
            else:
                raw_amount = self.amount.value.strip()

                if raw_amount.lower() in ("전액", "전체", "all", "max"):
                    withdraw_amount = total_value
                else:
                    withdraw_amount = parse_amount(raw_amount)

                    if withdraw_amount is None or withdraw_amount <= 0:
                        error = "❌ 올바른 출금 금액을 입력하세요."
                    elif withdraw_amount > total_value:
                        error = f"❌ 출금 가능 금액은 {num(total_value)} Byte입니다."

            if error is None:
                # 남은 금액(이자 포함)이 새 원금이 되고, 오늘부터 다시 센다.
                remaining = total_value - withdraw_amount
                if remaining < 0.01:
                    await db.update_user(self.user_id, conn, deposit_amount=0, deposit_start=None)
                    remaining = 0.0
                else:
                    await db.update_user(
                        self.user_id, conn, deposit_amount=remaining, deposit_start=db.now()
                    )
                result = await db.receive(self.user_id, withdraw_amount, conn)

        if error:
            return await interaction.response.send_message(error, ephemeral=True)

        await interaction.response.send_message(
            f"✅ {num(withdraw_amount)} Byte 출금 완료!\n"
            f"남은 적금: {num(remaining)} Byte"
            + debt_line(result["collected"]),
            ephemeral=True
        )
