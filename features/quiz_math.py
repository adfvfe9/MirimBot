"""선착순 퀴즈 수학 문제: 매번 숫자를 바꿔서 새로 만든다. (고2 2학기: 대수, 미적분 I 범위)

난이도별 함수 목록 GENERATORS[하/중/상] 에서 하나를 골라 부른다.
모든 문제는 정답이 정수가 되게 숫자를 고르고, 일부는 그래프 그림(PNG)을 같이 낸다.

문제 하나 = dict
    unit      단원 (예: "미적분 I · 미분")
    question  문제 (디스코드 마크다운)
    answer    정답 (int)
    explain   풀이
    image     그래프 PNG bytes 또는 None
"""
import io
import os
import random
from fractions import Fraction
from math import gcd

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

# 그래프에 한글이 나오도록 맑은 고딕 등록 (stocks.py 와 같은 폰트)
_FONT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "malgun.ttf")
if os.path.exists(_FONT_PATH):
    font_manager.fontManager.addfont(_FONT_PATH)
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=_FONT_PATH).get_name()
plt.rcParams["axes.unicode_minus"] = False


# ───────────── 표기 도우미 ─────────────
_SUP = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")
_SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


def sup(n) -> str:
    return str(n).translate(_SUP)


def sub(n) -> str:
    return str(n).translate(_SUB)


def signed(n) -> str:
    """식 중간에 붙일 숫자: +3 → ' + 3', -3 → ' − 3'"""
    return f" + {n}" if n >= 0 else f" − {-n}"


def xm(r) -> str:
    """(x − r) 의 안쪽: 0 → 'x', 3 → 'x − 3', -2 → 'x + 2'"""
    return "x" if r == 0 else f"x{signed(-r)}"


def poly(coefs, var="x") -> str:
    """계수 목록(최고차항부터)을 식으로. [1, -3, 0, 2] → 'x³ − 3x + 2'"""
    deg = len(coefs) - 1
    parts = []
    for i, c in enumerate(coefs):
        p = deg - i
        if c == 0:
            continue
        a = abs(c)
        coef = "" if a == 1 and p > 0 else str(a)
        body = coef + ("" if p == 0 else var if p == 1 else var + sup(p))
        if not parts:
            parts.append(("−" if c < 0 else "") + body)
        else:
            parts.append((" − " if c < 0 else " + ") + body)
    return "".join(parts) or "0"


def poly_mul(p, q):
    out = [0] * (len(p) + len(q) - 1)
    for i, a in enumerate(p):
        for j, b in enumerate(q):
            out[i + j] += a * b
    return out


def from_roots(lead, roots):
    """lead × (x − r₁)(x − r₂)... 의 계수 목록"""
    coefs = [lead]
    for r in roots:
        coefs = poly_mul(coefs, [1, -r])
    return coefs


def evaluate(coefs, x):
    total = 0
    for c in coefs:
        total = total * x + c
    return total


def derivative(coefs):
    deg = len(coefs) - 1
    return [c * (deg - i) for i, c in enumerate(coefs[:-1])]


def plot(f, x_range, label, points=(), y_range=None) -> bytes:
    """시험지 느낌의 그래프. points: [(x, y, 글자)] 에 점을 찍고 글자를 단다."""
    x0, x1 = x_range
    xs = [x0 + (x1 - x0) * i / 400 for i in range(401)]
    ys = [f(x) for x in xs]
    fig, ax = plt.subplots(figsize=(5, 4), dpi=110)
    ax.plot(xs, ys, color="#1f3a93", linewidth=2)
    if y_range:
        ax.set_ylim(*y_range)
    ax.spines["left"].set_position("zero")
    ax.spines["bottom"].set_position("zero")
    ax.spines["right"].set_visible(False)
    ax.spines["top"].set_visible(False)
    ax.set_xticks(range(int(x0), int(x1) + 1))
    ax.grid(True, color="#dddddd", linewidth=0.8)
    ax.tick_params(labelsize=8)
    for px, py, text in points:
        ax.plot([px], [py], "o", color="#c0392b", markersize=5)
        ax.annotate(text, (px, py), textcoords="offset points", xytext=(6, 6), fontsize=9,
                    bbox={"boxstyle": "round,pad=0.15", "fc": "white", "ec": "none", "alpha": 0.85})
    ax.text(1.0, 0.0, "x", transform=ax.get_yaxis_transform(), ha="left", va="bottom", fontsize=10)
    ax.text(0.0, 1.0, "y", transform=ax.get_xaxis_transform(), ha="left", va="bottom", fontsize=10)
    ax.text(xs[-60], ys[-60], f"  {label}", fontsize=11, color="#1f3a93")
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def q(unit, question, answer, explain, image=None):
    assert int(answer) == answer, (unit, answer)
    return {"unit": unit, "question": question, "answer": int(answer), "explain": explain, "image": image}


