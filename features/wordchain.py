"""끝말잇기: 봇과 끝말잇기를 해서 단어를 이을 때마다 돈을 번다.

    %끝말잇기       게임 시작 (봇이 먼저 단어를 낸다)
    게임 중 "그만"   여기까지 번 돈을 받고 끝내기

- 단어는 kkwords.txt (한 줄에 한 단어) 에 있는 한글 2글자 이상만 인정한다.
- 두음법칙을 쓸 수 있다. (예: 기술력 → 역사, 고려 → 여름)
- 시간 안에 못 내면 끝나지만, 그때까지 번 돈은 그대로 받는다. (잃는 건 없음)
- 단어 목록은 처음 게임을 시작할 때 한 번 읽어서 메모리에 둔다.
  (선착순 퀴즈의 초성 문제도 이 목록을 쓴다)
"""
import asyncio
import random
import re
import time
from pathlib import Path

import discord

import database as db
from bot import client
from fmt import debt_line, num

# ───────────── 밸런스 설정 ─────────────
TURN_SECONDS = 20             # 한 턴 제한 시간
WORD_REWARD_BASE = 200        # 첫 단어 보상
WORD_REWARD_STEP = 50         # 단어를 이을 때마다 늘어나는 보상
WORD_REWARD_MAX = 1000        # 단어 하나당 최대 보상 (17번째 단어부터)
DAILY_MAX = 15000             # 하루에 끝말잇기로 벌 수 있는 최대 금액
STOP_WORDS = {"그만", "포기", "ㅈㅈ", "gg"}

BOT_WORD_LENGTH = (2, 3)      # 봇이 내는 단어 길이 (길수록 처음 보는 단어가 많아서 짧게)
BOT_SAFE_MIN = 30             # 봇은 다음 사람이 이을 수 있는 단어가 이만큼 이상 있는 단어만 낸다 (한방단어 금지)

WORDS_PATH = Path(__file__).resolve().parent.parent / "kkwords.txt"


def word_reward(count):
    """count 번째로 이은 단어의 보상"""
    return min(WORD_REWARD_BASE + WORD_REWARD_STEP * (count - 1), WORD_REWARD_MAX)


# ───────────── 단어 사전 ─────────────
# 56만 단어를 set 으로 들고 있으면 메모리를 50MB 넘게 쓴다.
# 그래서 첫 글자별로 "\n단어1\n단어2\n...\n" 한 덩어리 문자열로 묶어 둔다. (약 7MB)
#   단어 확인: f"\n{단어}\n" in 덩어리
_buckets: dict[str, str] = {}
_counts: dict[str, int] = {}     # 첫 글자별 단어 수 (한방단어 판별용)
_load_lock = asyncio.Lock()


def _read_words():
    groups: dict[str, list[str]] = {}
    with open(WORDS_PATH, encoding="utf-8") as f:
        for line in f:
            word = line.strip()
            if re.fullmatch(r"[가-힣]{2,}", word):
                groups.setdefault(word[0], []).append(word)
    buckets = {c: "\n" + "\n".join(ws) + "\n" for c, ws in groups.items()}
    counts = {c: len(ws) for c, ws in groups.items()}
    return buckets, counts


async def load_words() -> bool:
    """단어 목록을 읽는다. 이미 읽었으면 바로 True, 파일이 없으면 False."""
    global _buckets, _counts
    if _buckets:
        return True
    async with _load_lock:
        if not _buckets:
            if not WORDS_PATH.exists():
                print(f"[끝말잇기] ❌ 단어 파일이 없습니다: {WORDS_PATH}")
                return False
            _buckets, _counts = await asyncio.to_thread(_read_words)
            print(f"[끝말잇기] 단어 {sum(_counts.values()):,}개 불러옴")
    return True


def is_word(word: str) -> bool:
    return bool(word) and f"\n{word}\n" in _buckets.get(word[0], "")


def words_starting_with(char: str) -> list[str]:
    return _buckets[char].strip("\n").split("\n") if char in _buckets else []


