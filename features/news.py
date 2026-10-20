"""주식 뉴스: 30~90분마다 랜덤 뉴스가 나오고, 뉴스에 맞춰 주가가 10~30분 동안 서서히 움직인다.

    %뉴스                최근 뉴스 보기
    %뉴스채널 <채널ID>    (관리자) 뉴스를 올릴 채널 설정
    %뉴스발행            (관리자) 지금 바로 뉴스 하나 내기

- 효과는 한 번에 튀지 않고 매분 조금씩 더해진다. (stocks.update_stocks 가 current_drift 를 사용)
  → 뉴스를 보고 빨리 움직인 학생이 유리하다.
- 진행 중인 효과는 메모리에만 있어서, 봇을 재시작하면 사라진다. (뉴스 기록은 DB 에 남음)
"""
import random

import discord
from discord.ext import commands, tasks

import database as db
from bot import client
from features import stocks
from fmt import num

# ───────────── 밸런스 설정 ─────────────
NEWS_INTERVAL_MINUTES = (30, 90)      # 다음 뉴스까지 랜덤 간격
EFFECT_MINUTES = (10, 30)             # 효과가 지속되는 시간

# 뉴스 종류별 확률 (%)
KIND_WEIGHTS = {
    "good": 35,           # 개별 종목 호재
    "bad": 35,            # 개별 종목 악재
    "market_good": 10,    # 시장 전체 호재
    "market_bad": 10,     # 시장 전체 악재
    "bubble": 5,          # 초상승장 (끝나면 주식부도로 이어짐)
    "default_risk": 5,    # 한 종목 부도 위기 (상장폐지 위험)
}

# 1분마다 가격에 더해지는 변화 (기준가 대비 비율). 예: 0.01 이면 기준가의 1% 만큼 오른다.
STOCK_DRIFT = (0.003, 0.010)          # 개별 종목: 분당 기준가의 +-0.3~1.0% → 뉴스가 끝날 때 평균 약 8% 움직임
MARKET_DRIFT = (0.002, 0.005)         # 시장 전체: 분당 기준가의 +-0.2~0.5%
DEFAULT_RISK_DRIFT = (0.06, 0.10)     # 부도 위기: 분당 기준가의 -6~10% → 상장폐지 확률 JS 4% ~ RUST 34%
DEFAULT_RISK_MINUTES = (10, 15)
BUBBLE_MINUTES = (10, 20)             # 초상승장 길이 (끝나면 stocks 가 주식부도 20분을 건다)