# ───────────── 하 (1분) ─────────────

def exponent():
    terms = []
    total = 0
    for _ in range(2):
        r, n = random.choice([(2, 3), (2, 2), (3, 3), (3, 2), (5, 2), (2, 4)])   # 밑 = r^n
        p = random.choice([k for k in range(1, n + 2) if gcd(k, n) == 1])
        terms.append(f"{r ** n}^({p}/{n})")
        total += r ** p
    return q("대수 · 지수", f"**{terms[0]} + {terms[1]}** 의 값은?", total,
             "a^(p/n) = (ⁿ√a)ᵖ 를 이용해요.")


def logarithm():
    if random.random() < 0.5:
        b = random.choice([2, 3, 5])
        k = random.randint(2, 4)
        m = random.choice([x for x in range(2, 8) if x % b])
        return q("대수 · 로그", f"**log{sub(b)} {b ** k * m} − log{sub(b)} {m}** 의 값은?", k,
                 f"log{sub(b)} ({b ** k * m} ÷ {m}) = log{sub(b)} {b ** k} = {k}")
    a, b = random.sample([2, 3, 5, 7], 2)
    k = random.randint(2, 4)
    return q("대수 · 로그", f"**log{sub(a)} {b} × log{sub(b)} {a ** k}** 의 값은?", k,
             f"밑 변환: log{sub(a)} {b} × {k}·log{sub(b)} {a} = {k}")


def arithmetic_sequence():
    d = random.choice([-3, -2, 2, 3, 4, 5])
    a1 = random.randint(-5, 10)
    i, j = random.sample(range(2, 8), 2)
    n = random.randint(10, 20)
    ai, aj = a1 + (i - 1) * d, a1 + (j - 1) * d
    return q("대수 · 수열", f"등차수열 {{aₙ}}에서 **a{sub(i)} = {ai}, a{sub(j)} = {aj}** 일 때, **a{sub(n)}** 의 값은?",
             a1 + (n - 1) * d, f"공차 = ({aj} − {ai}) ÷ ({j} − {i}) = {d}")


def derivative_value():
    coefs = [random.randint(1, 3), random.randint(-4, 4), random.randint(-5, 5), random.randint(-5, 5)]
    k = random.randint(-2, 3)
    ans = evaluate(derivative(coefs), k)
    return q("미적분 I · 미분", f"함수 **f(x) = {poly(coefs)}** 에 대하여 **f′({k})** 의 값은?", ans,
             f"f′(x) = {poly(derivative(coefs))}")


def limit_factor():
    a = random.randint(-3, 4)
    r = random.choice([x for x in range(-4, 6) if x != a])
    num = from_roots(1, [a, r])
    return q("미적분 I · 함수의 극한",
             f"**lim(x→{a})  ({poly(num)}) / ({xm(a)})** 의 값은?", a - r,
             f"분자 = ({xm(a)})({xm(r)}) → 약분하면 {xm(r)} → x = {a} 대입 → {a - r}")


def vieta():
    s, p = random.choice([x for x in range(-6, 7) if x]), random.choice([x for x in range(-8, 9) if x])
    return q("이차방정식 · 근과 계수",
             f"이차방정식 **{poly([1, -s, p])} = 0** 의 두 근을 α, β라 할 때, "
             f"**α² + β²** 의 값은?", s * s - 2 * p,
             f"α + β = {s}, αβ = {p} → α² + β² = (α + β)² − 2αβ = {s * s - 2 * p}")


def graph_quadratic():
    p, qq = random.randint(-2, 3), random.randint(-4, 2)
    coefs = [1, -2 * p, p * p + qq]
    k = random.choice([x for x in range(-3, 6) if x != p])
    image = plot(lambda x: (x - p) ** 2 + qq, (p - 3.2, p + 3.2), "y = f(x)",
                 [(p, qq, f"({p}, {qq})")])
    return q("이차함수 · 그래프",
             f"최고차항의 계수가 1인 이차함수 **y = f(x)** 의 그래프가 그림과 같다. 꼭짓점이 ({p}, {qq})일 때, **f({k})** 의 값은?",
             evaluate(coefs, k), f"f(x) = ({xm(p)})²{signed(qq)} = {poly(coefs)}", image)


# ───────────── 중 (5분) ─────────────

def sigma():
    a, b = random.randint(1, 5), random.randint(-5, 5)
    n = random.randint(5, 15)
    ans = a * n * (n + 1) // 2 + b * n
    return q("대수 · 수열의 합", f"**Σ(k=1~{n}) ({a}k{signed(b)})** 의 값은?", ans,
             f"{a} × {n}·{n + 1}/2{signed(b * n)} = {ans}")


