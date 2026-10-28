"""숫자 표시용 도우미.

DB 에는 계산한 값을 그대로 저장하고, 화면에 보여줄 때만 이 함수로 정리한다.
- 소수점은 최대 2자리까지, 그 아래는 버린다(내림). 예: 12.349 → 12.34
- 끝의 0 은 지운다. 예: 100.00 → 100, 12.50 → 12.5
- 천 단위 쉼표를 넣는다. 예: 1234567.8 → 1,234,567.8

    from fmt import num
    f"{num(balance)} byte"          → "1,234.5 byte"
    f"{num(profit, sign=True)} byte" → "+1,234.5 byte" / "-12 byte"
    f"{num(rate, sign=True)}%"       → "+3.14%"

명령어로 받은 금액 / 수량 읽기는 parse_amount 와 Amount 를 쓴다.
    async def gamble(ctx, amount: Amount):   %도박 5만 · %도박 1,000 · %도박 올인 · %도박 절반
"""
import math
import re
from decimal import ROUND_DOWN, Decimal

from discord.ext import commands


def num(value, sign: bool = False) -> str:
    if value is None:
        value = 0
    if isinstance(value, float):
        value = Decimal(repr(value))
    d = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    if d == 0:
        d = Decimal(0)  # -0.00 → 0

    text = f"{d:,.2f}".rstrip("0").rstrip(".")
    if sign and d > 0:
        text = "+" + text
    return text


def debt_line(collected) -> str:
    """돈을 받았는데 미납금으로 일부가 징수됐을 때 메시지 끝에 붙일 한 줄."""
    if collected and collected > 0:
        return f"\n🧾 미납금 **{num(collected)} byte**가 자동으로 징수되었습니다."
    return ""


def floor2(value) -> float:
    """계산에 쓸 값을 소수 2자리로 내림한다. (예: 판매 금액, 수수료)"""
    if isinstance(value, float):
        value = Decimal(repr(value))
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_DOWN))


# ───────────── 금액 / 수량 읽기 ─────────────
UNITS = {"": 1, "천": 1_000, "만": 10_000, "억": 100_000_000, "k": 1_000}
_AMOUNT = re.compile(r"(\d+(?:\.\d+)?)(천|만|억|k)?")

ALL = "all"       # 올인 / 최대 / 전부: 할 수 있는 만큼 다
HALF = "half"     # 절반: 할 수 있는 만큼의 절반
ALL_WORDS = {"올인", "최대", "전부", "전체", "다", "all", "max"}
HALF_WORDS = {"절반", "반", "half"}


def parse_amount(value):
    """'1,000' · '5만' · '1.5만' · '3천' · '2억' · '10k' → 숫자. 못 읽으면 None"""
    text = str(value).replace(",", "").replace(" ", "").lower()
    match = _AMOUNT.fullmatch(text)
    if not match:
        return None
    amount = float(match[1]) * UNITS[match[2] or ""]
    return amount if math.isfinite(amount) else None


class Amount(commands.Converter):
    """%명령어 인자로 받는 금액 / 수량. 정수 또는 ALL / HALF 를 돌려준다. (resolve_amount 로 실제 숫자로)"""

    async def convert(self, ctx, argument):
        word = argument.strip().lower()
        if word in ALL_WORDS:
            return ALL
        if word in HALF_WORDS:
            return HALF
        amount = parse_amount(argument)
        if amount is None or amount != int(amount):
            raise commands.BadArgument(f"금액을 읽을 수 없어요: {argument}")
        return int(amount)


def resolve_amount(amount, maximum):
    """Amount 로 받은 값을 실제 숫자로. 올인 = maximum, 절반 = maximum 의 절반 (정수로 내림)"""
    if amount == ALL:
        return int(maximum)
    if amount == HALF:
        return int(maximum // 2)
    return amount