# ───────────── 뉴스 문장 틀 ─────────────
GOOD = [
    ("{s}, 대형 IT 기업과 파트너십 체결", "업계에서는 {s} 관련주의 수요가 크게 늘 것으로 보고 있다."),
    ("{s} 개발자 연봉 역대 최고치 경신", "{s}를 배우려는 사람이 몰리면서 관련 시장이 들썩이고 있다."),
    ("{s} 신규 버전 공개, 성능 2배 향상", "커뮤니티 반응이 뜨겁다. 개발자들 사이에서 '이번엔 진짜다'라는 평가."),
    ("미림마이스터고, 다음 학기 {s} 수업 확대", "학생 수요가 늘면서 {s} 관련주가 주목받고 있다."),
    ("{s}, 개발자 설문 '가장 사랑받는 언어' 1위", "{s} 생태계에 투자자들의 관심이 쏠리고 있다."),
    ("유명 스타트업, 전 서비스를 {s}로 재작성 발표", "{s} 관련 일자리가 크게 늘 전망이다."),
]
BAD = [
    ("{s}에서 치명적 보안 취약점 발견", "긴급 패치가 나오기 전까지 {s} 사용을 자제하라는 권고가 나왔다."),
    ("{s} 핵심 개발자 대거 이탈", "향후 업데이트가 늦어질 수 있다는 우려가 커지고 있다."),
    ("{s} 라이선스 정책 변경… 개발자들 반발", "일부 기업은 다른 언어로 옮기는 것을 검토 중이다."),
    ("'{s}는 이제 한물갔다' 유명 개발자 발언 논란", "커뮤니티가 술렁이며 {s} 관련주에 매도세가 몰리고 있다."),
    ("{s} 컴파일 오류 대란, 전 세계 서버 다운", "복구까지 시간이 걸릴 것으로 보인다."),
    ("대형 IT 기업, {s} 지원 중단 발표", "{s} 관련 시장이 크게 위축될 전망이다."),
]
MARKET_GOOD = [
    ("IT 업계 호황, 개발자 채용 열풍", "전 종목에 걸쳐 매수세가 이어지고 있다."),
    ("정부, 소프트웨어 교육 예산 대폭 확대", "프로그래밍 언어 관련주 전반이 강세다."),
    ("AI 붐 계속… 개발 언어 시장 전반 상승", "투자 심리가 살아나고 있다."),
]
MARKET_BAD = [
    ("IT 버블 우려 확산, 투자 심리 위축", "전 종목에 걸쳐 매도세가 나타나고 있다."),
    ("대규모 정전으로 데이터센터 마비", "개발 언어 시장 전반이 흔들리고 있다."),
    ("글로벌 경기 침체 우려, 기술주 일제히 약세", "당분간 조심스러운 흐름이 예상된다."),
]
BUBBLE = [
    ("🚀 역대급 IT 호황! 개발 언어 시장 폭등", "모든 종목이 미친 듯이 오르고 있다. 전문가들은 '거품이 꺼지면 위험하다'고 경고한다."),
]
DEFAULT_RISK = [
    ("⚠️ {s} 부도 위기설… 투자자 패닉", "{s}가 버티지 못하면 상장폐지될 수 있다는 관측이 나온다."),
    ("⚠️ {s} 운영사 자금난 심각", "{s} 관련주가 폭락하고 있다. 상장폐지 가능성도 거론된다."),
]

KIND_STYLE = {
    "good": ("📈 호재", discord.Color.green()),
    "bad": ("📉 악재", discord.Color.red()),
    "market_good": ("🌐 시장 호재", discord.Color.green()),
    "market_bad": ("🌐 시장 악재", discord.Color.red()),
    "bubble": ("🚀 초대형 호재", discord.Color.gold()),
    "default_risk": ("💥 부도 위기", discord.Color.dark_red()),
}

# 진행 중인 효과: [{"symbol": 종목 또는 None(시장 전체), "drift": 분당 변화율, "left": 남은 분}]
active_effects = []
minutes_until_next = random.randint(*NEWS_INTERVAL_MINUTES)


def current_drift(symbol):
    """이번 분에 해당 종목에 더할 변화 (기준가 대비 비율, stocks.update_stocks 에서 사용)"""
    return sum(e["drift"] for e in active_effects if e["symbol"] in (None, symbol))


def tick_effects():
    """1분 지남: 효과 남은 시간을 줄이고 끝난 효과를 지운다."""
    for e in active_effects:
        e["left"] -= 1
    active_effects[:] = [e for e in active_effects if e["left"] > 0]


async def make_news(kind=None):
    """뉴스 하나를 만들고 효과를 건다. (kind, symbol, headline, body) 를 돌려준다."""
    if kind is None:
        kind = random.choices(list(KIND_WEIGHTS), weights=list(KIND_WEIGHTS.values()))[0]

    symbol = random.choice(list(stocks.stock_info)) if kind in ("good", "bad", "default_risk") else None
    minutes = random.randint(*EFFECT_MINUTES)

    if kind == "good":
        headline, body = random.choice(GOOD)
        active_effects.append({"symbol": symbol, "drift": random.uniform(*STOCK_DRIFT), "left": minutes})
    elif kind == "bad":
        headline, body = random.choice(BAD)
        active_effects.append({"symbol": symbol, "drift": -random.uniform(*STOCK_DRIFT), "left": minutes})
    elif kind == "market_good":
        headline, body = random.choice(MARKET_GOOD)
        active_effects.append({"symbol": None, "drift": random.uniform(*MARKET_DRIFT), "left": minutes})
    elif kind == "market_bad":
        headline, body = random.choice(MARKET_BAD)
        active_effects.append({"symbol": None, "drift": -random.uniform(*MARKET_DRIFT), "left": minutes})
    elif kind == "bubble":
        headline, body = random.choice(BUBBLE)
        await stocks.set_override_state("HYPER_BULL", random.randint(*BUBBLE_MINUTES) * 60)
    else:  # default_risk
        headline, body = random.choice(DEFAULT_RISK)
        active_effects.append({
            "symbol": symbol,
            "drift": -random.uniform(*DEFAULT_RISK_DRIFT),
            "left": random.randint(*DEFAULT_RISK_MINUTES),
        })

    headline = headline.format(s=symbol)
    body = body.format(s=symbol)
    await db.add_news(kind, symbol, headline, body)
    return kind, symbol, headline, body