def geometric_sum():
    a, r, n = random.randint(1, 3), random.choice([2, 3]), random.randint(4, 7)
    ans = a * (r ** n - 1) // (r - 1)
    return q("대수 · 등비수열", f"첫째항이 {a}, 공비가 {r}인 등비수열의 **첫째항부터 제{n}항까지의 합**은?", ans,
             f"S = {a}({r}{sup(n)} − 1)/({r} − 1) = {ans}")


def definite_integral():
    a, b, c = random.choice([1, 2, -1]), random.randint(-3, 3), random.randint(-4, 4)
    lo, hi = sorted(random.sample(range(-2, 4), 2))
    coefs = [3 * a, 2 * b, c]
    ans = a * (hi ** 3 - lo ** 3) + b * (hi ** 2 - lo ** 2) + c * (hi - lo)
    return q("미적분 I · 정적분", f"**∫({lo}→{hi}) ({poly(coefs)}) dx** 의 값은?", ans,
             f"부정적분 F(x) = {poly([a, b, c, 0])} → F({hi}) − F({lo}) = {ans}")


def extremum():
    k, c = random.randint(1, 3), random.randint(-6, 6)
    coefs = [1, 0, -3 * k * k, c]
    if random.random() < 0.5:
        return q("미적분 I · 극대와 극소", f"함수 **f(x) = {poly(coefs)}** 의 **극댓값**은?", 2 * k ** 3 + c,
                 f"f′(x) = 3(x + {k})(x − {k}) → x = −{k} 에서 극대, f(−{k}) = {2 * k ** 3 + c}")
    return q("미적분 I · 극대와 극소", f"함수 **f(x) = {poly(coefs)}** 의 **극솟값**은?", -2 * k ** 3 + c,
             f"f′(x) = 3(x + {k})(x − {k}) → x = {k} 에서 극소, f({k}) = {-2 * k ** 3 + c}")


def trig_function():
    a, c = random.randint(1, 4), random.randint(-3, 3)
    b_text, period_k = random.choice([(" x", 2), (" 2x", 1), ("(x/2)", 4)])
    fn = random.choice(["sin", "cos"])
    ans = 2 * c + period_k
    return q("대수 · 삼각함수",
             f"함수 **y = {a if a > 1 else ''}{fn}{b_text}{signed(c) if c else ''}** 의 최댓값을 M, 최솟값을 m, 주기를 kπ라 할 때, **M + m + k** 의 값은?",
             ans, f"M = {a + c}, m = {c - a}, 주기 = {period_k}π")


def trig_values():
    table = [  # (식, 값)
        ("sin(π/6)", Fraction(1, 2)), ("cos(π/3)", Fraction(1, 2)), ("sin²(π/4)", Fraction(1, 2)),
        ("sin²(π/3)", Fraction(3, 4)), ("cos²(π/6)", Fraction(3, 4)), ("tan(π/4)", Fraction(1)),
        ("tan²(π/3)", Fraction(3)), ("cos π", Fraction(-1)), ("sin(3π/2)", Fraction(-1)),
        ("cos²(π/4)", Fraction(1, 2)), ("tan²(π/6)", Fraction(1, 3)),
    ]
    picked = random.sample(table, 3)
    text, total = [], Fraction(0)
    for i, (expr, value) in enumerate(picked):
        coef = value.denominator * random.randint(1, 3) * random.choice([1, -1] if i else [1])
        total += coef * value
        text.append((f"{coef}" if i == 0 else f" + {coef}" if coef > 0 else f" − {-coef}") + expr)
    return q("대수 · 삼각함수", f"**{''.join(text)}** 의 값은?", total,
             ", ".join(f"{e} = {v}" for e, v in picked))


