"""주식 뉴스: 30~90분마다 랜덤 뉴스가 나오고, 뉴스가 나오는 순간 주가가 한 번에 튄다.

    %뉴스                최근 뉴스 보기
    %뉴스채널 <채널ID>    (관리자) 뉴스를 올릴 채널 설정
    %뉴스발행            (관리자) 지금 바로 뉴스 하나 내기

- 큰 움직임(점프)은 뉴스와 동시에 일어난다. 뉴스를 보고 들어가면 이미 움직인 뒤다. (stocks.jump)
- 그 뒤 10~30분 동안 작은 후속 움직임이 이어지는데, 방향은 반반에 가깝다. (stocks.update_stocks 가 current_drift 를 사용)
  예전처럼 뉴스 뒤에 서서히 움직이면 뉴스만 보고 레버리지를 타서 누구나 벌 수 있었다.
- 일부 뉴스는 기사만 보고 방향을 알 수 없다: 루머(반반), 뒤통수(호재인데 하락 / 악재인데 상승)
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
    "good": 20,           # 개별 종목 호재
    "bad": 20,            # 개별 종목 악재
    "rumor": 32,          # 해석이 엇갈리는 뉴스 (오를지 내릴지 반반)
    "market_good": 10,    # 시장 전체 호재
    "market_bad": 10,     # 시장 전체 악재
    "bubble": 5,          # 초상승장 (끝나면 주식부도로 이어짐)
    "default_risk": 3,    # 한 종목 부도 위기 (상장폐지 위험)
}

# 호재/악재 뉴스인데 실제로는 반대로 움직일 확률 ("이미 가격에 반영", "소문에 사서 뉴스에 팔아라")
TWIST_CHANCE = 0.2

# 점프: 뉴스가 나오는 순간 한 번에 튀는 크기 (변화율, 0.1 이면 약 10%)
JUMP_SIZE = (0.06, 0.15)              # 기준 = 0.06 + 종목 하루 변동성 × 0.15, 실제는 그 0.5~1.5배 (JS 약 4~11%, RUST 약 8~23%)
MARKET_JUMP = (0.01, 0.04)            # 시장 전체 뉴스: 모든 종목 1~4%
DEFAULT_RISK_JUMP = (0.15, 0.30)      # 부도 위기: 15~30% 폭락

# 후속 움직임: 점프 뒤 효과가 끝날 때까지 1분마다 더해지는 변화 (현재가 대비 비율)
FOLLOW_SAME_CHANCE = 0.55             # 점프와 같은 방향일 확률 (거의 반반이라 뉴스만 보고 따라가면 수수료만큼 손해)
STOCK_DRIFT = (0.0005, 0.0015)        # 개별 종목: 분당 0.05~0.15%
RUMOR_DRIFT = (0.001, 0.003)          # 루머: 분당 0.1~0.3%, 방향 반반
MARKET_DRIFT = (0.0002, 0.0005)       # 시장 전체: 분당 0.02~0.05%
DEFAULT_RISK_DRIFT = (0.003, 0.010)   # 부도 위기: 분당 0.3~1% 계속 하락
DEFAULT_RISK_MINUTES = (10, 15)
DELIST_CHANCE = (0.02, 0.20)          # 부도 위기가 상장폐지로 끝날 확률: 가장 안정적인 종목(JS) ~ 가장 위험한 종목(RUST)
BUBBLE_MINUTES = (10, 20)             # 초상승장 길이 (끝나면 stocks 가 모든 종목을 떨어뜨리고 주식부도 20분을 건다)

# ───────────── 뉴스 문장 틀 ({s} 자리에 종목 이름이 들어간다) ─────────────
GOOD = [
    ("{s}, 대형 IT 기업과 파트너십 체결", "업계에서는 {s} 관련주의 수요가 크게 늘 것으로 보고 있다."),
    ("{s} 개발자 연봉 역대 최고치 경신", "{s}를 배우려는 사람이 몰리면서 관련 시장이 들썩이고 있다."),
    ("{s} 신규 버전 공개, 성능 2배 향상", "커뮤니티 반응이 뜨겁다. 개발자들 사이에서 '이번엔 진짜다'라는 평가."),
    ("미림마이스터고, 다음 학기 {s} 수업 확대", "학생 수요가 늘면서 {s} 관련주가 주목받고 있다."),
    ("{s}, 개발자 설문 '가장 사랑받는 언어' 1위", "{s} 생태계에 투자자들의 관심이 쏠리고 있다."),
    ("유명 스타트업, 전 서비스를 {s}로 재작성 발표", "{s} 관련 일자리가 크게 늘 전망이다."),
    ("{s}로 만든 게임, 출시 첫날 100만 다운로드", "개발사 측은 '{s} 덕분에 개발 기간을 절반으로 줄였다'고 밝혔다."),
    ("국제 코딩대회 우승팀, '{s}가 비결' 인터뷰", "대회 이후 {s} 강의 수강생이 급증했다."),
    ("{s} 공식 문서 전면 개편, 입문자 호평", "'이제야 이해된다'는 후기가 쏟아지고 있다."),
    ("빅테크 3사, {s} 전문 인력 대규모 채용 공고", "채용 시장에서 {s} 개발자 몸값이 치솟고 있다."),
    ("{s}, 우주 탐사선 소프트웨어로 채택", "'우주에서도 버그 없이 돌아간다'는 평가가 나왔다."),
    ("정보처리기사 실기, 올해부터 {s} 문제 비중 확대", "수험생들 사이에서 {s} 공부 열풍이 불고 있다."),
]
BAD = [
    ("{s}에서 치명적 보안 취약점 발견", "긴급 패치가 나오기 전까지 {s} 사용을 자제하라는 권고가 나왔다."),
    ("{s} 핵심 개발자 대거 이탈", "향후 업데이트가 늦어질 수 있다는 우려가 커지고 있다."),
    ("{s} 라이선스 정책 변경… 개발자들 반발", "일부 기업은 다른 언어로 옮기는 것을 검토 중이다."),
    ("'{s}는 이제 한물갔다' 유명 개발자 발언 논란", "커뮤니티가 술렁이며 {s} 관련주에 매도세가 몰리고 있다."),
    ("{s} 컴파일 오류 대란, 전 세계 서버 다운", "복구까지 시간이 걸릴 것으로 보인다."),
    ("대형 IT 기업, {s} 지원 중단 발표", "{s} 관련 시장이 크게 위축될 전망이다."),
    ("{s} 최신 업데이트 후 '프로그램이 안 켜진다' 신고 폭주", "개발진은 원인을 조사 중이라고만 밝혔다."),
    ("{s}로 만든 은행 앱 장애… 3시간 송금 마비", "책임 공방이 이어지며 {s}에 대한 신뢰가 흔들리고 있다."),
    ("{s} 개발자 커뮤니티 내분… 프로젝트 분열 위기", "두 진영이 각자 다른 버전을 만들겠다고 선언했다."),
    ("해커 집단, {s} 패키지 저장소 공격", "수천 개의 패키지가 오염됐을 가능성이 제기됐다."),
    ("{s} 메모리 누수 버그 10년 만에 발견", "'그동안 왜 아무도 몰랐나'라는 비판이 나온다."),
    ("유명 기업, '{s} 때문에 서비스 느려졌다' 공개 비판", "{s} 성능 논란이 다시 불붙었다."),
]
# 해석이 엇갈리는 뉴스: 오를지 내릴지 기사만 보고는 알 수 없다. (실제 방향은 반반)
RUMOR = [
    ("{s} 창시자, 내일 '중대 발표' 예고", "어떤 내용인지는 아직 알려지지 않았다. 커뮤니티는 기대 반 걱정 반."),
    ("{s} 운영 재단, 대규모 조직 개편 단행", "'더 빨라질 것'이라는 쪽과 '혼란이 올 것'이라는 쪽으로 의견이 갈린다."),
    ("{s} 관련 기업 CEO 돌연 사임", "후임자가 누구냐에 따라 분위기가 크게 달라질 전망이다."),
    ("익명 게시판에 '{s} 곧 터진다' 글 화제", "좋은 의미인지 나쁜 의미인지를 두고 해석이 분분하다."),
    ("{s}, 경쟁 언어와 합병 논의설", "성사되면 시너지가 크겠지만, 결렬되면 타격이 클 수 있다."),
    ("정부, {s} 관련 규제 검토 착수", "업계는 '오히려 기회'라는 쪽과 '족쇄'라는 쪽으로 나뉘었다."),
    ("{s} 실적 발표 D-1, 전문가 전망 엇갈려", "'역대 최고'와 '어닝 쇼크' 예측이 동시에 나오고 있다."),
    ("유명 투자자, {s} 대량 거래 포착", "산 건지 판 건지는 아직 확인되지 않았다."),
    ("{s} 차기 버전, 기존 코드와 호환 안 된다", "새 기능은 강력하지만 옮기는 비용이 만만치 않다는 지적이다."),
    ("{s} 개발팀, 미림마이스터고 방문 예정", "학생들 사이에서 '채용 설명회다', '단순 견학이다' 소문이 엇갈린다."),
    ("{s}, AI가 코드를 대신 짜주는 기능 공개", "개발자 수요가 늘지 줄지를 두고 논쟁이 뜨겁다."),
    ("'{s} 거품 논란' 토론회 개최", "찬반 양측의 팽팽한 토론이 이어졌다. 결론은 나지 않았다."),
]
MARKET_GOOD = [
    ("IT 업계 호황, 개발자 채용 열풍", "전 종목에 걸쳐 매수세가 이어지고 있다."),
    ("정부, 소프트웨어 교육 예산 대폭 확대", "프로그래밍 언어 관련주 전반이 강세다."),
    ("AI 붐 계속… 개발 언어 시장 전반 상승", "투자 심리가 살아나고 있다."),
    ("기준금리 인하 발표, 기술주 일제히 반등", "시장에 돈이 풀리며 매수세가 몰리고 있다."),
    ("전국 마이스터고 졸업생 취업률 역대 최고", "개발 인력 시장 전체가 활기를 띠고 있다."),
]
MARKET_BAD = [
    ("IT 버블 우려 확산, 투자 심리 위축", "전 종목에 걸쳐 매도세가 나타나고 있다."),
    ("대규모 정전으로 데이터센터 마비", "개발 언어 시장 전반이 흔들리고 있다."),
    ("글로벌 경기 침체 우려, 기술주 일제히 약세", "당분간 조심스러운 흐름이 예상된다."),
    ("기준금리 인상 발표, 기술주 줄줄이 하락", "투자자들이 위험 자산에서 돈을 빼고 있다."),
    ("해저 인터넷 케이블 절단 사고", "복구까지 며칠이 걸릴 수 있어 시장 전체가 긴장하고 있다."),
]
BUBBLE = [
    ("🚀 역대급 IT 호황! 개발 언어 시장 폭등", "모든 종목이 미친 듯이 오르고 있다. 전문가들은 '거품이 꺼지면 위험하다'고 경고한다."),
    ("🚀 '코딩 안 하면 손해' 열풍… 개발 언어 시장 과열", "너도나도 뛰어들고 있다. 일부에서는 '역사는 반복된다'며 폭락을 경고한다."),
]
DEFAULT_RISK = [
    ("⚠️ {s} 부도 위기설… 투자자 패닉", "{s}가 버티지 못하면 상장폐지될 수 있다는 관측이 나온다."),
    ("⚠️ {s} 운영사 자금난 심각", "{s} 관련주가 폭락하고 있다. 상장폐지 가능성도 거론된다."),
    ("⚠️ {s} 운영 재단 파산 신청 검토", "최악의 경우 {s} 지원이 완전히 끊길 수 있다."),
]

KIND_STYLE = {
    "good": ("📈 호재", discord.Color.green()),
    "bad": ("📉 악재", discord.Color.red()),
    "rumor": ("❓ 해석 엇갈림", discord.Color.greyple()),
    "market_good": ("🌐 시장 호재", discord.Color.green()),
    "market_bad": ("🌐 시장 악재", discord.Color.red()),
    "bubble": ("🚀 초대형 호재", discord.Color.gold()),
    "default_risk": ("💥 부도 위기", discord.Color.dark_red()),
}

# 진행 중인 효과
# [{"symbol": 종목 또는 None(시장 전체), "drift": 분당 변화, "left": 남은 분, "kind": 뉴스 종류, "delist": 끝나면 상장폐지}]
# kind 는 기사 분위기라서 실제 방향(drift 부호)과 다를 수 있다. (뒤통수 뉴스, 루머)
active_effects = []
minutes_until_next = random.randint(*NEWS_INTERVAL_MINUTES)


def current_drift(symbol):
    """이번 분에 해당 종목에 더할 변화 (현재가 대비 비율, stocks.update_stocks 에서 사용)"""
    return sum(e["drift"] for e in active_effects if e["symbol"] in (None, symbol))


def under_default_risk(symbol):
    """이 종목에 부도 위기 효과가 진행 중인지. (방향이 정해진 급락이라 레버리지 신규 진입을 막는다, features/futures.py)"""
    return any(e["symbol"] == symbol and e["kind"] == "default_risk" for e in active_effects)


# %주식 화면에 붙는 뉴스 표시 (기사 분위기 기준이라 실제 방향은 숨겨진다)
BADGES = {"good": "🔥", "bad": "🧊", "rumor": "❓", "default_risk": "💥"}


def badge(symbol):
    """종목 이름 옆에 붙일 이모지. 가장 최근 종목 뉴스 기준. 없으면 빈 문자열."""
    effects = [e for e in active_effects if e["symbol"] == symbol]
    if not effects:
        return ""
    return BADGES.get(effects[-1].get("kind"), "📰")


def market_badge():
    """시장 전체 뉴스가 진행 중이면 한 줄 설명, 아니면 빈 문자열."""
    effects = [e for e in active_effects if e["symbol"] is None]
    if not effects:
        return ""
    return "🌐 시장 호재 진행 중" if effects[-1].get("kind") == "market_good" else "🌐 시장 악재 진행 중"


def tick_effects():
    """1분 지남: 효과 남은 시간을 줄이고 끝난 효과를 지운다.
    상장폐지로 끝나는 부도 위기 종목 목록을 돌려준다. (stocks.update_stocks 가 상장폐지 처리)"""
    for e in active_effects:
        e["left"] -= 1
    doomed = [e["symbol"] for e in active_effects if e["left"] <= 0 and e.get("delist")]
    active_effects[:] = [e for e in active_effects if e["left"] > 0]
    return doomed


def follow_direction(direction):
    """점프 뒤 후속 움직임 방향. 점프와 같은 방향일 확률이 FOLLOW_SAME_CHANCE 라 거의 반반이다."""
    return direction if random.random() < FOLLOW_SAME_CHANCE else -direction


def stock_jump_size(symbol):
    """종목 뉴스 점프 크기 (변하기 쉬운 종목일수록 크다)"""
    base, per_vol = JUMP_SIZE
    return random.uniform(0.5, 1.5) * (base + stocks.stock_info[symbol]["vol"] * per_vol)


def delist_chance(symbol):
    """부도 위기가 상장폐지로 끝날 확률. 하루 변동성이 가장 낮은 종목이 DELIST_CHANCE[0], 가장 높은 종목이 [1]."""
    vols = [info["vol"] for info in stocks.stock_info.values()]
    low, high = min(vols), max(vols)
    ratio = (stocks.stock_info[symbol]["vol"] - low) / (high - low) if high > low else 0
    return DELIST_CHANCE[0] + (DELIST_CHANCE[1] - DELIST_CHANCE[0]) * ratio


async def make_news(kind=None):
    """뉴스 하나를 만들고 점프와 효과를 건다. (kind, symbol, headline, body) 를 돌려준다.
    가격을 바꾸므로 stocks.update_lock 을 잡은 상태에서 불러야 한다. (publish, %주식가속)"""
    if kind is None:
        kind = random.choices(list(KIND_WEIGHTS), weights=list(KIND_WEIGHTS.values()))[0]

    symbol = random.choice(list(stocks.stock_info)) if kind in ("good", "bad", "rumor", "default_risk") else None
    minutes = random.randint(*EFFECT_MINUTES)

    def add(drift, left=minutes, target=symbol, delist=False):
        active_effects.append({"symbol": target, "drift": drift, "left": left, "kind": kind, "delist": delist})

    if kind in ("good", "bad"):
        headline, body = random.choice(GOOD if kind == "good" else BAD)
        direction = 1 if kind == "good" else -1
        if random.random() < TWIST_CHANCE:
            direction = -direction  # 뒤통수: 기사와 반대로 움직인다
        await stocks.jump(symbol, direction * stock_jump_size(symbol))
        add(follow_direction(direction) * random.uniform(*STOCK_DRIFT))
    elif kind == "rumor":
        headline, body = random.choice(RUMOR)
        add(random.choice((1, -1)) * random.uniform(*RUMOR_DRIFT))
    elif kind in ("market_good", "market_bad"):
        headline, body = random.choice(MARKET_GOOD if kind == "market_good" else MARKET_BAD)
        direction = 1 if kind == "market_good" else -1
        await stocks.jump_all(direction * random.uniform(*MARKET_JUMP))
        add(follow_direction(direction) * random.uniform(*MARKET_DRIFT))
    elif kind == "bubble":
        headline, body = random.choice(BUBBLE)
        await stocks.set_override_state("HYPER_BULL", random.randint(*BUBBLE_MINUTES) * 60)
    else:  # default_risk
        headline, body = random.choice(DEFAULT_RISK)
        await stocks.jump(symbol, -random.uniform(*DEFAULT_RISK_JUMP))
        add(-random.uniform(*DEFAULT_RISK_DRIFT), left=random.randint(*DEFAULT_RISK_MINUTES),
            delist=random.random() < delist_chance(symbol))

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
    async with stocks.update_lock:  # 뉴스가 가격을 바꾸므로 1분 갱신 / %주식가속과 겹치지 않게
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


def minute_passed():
    """1분 지남. 뉴스를 낼 때가 됐으면 True 를 돌려주고 다음 뉴스까지 남은 분을 새로 정한다.
    (news_loop 와 %주식가속 이 같이 쓴다)"""
    global minutes_until_next
    minutes_until_next -= 1
    if minutes_until_next <= 0:
        minutes_until_next = random.randint(*NEWS_INTERVAL_MINUTES)
        return True
    return False


@tasks.loop(minutes=1)
async def news_loop():
    try:
        if minute_passed():
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
