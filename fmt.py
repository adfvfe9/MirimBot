"""숫자 표시용 도우미.

DB 에는 계산한 값을 그대로 저장하고, 화면에 보여줄 때만 이 함수로 정리한다.
- 소수점은 최대 2자리까지, 그 아래는 버린다(내림). 예: 12.349 → 12.34
- 끝의 0 은 지운다. 예: 100.00 → 100, 12.50 → 12.5
- 천 단위 쉼표를 넣는다. 예: 1234567.8 → 1,234,567.8

    from fmt import num
    f"{num(balance)} byte"          → "1,234.5 byte"
    f"{num(profit, sign=True)} byte" → "+1,234.5 byte" / "-12 byte"
    f"{num(rate, sign=True)}%"       → "+3.14%"
"""
from decimal import ROUND_DOWN, Decimal


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