def random_word(lengths=(2, 3)) -> str:
    """사전에서 아무 단어나 하나 (퀴즈용)"""
    while True:
        bucket = random.choice(list(_buckets.values()))
        candidates = [w for w in bucket.strip("\n").split("\n") if len(w) in lengths]
        if candidates:
            return random.choice(candidates)


# ───────────── 한글 처리 ─────────────
# 한글 한 글자 = 0xAC00 + (초성 × 21 + 중성) × 28 + 종성
CHOSUNG = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_N, _R, _O = 2, 5, 11                  # 초성 번호: ㄴ, ㄹ, ㅇ
_YI_VOWELS = {2, 3, 6, 7, 12, 17, 20}  # ㅑ ㅒ ㅕ ㅖ ㅛ ㅠ ㅣ (ㄹ → ㅇ 이 되는 모음)
_N_YI_VOWELS = {6, 7, 12, 17, 20}      # ㅕ ㅖ ㅛ ㅠ ㅣ (ㄴ → ㅇ 이 되는 모음)


def chosung(word: str) -> str:
    return "".join(CHOSUNG[(ord(c) - 0xAC00) // 588] for c in word)


def dueum(char: str) -> str:
    """두음법칙을 적용한 글자. 해당 없으면 그대로. (력 → 역, 로 → 노, 녀 → 여)"""
    code = ord(char) - 0xAC00
    cho, rest = divmod(code, 588)
    jung = rest // 28
    if cho == _R:
        cho = _O if jung in _YI_VOWELS else _N
    elif cho == _N and jung in _N_YI_VOWELS:
        cho = _O
    else:
        return char
    return chr(0xAC00 + cho * 588 + rest)


def next_starts(word: str) -> set[str]:
    """word 다음에 올 단어가 시작할 수 있는 글자들"""
    last = word[-1]
    return {last, dueum(last)}


def continuations(word: str) -> int:
    return sum(_counts.get(c, 0) for c in next_starts(word))


def bot_pick(prev: str, used: set[str]) -> str | None:
    """봇이 낼 단어. 이을 단어가 없으면 None (봇 패배)."""
    candidates = []
    for start in next_starts(prev):
        candidates += [w for w in words_starting_with(start) if w not in used]
    if not candidates:
        return None
    low, high = BOT_WORD_LENGTH
    safe = [w for w in candidates if low <= len(w) <= high and continuations(w) >= BOT_SAFE_MIN]
    return random.choice(safe or candidates)


def start_hint(word: str) -> str:
    starts = next_starts(word)
    last = word[-1]
    return f"**{last}**" + (f" (또는 **{dueum(last)}**)" if len(starts) > 1 else "")


# ───────────── 게임 ─────────────
playing: set[int] = set()   # 지금 끝말잇기 중인 유저


async def earned_today(user_id) -> float:
    user = await db.get_user(user_id)
    return user["wordchain_earned"] if user["wordchain_date"] == db.today() else 0.0


async def pay(user_id, amount):
    """오늘 한도 안에서 지급한다. 실제로 지급한 금액과 receive 결과를 돌려준다."""
    today = db.today()
    async with db.user_tx(user_id) as conn:
        user = await db.get_user(user_id, conn)
        earned = user["wordchain_earned"] if user["wordchain_date"] == today else 0.0
        amount = max(0, min(amount, DAILY_MAX - earned))
        await db.update_user(user_id, conn, wordchain_date=today, wordchain_earned=earned + amount)
        result = await db.receive(user_id, amount, conn) if amount > 0 else {"collected": 0}
    return amount, result


@client.command(aliases=["끝말잇기", "끝말"])
async def wordchain(ctx):
    user_id = ctx.author.id
    if user_id in playing:
        await ctx.send(f"{ctx.author.mention} ❌ 이미 끝말잇기를 하고 있어요!")
        return

    remaining = DAILY_MAX - await earned_today(user_id)
    if remaining <= 0:
        await ctx.send(
            f"{ctx.author.mention} ❌ 오늘은 끝말잇기로 **{num(DAILY_MAX)} byte**를 모두 벌었어요. "
            "내일 다시 도전하세요!"
        )
        return

    if not await load_words():
        await ctx.send("❌ 단어 목록 파일(kkwords.txt)이 없어서 끝말잇기를 할 수 없어요. 관리자에게 알려주세요.")
        return

    playing.add(user_id)
    try:
        await play(ctx, remaining)
    finally:
        playing.discard(user_id)


async def play(ctx, remaining):
    user = ctx.author
    used: set[str] = set()
    count = 0
    earned = 0

    word = random_word(lengths=(2, 3))
    while continuations(word) < BOT_SAFE_MIN:
        word = random_word(lengths=(2, 3))
    used.add(word)

    embed = discord.Embed(
        title="🔤 끝말잇기 시작!",
        description=(
            f"🤖 **{word}**\n\n"
            f"{start_hint(word)}(으)로 시작하는 단어를 입력하세요. (턴당 {TURN_SECONDS}초)\n"
            f"단어를 이을 때마다 **{num(WORD_REWARD_BASE)} byte**부터 점점 더 벌어요. "
            f"`그만`을 입력하면 번 돈을 받고 끝나요."
        ),
        color=discord.Color.blurple(),
    )
    embed.set_footer(text=f"오늘 끝말잇기로 더 벌 수 있는 돈: {num(remaining)} byte")
    await ctx.send(user.mention, embed=embed)

    def check(m: discord.Message):
        return (
            m.author.id == user.id
            and m.channel.id == ctx.channel.id
            and not m.content.startswith(client.command_prefix)
        )

    end_reason = None
    while end_reason is None:
        deadline = time.monotonic() + TURN_SECONDS
        while True:
            try:
                msg = await client.wait_for("message", check=check, timeout=deadline - time.monotonic())
            except asyncio.TimeoutError:
                end_reason = f"⏰ 시간 초과! 봇의 단어는 **{word}** 였어요."
                break

            text = msg.content.strip()
            if text.lower() in STOP_WORDS:
                end_reason = "🛑 그만하기를 선택했어요."
                break

            starts = next_starts(word)
            if not re.fullmatch(r"[가-힣]{2,}", text):
                error = "한글 2글자 이상만 낼 수 있어요."
            elif text[0] not in starts:
                error = f"{start_hint(word)}(으)로 시작해야 해요."
            elif text in used:
                error = "이미 나온 단어예요."
            elif not is_word(text):
                error = "사전에 없는 단어예요."
            else:
                break
            left = max(0, int(deadline - time.monotonic()))
            await msg.reply(f"❌ {error} (남은 시간 {left}초)", mention_author=False)

        if end_reason:
            break

        # 유저가 단어를 이었다
        used.add(text)
        count += 1
        reward = min(word_reward(count), remaining - earned)
        earned += reward
        if earned >= remaining:
            end_reason = f"🎯 오늘 끝말잇기 한도(**{num(DAILY_MAX)} byte**)를 다 채웠어요!"
            break

        word = bot_pick(text, used)
        if word is None:
            end_reason = f"🏆 봇이 **{text}**에 이을 단어를 못 찾았어요. 당신의 승리!"
            break
        used.add(word)

        await msg.reply(
            f"✅ +{num(reward)} byte (누적 **{num(earned)}**, {count}단어)\n"
            f"🤖 **{word}** → {start_hint(word)}",
            mention_author=False,
        )

    paid, result = await pay(user.id, earned) if earned > 0 else (0, {"collected": 0})

    embed = discord.Embed(
        title="🔤 끝말잇기 끝!",
        description=end_reason + debt_line(result["collected"]),
        color=discord.Color.green() if paid > 0 else discord.Color.light_grey(),
    )
    embed.add_field(name="📝 이은 단어", value=f"{count}개", inline=True)
    embed.add_field(name="💰 받은 돈", value=f"{num(paid)} byte", inline=True)
    embed.set_author(name=str(user), icon_url=user.avatar.url if user.avatar else None)
    await ctx.send(embed=embed)
