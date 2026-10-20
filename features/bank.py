"""은행: 대출, 상환, 적금, 출금, 24시간 강제징수"""
import datetime
import math

import discord
from discord import ButtonStyle
from discord.ext import tasks
from discord.ui import Button, Modal, TextInput, View

import database as db
from bot import client


# =========================
# 은행 (대출 / 상환 / 적금 / 출금)
# =========================

LOAN_DEADLINE_HOURS = 24
COLLECTION_INTERVAL_SECONDS = 60


def get_total_loan(loans):
    """아직 강제징수되지 않은 대출의 남은 원금 합계.
    강제징수가 끝난 대출은 정산이 끝난 것이라 대출금/한도/상환 대상에서 빠진다."""
    return sum(
        max(0.0, float(loan["amount"]))
        for loan in loans
        if not loan["collected"]
    )


def parse_amount(value):
    try:
        amount = float(value.replace(",", "").strip())

        if not math.isfinite(amount):
            return None

        return amount

    except (ValueError, AttributeError, TypeError):
        return None


# =========================
# 강제징수 처리
# =========================

async def collect_overdue(user_id):
    """
    대출별 24시간 경과 여부를 확인한다.

    강제징수액 = 대출 원금의 제곱
    잔액이 부족하면 보유 잔액을 징수하고 부족분을 미납금에 누적한다.
    이미 처리한 대출은 다시 징수하지 않는다.
    """
    now = db.now()
    messages = []

    async with db.user_tx(user_id) as conn:
        user = await db.get_user(user_id, conn)
        balance = user["money"]
        unpaid_total = user["unpaid_amount"]
        changed = False

        for loan in await db.get_loans(user_id, conn):
            if loan["collected"]:
                continue

            deadline = loan["taken_at"] + datetime.timedelta(
                hours=LOAN_DEADLINE_HOURS
            )

            if now < deadline:
                continue

            principal = loan["amount"]

            if principal <= 0:
                await db.update_loan(loan["id"], conn, collected=True)
                continue

            collection_amount = principal ** 2

            # 징수 가능한 금액은 현재 보유 잔액까지
            collected_now = min(max(balance, 0.0), collection_amount)
            balance -= collected_now

            unpaid = max(0.0, collection_amount - collected_now)
            unpaid_total += unpaid

            # 중복 징수 방지
            await db.update_loan(
                loan["id"], conn,
                collected=True,
                collection_amount=collection_amount,
                collected_amount=collected_now,
                unpaid_from_loan=unpaid,
                collected_at=now,
            )

            changed = True

            message = (
                f"대출 원금 {principal:.2f} Byte: "
                f"징수 {collected_now:.2f} Byte"
            )

            if unpaid > 0:
                message += f", 미납 {unpaid:.2f} Byte"

            messages.append(message)

        if changed:
            await db.update_user(
                user_id, conn,
                money=round(balance, 2),
                unpaid_amount=unpaid_total,
            )

    return messages