def log_equation():
    b, k = random.choice([(2, 3), (2, 4), (2, 5), (3, 2), (3, 3), (2, 6)])
    i = random.randint(0, (k - 1) // 2)
    x, y = b ** i, b ** (k - i)
    c = y - x
    return q("대수 · 로그방정식", f"방정식 **log{sub(b)} x + log{sub(b)} (x + {c}) = {k}** 의 해는?", x,
             f"x(x + {c}) = {b ** k} → x = {x} (진수 조건 x > 0)")


def graph_cubic():
    roots = sorted(random.sample(range(-3, 4), 3))
    coefs = from_roots(1, roots)
    k = random.choice([x for x in range(-4, 6) if x not in roots and abs(x) >= 2])
    f = lambda x: evaluate(coefs, x)  # noqa: E731
    lo, hi = roots[0] - 1.2, roots[2] + 1.2
    peak = max(abs(f(lo + (hi - lo) * i / 50)) for i in range(51))
    image = plot(f, (lo, hi), "y = f(x)", [(r, 0, str(r)) for r in roots], y_range=(-peak * 1.1, peak * 1.1))
    return q("미적분 I · 다항함수의 그래프",
             f"최고차항의 계수가 1인 삼차함수 **y = f(x)** 의 그래프가 그림과 같이 x축과 세 점에서 만난다. **f({k})** 의 값은?",
             f(k), f"f(x) = " + "".join(f"({xm(r)})" for r in roots), image)


# ───────────── 상 (10분) ─────────────

def area_between():
    while True:
        a = random.choice([1, 2, 3])
        p, r = sorted(random.sample(range(-3, 5), 2))
        if (a * (r - p) ** 3) % 6 == 0:
            break
    s, t = random.randint(-3, 3), random.randint(-3, 3)
    diff = from_roots(a, [p, r])
    f = [diff[0], diff[1] + s, diff[2] + t]
    ans = a * (r - p) ** 3 // 6
    return q("미적분 I · 넓이",
             f"곡선 **y = {poly(f)}** 와 직선 **y = {poly([s, t])}** 로 둘러싸인 부분의 넓이는?", ans,
             f"두 식의 차 = {a}({xm(p)})({xm(r)}) → 넓이 = {a} × ({r} − ({p}))³ / 6 = {ans}")


def tangent_line():
    coefs = [1, random.randint(-3, 3), random.randint(-4, 4), random.randint(-5, 5)]
    t = random.randint(-2, 2) or 1
    ft, dt = evaluate(coefs, t), evaluate(derivative(coefs), t)
    ans = ft - t * dt
    return q("미적분 I · 접선",
             f"곡선 **y = {poly(coefs)}** 위의 점 ({t}, {ft})에서의 접선이 y축과 만나는 점의 **y좌표**는?", ans,
             f"기울기 f′({t}) = {dt} → y = {dt}({xm(t)}){signed(ft)} → x = 0 대입")


def recurrence():
    a1, r, d = random.randint(1, 3), random.choice([2, 3]), random.randint(-1, 3)
    k = random.randint(5, 6 if r == 2 else 5)
    a = a1
    for _ in range(k - 1):
        a = r * a + d
    return q("대수 · 수열의 귀납적 정의",
             f"수열 {{aₙ}}이 **a₁ = {a1}, aₙ₊₁ = {r}aₙ{signed(d)}** (n ≥ 1)을 만족시킬 때, **a{sub(k)}** 의 값은?", a,
             "a₁부터 차례로 구해요.")


def continuity():
    m, n = random.randint(1, 3), random.randint(2, 6)
    return q("미적분 I · 함수의 연속",
             f"함수 **f(x) = (x² + ax − {m * n}) / (x − {m})** (x ≠ {m}), **f({m}) = b** 가 실수 전체에서 연속일 때, "
             f"**a + b** 의 값은? (단, a, b는 상수)", 2 * n,
             f"x = {m}에서 분자가 0 → a = {n - m}, 분자 = (x − {m})(x + {n}) → b = {m + n}")


def telescoping():
    n = random.choice([3, 8, 15, 24, 35, 48, 63, 80, 99])
    return q("대수 · 수열의 합",
             f"**Σ(k=1~{n}) 1 / (√(k+1) + √k)** 의 값은?", round((n + 1) ** 0.5) - 1,
             f"유리화하면 √(k+1) − √k → 합 = √{n + 1} − 1")


def graph_derivative():
    while True:
        a, b = sorted(random.sample(range(-2, 4), 2))
        c = random.randint(-4, 4)
        # f′(x) = 3(x − a)(x − b), f(0) = c
        fx = [Fraction(1), Fraction(-3 * (a + b), 2), Fraction(3 * a * b), Fraction(c)]
        ans = evaluate(fx, b)
        if ans.denominator == 1:
            break
    d = from_roots(3, [a, b])
    f = lambda x: evaluate(d, x)  # noqa: E731
    image = plot(f, (a - 1.3, b + 1.3), "y = f′(x)", [(a, 0, str(a)), (b, 0, str(b))])
    return q("미적분 I · 도함수의 활용",
             f"삼차함수 f(x)의 도함수 **y = f′(x)** 의 그래프가 그림과 같다. f′(x)의 최고차항의 계수가 3이고 "
             f"**f(0) = {c}** 일 때, 함수 f(x)의 **극솟값**은?", ans,
             f"f′(x) = 3({xm(a)})({xm(b)}) → f(x) = ∫f′(x)dx 이고 f(0) = {c}로 적분상수를 정해요. "
             f"x = {b}에서 극소 → f({b}) = {ans}", image)


GENERATORS = {
    "하": [exponent, logarithm, arithmetic_sequence, derivative_value, limit_factor, vieta, graph_quadratic],
    "중": [sigma, geometric_sum, definite_integral, extremum, trig_function, trig_values, log_equation, graph_cubic],
    "상": [area_between, tangent_line, recurrence, continuity, telescoping, graph_derivative],
}


def make(level: str) -> dict:
    return random.choice(GENERATORS[level])()