def news_embed(kind, symbol, headline, body, when=None):
    label, color = KIND_STYLE.get(kind, ("📰 뉴스", discord.Color.blurple()))
    embed = discord.Embed(title=f"📰 [속보] {headline}", description=body, color=color)
    embed.add_field(name="분류", value=label, inline=True)
    if symbol:
        price = stocks.stock_prices.get(symbol, {}).get("current")
        embed.add_field(name="관련 종목", value=f"{symbol} (현재 {num(price)} byte)", inline=True)
    embed.set_footer(text=(when or db.now()).astimezone(db.KST).strftime("%m월 %d일 %H:%M") + " · 미림 경제신문")
    return embed


async def publish(kind=None):
    """뉴스를 만들어 설정된 모든 뉴스 채널에 올린다."""
    kind, symbol, headline, body = await make_news(kind)
    embed = news_embed(kind, symbol, headline, body)
    for channel_id in await db.get_news_channels():
        channel = client.get_channel(channel_id)
        if channel is None:
            continue
        try:
            await channel.send(embed=embed)
        except discord.HTTPException as e:
            print(f"[뉴스] 채널 {channel_id} 전송 실패: {e}")
    print(f"[뉴스] {headline}")
    return embed


@tasks.loop(minutes=1)
async def news_loop():
    global minutes_until_next
    try:
        minutes_until_next -= 1
        if minutes_until_next <= 0:
            minutes_until_next = random.randint(*NEWS_INTERVAL_MINUTES)
            await publish()
    except Exception as e:
        print(f"[뉴스 오류] {type(e).__name__}: {e}")


@news_loop.before_loop
async def before_news_loop():
    await client.wait_until_ready()


@client.listen("on_ready")
async def start_news_loop():
    if not news_loop.is_running():
        news_loop.start()


# ───────────── 명령어 ─────────────

@client.command(aliases=["뉴스"])
async def news(ctx):
    await ctx.message.delete()
    rows = await db.recent_news(5)
    if not rows:
        await ctx.send("📭 아직 나온 뉴스가 없어요.")
        return

    embed = discord.Embed(title="📰 최근 뉴스", color=discord.Color.blurple())
    for row in rows:
        label, _ = KIND_STYLE.get(row["kind"], ("📰", None))
        when = row["created_at"].astimezone(db.KST).strftime("%m/%d %H:%M")
        embed.add_field(name=f"{when}  {label}  {row['headline']}", value=row["body"], inline=False)
    embed.set_footer(text=f"다음 뉴스까지 약 {minutes_until_next}분")
    await ctx.send(embed=embed)


@client.command(aliases=["뉴스채널"])
@commands.has_permissions(administrator=True)
async def set_news_channel(ctx, channel_id: int):
    await ctx.message.delete()
    await db.set_news_channel(ctx.guild.id, channel_id)
    await ctx.send(f"✅ 뉴스 채널이 <#{channel_id}>로 설정되었습니다.")


@client.command(aliases=["뉴스발행"])
@commands.has_permissions(administrator=True)
async def publish_news(ctx):
    await ctx.message.delete()
    embed = await publish()
    if not await db.get_news_channels():
        await ctx.send("⚠️ 뉴스 채널이 설정되지 않아 여기에만 보여요. (`%뉴스채널 <채널ID>`)", embed=embed)