async def collect_all_overdue():
    """
    기한이 지난 대출이 있는 모든 유저를 검사한다.
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
# 자동 강제징수 작업
# =========================

@tasks.loop(seconds=COLLECTION_INTERVAL_SECONDS)
async def bank_collection_loop():
    try:
        results = await collect_all_overdue()

        for user_id, messages in results:
            print(
                f"[은행 강제징수] 유저 {user_id}: "
                + " / ".join(messages)
            )

    except Exception as e:
        print(f"[은행 강제징수 오류] {e}")


@bank_collection_loop.before_loop
async def before_bank_collection_loop():
    await client.wait_until_ready()


@client.listen("on_ready")
async def start_bank_collection_loop():
    # 봇이 꺼져 있던 동안 발생한 연체도 루프 첫 실행 때 바로 처리된다.
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

    total_loan = get_total_loan(loans)
    average_balance = await db.average_positive_money()
    max_loan = average_balance

    deadline_lines = []

    for index, loan in enumerate(loans, start=1):
        if loan["collected"]:
            continue

        deadline = loan["taken_at"] + datetime.timedelta(
            hours=LOAN_DEADLINE_HOURS
        )

        remain = deadline - db.now()

        if remain.total_seconds() > 0:
            total_seconds = int(remain.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            deadline_text = f"{hours}시간 {minutes}분 남음"
        else:
            deadline_text = "강제징수 대기"

        deadline_lines.append(
            f"대출 {index}: {float(loan['amount']):.2f} Byte "
            f"({deadline_text})"
        )

    embed = discord.Embed(
        title="🏦 은행 시스템",
        description="버튼을 눌러 기능을 선택하세요.",
        color=discord.Color.teal()
    )

    embed.add_field(
        name="💳 총 대출금",
        value=f"{total_loan:.2f} Byte",
        inline=True
    )

    embed.add_field(
        name="💰 적금 원금",
        value=f"{user['deposit_amount']:.2f} Byte",
        inline=True
    )

    embed.add_field(
        name="⚠️ 미납 강제징수액",
        value=f"{user['unpaid_amount']:.2f} Byte",
        inline=True
    )

    embed.add_field(
        name="🏦 최대 총대출 한도",
        value=f"{max_loan:.2f} Byte",
        inline=True
    )

    embed.add_field(
        name="📆 대출별 강제징수 기한",
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
            name="🚨 강제징수 결과",
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
        label="대출할 금액",
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

        # 총대출금 기준으로 한도 검사
        average_balance = await db.average_positive_money()
        max_total_loan = average_balance

        async with db.user_tx(self.user_id) as conn:
            loans = await db.get_loans(self.user_id, conn)
            current_total_loan = get_total_loan(loans)
            remaining_limit = max(
                0.0,
                max_total_loan - current_total_loan
            )

            approved = amount <= remaining_limit
            if approved:
                await db.add_loan(self.user_id, amount, db.now(), conn)
                await db.add_money(self.user_id, amount, conn)

        if not approved:
            return await interaction.response.send_message(
                f"❌ 대출 한도를 초과했습니다.\n"
                f"서버 평균 잔액: {average_balance:.2f} Byte\n"
                f"현재 총대출금: {current_total_loan:.2f} Byte\n"
                f"최대 총대출 한도: {max_total_loan:.2f} Byte\n"
                f"추가 대출 가능 금액: {remaining_limit:.2f} Byte",
                ephemeral=True
            )

        await interaction.response.send_message(
            f"✅ {amount:.2f} Byte 대출 완료!\n"
            f"현재 총대출금: {current_total_loan + amount:.2f} Byte\n"
            f"최대 총대출 한도: {max_total_loan:.2f} Byte\n"
            f"대출일로부터 24시간 후 강제징수됩니다.",
            ephemeral=True
        )


# =========================
# 상환
# =========================

class RepayModal(Modal, title="✅ 상환 금액 입력"):
    amount = TextInput(
        label="상환할 금액",
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
                "❌ 올바른 상환 금액을 입력하세요.",
                ephemeral=True
            )

        error = None

        async with db.user_tx(self.user_id) as conn:
            balance = await db.get_money(self.user_id, conn)
            loans = await db.get_loans(self.user_id, conn)
            total_loan = get_total_loan(loans)

            if total_loan <= 0:
                error = "❌ 상환할 대출이 없습니다."
            elif amount > total_loan:
                error = f"❌ 총 대출금은 {total_loan:.2f} Byte입니다."
            elif amount > balance:
                error = "❌ 잔액이 부족합니다."
            else:
                remaining = amount

                # 오래된 대출부터 상환 (강제징수된 대출은 제외)
                for loan in loans:
                    if remaining <= 0:
                        break

                    if loan["collected"]:
                        continue

                    loan_amount = float(loan["amount"])
                    paid = min(loan_amount, remaining)

                    loan["amount"] = round(loan_amount - paid, 2)
                    remaining = round(remaining - paid, 2)

                    # 다 갚은 대출은 삭제
                    if loan["amount"] > 0.001:
                        await db.update_loan(loan["id"], conn, amount=loan["amount"])
                    else:
                        await db.delete_loan(loan["id"], conn)

                await db.update_user(self.user_id, conn, money=round(balance - amount, 2))
                remaining_loan = get_total_loan(
                    [loan for loan in loans if loan["amount"] > 0.001]
                )

        if error:
            return await interaction.response.send_message(error, ephemeral=True)

        await interaction.response.send_message(
            f"✅ {amount:.2f} Byte 상환 완료!\n"
            f"남은 대출금: {remaining_loan:.2f} Byte",
            ephemeral=True
        )


# =========================
# 적금
# =========================

class DepositModal(Modal, title="💰 적금 금액 입력"):
    amount = TextInput(
        label="적금할 금액",
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

        async with db.user_tx(self.user_id) as conn:
            user = await db.get_user(self.user_id, conn)
            balance = user["money"]
            enough = balance >= amount

            if enough:
                deposit_start = user["deposit_start"]
                if user["deposit_amount"] <= 0:
                    deposit_start = db.now()

                deposit_amount = round(user["deposit_amount"] + amount, 2)

                await db.update_user(
                    self.user_id, conn,
                    money=round(balance - amount, 2),
                    deposit_amount=deposit_amount,
                    deposit_start=deposit_start,
                )

        if not enough:
            return await interaction.response.send_message(
                "❌ 잔액이 부족합니다.",
                ephemeral=True
            )

        await interaction.response.send_message(
            f"✅ {amount:.2f} Byte 적금 완료!\n"
            f"현재 적금 원금: {deposit_amount:.2f} Byte",
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
            principal = user["deposit_amount"]

            if principal <= 0:
                error = "❌ 적금이 없습니다."
            else:
                now = db.now()
                start = user["deposit_start"]
                days = max((now - start).days, 0) if start else 0

                # 기존 일복리 10% 유지
                multiplier = 1.1 ** days
                total_value = principal * multiplier

                raw_amount = self.amount.value.strip()

                if raw_amount.lower() in ("전액", "전체", "all", "max"):
                    withdraw_amount = total_value
                else:
                    withdraw_amount = parse_amount(raw_amount)

                    if withdraw_amount is None or withdraw_amount <= 0:
                        error = "❌ 올바른 출금 금액을 입력하세요."
                    elif withdraw_amount > total_value:
                        error = f"❌ 출금 가능 금액은 {total_value:.2f} Byte입니다."

            if error is None:
                withdraw_amount = round(withdraw_amount, 2)

                # 출금액에 비례해 적금 원금 차감
                principal_to_remove = min(
                    principal,
                    withdraw_amount / multiplier
                )

                remaining_principal = max(
                    0.0,
                    principal - principal_to_remove
                )

                if remaining_principal < 0.01:
                    deposit_amount = 0.0
                    deposit_start = None
                else:
                    deposit_amount = round(remaining_principal, 2)

                    # 잔여 적금의 이자는 출금 시점부터 다시 계산
                    deposit_start = now

                await db.update_user(
                    self.user_id, conn,
                    money=round(user["money"] + withdraw_amount, 2),
                    deposit_amount=deposit_amount,
                    deposit_start=deposit_start,
                )

        if error:
            return await interaction.response.send_message(error, ephemeral=True)

        await interaction.response.send_message(
            f"✅ {withdraw_amount:.2f} Byte 출금 완료!\n"
            f"남은 적금 원금: {deposit_amount:.2f} Byte",
            ephemeral=True
        )
