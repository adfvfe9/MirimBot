"""끝말잇기: 봇과 끝말잇기를 해서 단어를 이을 때마다 돈을 번다.

    %끝말잇기         봇과 1대1 (난이도 버튼: 쉬움 / 보통 / 어려움 / 지옥, 연습 모드 켜기)
    %끝말잇기 연습    봇과 1대1 연습 (보상 없음, 하루 한도와 상관없이)
    %끝말잇기 같이    친구들과 다같이 (대기방에서 모여서 시작, 마지막까지 남으면 우승)
    %끝말잇기랭킹 [어려움|지옥]   봇과 1대1 한 판 최고 점수 랭킹 (어려움 / 지옥만)
    게임 중 "그만"     1대1: 번 돈을 받고 끝내기 / 다같이: 기권

- 게임은 명령어 메시지에 새 스레드를 만들어서 그 안에서 한다. 끝나면 스레드를 잠근다.

- 단어는 kkwords.txt (한 줄에 한 단어) 에 있는 한글 2글자 이상만 인정한다.
- 두음법칙을 쓸 수 있다. (예: 기술력 → 역사, 고려 → 여름)
- 시간 안에 못 내면 끝나지만, 그때까지 번 돈은 그대로 받는다. (잃는 건 없음)
- 보상 = 기본 보상(단어를 이을수록 커짐) × 글자 수 보너스 × 난이도 배율 + 미션 글자 보너스
  하루 보상 한도를 채우면 계속할지 물어본다. 계속하면 보상 없이 점수만 쌓인다.
- 점수(랭킹용, 돈과 별개) = 턴 점수(오래 이을수록 커짐) × 글자 수 보너스 × 속도 보너스 + 미션 점수
  어려움 / 지옥에서 연습이 아닐 때만 한 판 최고 점수가 랭킹에 기록된다.
- 미션 글자는 한 단어에 들어간 횟수만큼 전부 보너스. (예: 미션 '가'에 가가가가 → 4번)
- 봇은 어려울수록 "다음 사람이 이을 단어가 적은" 단어를 낸다.
  다만 어떤 난이도든 한방단어(이을 단어가 하나도 없는 단어)는 그것밖에 없을 때만 낸다.
  유저는 한방단어를 내도 된다. (봇이 못 이으면 유저 승리 + 승리 보너스)
- 단어 목록은 처음 게임을 시작할 때 한 번 읽어서 메모리에 둔다.
  (선착순 퀴즈의 초성 문제도 이 목록을 쓴다)
"""
import asyncio
import random
import re
import time
from collections import Counter
from pathlib import Path

import discord

import database as db
import respond
from bot import client
from features import abilities
from fmt import debt_line, num

# ───────────── 밸런스 설정 ─────────────
TURN_SECONDS = 20             # 한 턴 제한 시간
WORD_REWARD_BASE = 200        # 첫 단어 기본 보상
WORD_REWARD_STEP = 50         # 단어를 이을 때마다 늘어나는 기본 보상
WORD_REWARD_MAX = 1000        # 단어 하나당 최대 기본 보상 (17번째 단어부터)
LENGTH_BONUS = 0.25           # 2글자보다 한 글자 길 때마다 +25% (3글자 1.25배, 4글자 1.5배 ...)
LENGTH_BONUS_MAX_LETTERS = 8  # 글자 수 보너스는 8글자(2.5배)까지
MISSION_BONUS = 300           # 미션 글자 하나당 보너스 (× 난이도 배율)
MISSION_CHARS = "가나다라마바사아자차카타파하고기리이지시도수주우무부미비소오조정상전대"
WIN_BONUS = 2000              # 봇이 이을 단어를 못 찾으면 (× 난이도 배율)
DAILY_MAX = 15000             # 하루에 끝말잇기로 벌 수 있는 최대 금액
CONTINUE_SECONDS = 30         # 보상 한도를 채웠을 때 "계속할까요?" 버튼을 기다리는 시간

# 점수 (랭킹용, 돈과 별개)
SCORE_TURN_BASE = 10          # 첫 단어 턴 점수
SCORE_TURN_STEP = 2           # 단어를 이을 때마다 늘어나는 턴 점수 (상한 없음)
SCORE_SPEED_MAX = 1.0         # 바로 내면 ×2, 시간이 끝날 때쯤 내면 ×1 (남은 시간 비율만큼)
SCORE_MISSION = 30            # 미션 글자 하나당 점수
SCORE_WIN = 100               # 봇이 이을 단어를 못 찾으면
RANKED = ("hard", "hell")     # 랭킹에 기록되는 난이도
STOP_WORDS = {"그만", "포기", "ㅈㅈ", "gg"}
PRACTICE_WORDS = {"연습"}     # %끝말잇기 연습 → 연습 모드가 켜진 채로 시작

# 봇 난이도
#   mult         보상 배율
#   safe_min     평소에는 다음 사람이 이을 단어가 이만큼 이상 있는 단어만 낸다
#   nasty        이 확률로 "이을 단어가 가장 적은 쪽" 단어를 고른다 (지옥은 항상 가장 적은 단어)
#   short        True 면 2~3글자 단어 위주로 낸다 (긴 단어는 처음 보는 게 많아서)
DIFFICULTIES = {
    "easy":   {"name": "쉬움",   "emoji": "🟢", "mult": 0.05, "safe_min": 100, "nasty": 0.0, "short": True},
    "normal": {"name": "보통",   "emoji": "🟡", "mult": 0.5,  "safe_min": 30,  "nasty": 0.1, "short": True},
    "hard":   {"name": "어려움", "emoji": "🟠", "mult": 1.0,  "safe_min": 10,  "nasty": 0.5, "short": False},
    "hell":   {"name": "지옥",   "emoji": "🔴", "mult": 2.0,  "safe_min": 1,   "nasty": 1.0, "short": False},
}
NASTY_TOP = 0.05              # "이을 단어가 적은 쪽" = 후보 중 하위 5%
CHOOSE_SECONDS = 60           # 난이도 고르는 시간

MULTI_WORDS = {"같이", "다같이", "멀티", "친구"}   # %끝말잇기 <이 단어> → 다같이 모드
MULTI_MIN_PLAYERS = 2
MULTI_MAX_PLAYERS = 8
MULTI_WIN_BONUS = 1000        # 우승 보너스: (참가자 수 - 1) × 이 금액
LOBBY_SECONDS = 120           # 대기방이 열려 있는 시간

WORDS_PATH = Path(__file__).resolve().parent.parent / "kkwords.txt"


def length_factor(length):
    """글자 수 보너스: 2글자 ×1, 한 글자 길 때마다 +LENGTH_BONUS (최대 LENGTH_BONUS_MAX_LETTERS 글자까지)"""
    return 1 + LENGTH_BONUS * (min(length, LENGTH_BONUS_MAX_LETTERS) - 2)


def mission_hits(word, mission):
    """단어에 미션 글자가 몇 번 들어갔는지 (들어간 만큼 전부 센다. 가가가가 → 4)"""
    return word.count(mission)


def word_score(count, word, elapsed, hits):
    """count 번째로 이은 단어의 점수. elapsed: 그 턴에서 단어를 내기까지 걸린 초"""
    turn = SCORE_TURN_BASE + SCORE_TURN_STEP * (count - 1)
    speed = 1 + SCORE_SPEED_MAX * max(0.0, TURN_SECONDS - elapsed) / TURN_SECONDS
    return round(turn * length_factor(len(word)) * speed) + SCORE_MISSION * hits


def word_reward(count, length=2, mult=1.0):
    """count 번째로 이은 length 글자 단어의 보상"""
    base = min(WORD_REWARD_BASE + WORD_REWARD_STEP * (count - 1), WORD_REWARD_MAX)
    return round(base * length_factor(length) * mult)


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


def continuations(word: str, used_starts: Counter | None = None) -> int:
    """word 다음에 이을 수 있는 단어 수. used_starts(이미 나온 단어의 첫 글자 수)를 주면 그만큼 뺀다."""
    total = 0
    for c in next_starts(word):
        total += _counts.get(c, 0) - (used_starts[c] if used_starts else 0)
    return total


def pick_word(candidates: list[str], difficulty: str, used: set[str]) -> str:
    """난이도에 맞게 candidates 중 하나를 고른다. (candidates 는 비어 있지 않아야 한다)"""
    d = DIFFICULTIES[difficulty]
    used_starts = Counter(u[0] for u in used)
    # 고른 단어 자신도 나온 단어가 되므로, 자기 끝 글자로 시작하는 단어(예: 둬둬)면 1 을 더 뺀다
    scored = [(continuations(w, used_starts) - (w[0] in next_starts(w)), w) for w in candidates]

    # 한방단어는 그것밖에 없을 때만
    alive = [(n, w) for n, w in scored if n > 0]
    if not alive:
        return random.choice(candidates)

    if d["short"]:
        alive = [(n, w) for n, w in alive if len(w) <= 3] or alive

    if difficulty == "hell":
        least = min(n for n, _ in alive)
        return random.choice([w for n, w in alive if n == least])

    if random.random() < d["nasty"]:
        alive.sort()
        return random.choice(alive[:max(1, int(len(alive) * NASTY_TOP))])[1]

    safe = [w for n, w in alive if n >= d["safe_min"]]
    return random.choice(safe or [w for _, w in alive])


def bot_pick(prev: str, used: set[str], difficulty: str = "normal") -> str | None:
    """봇이 낼 단어. 이을 단어가 없으면 None (봇 패배)."""
    candidates = []
    for start in next_starts(prev):
        candidates += [w for w in words_starting_with(start) if w not in used]
    if not candidates:
        return None
    return pick_word(candidates, difficulty, used)


def start_hint(word: str) -> str:
    starts = next_starts(word)
    last = word[-1]
    return f"**{last}**" + (f" (또는 **{dueum(last)}**)" if len(starts) > 1 else "")




# ───────────── 게임 공통 ─────────────
playing: set[int] = set()   # 지금 끝말잇기 중이거나 대기방에 있는 유저


async def daily_max(user_id, conn=None) -> float:
    """하루 끝말잇기 보상 한도 (🔤 끝말잇기 보상 능력만큼 늘어난다)"""
    return DAILY_MAX * (1 + await abilities.total(user_id, "wordchain_bonus", conn) / 100)


async def player_bonus(user_id):
    """(보상 배율, 한 턴 제한 시간) — 🔤 끝말잇기 보상 / ⌛ 끝말잇기 시간 능력"""
    bonus = await abilities.totals(user_id)
    return 1 + bonus.get("wordchain_bonus", 0) / 100, TURN_SECONDS + bonus.get("wordchain_time", 0)


async def remaining_today(user_id) -> float:
    """오늘 끝말잇기로 더 벌 수 있는 돈"""
    user = await db.get_user(user_id)
    earned = user["wordchain_earned"] if user["wordchain_date"] == db.today() else 0.0
    return max(0.0, await daily_max(user_id) - earned)


async def pay(user_id, amount):
    """오늘 한도 안에서 지급한다. 실제로 지급한 금액과 receive 결과를 돌려준다."""
    if amount <= 0:
        return 0, {"collected": 0}
    today = db.today()
    async with db.user_tx(user_id) as conn:
        user = await db.get_user(user_id, conn)
        earned = user["wordchain_earned"] if user["wordchain_date"] == today else 0.0
        amount = max(0, min(amount, await daily_max(user_id, conn) - earned))
        await db.update_user(user_id, conn, wordchain_date=today, wordchain_earned=earned + amount)
        result = await db.receive(user_id, amount, conn) if amount > 0 else {"collected": 0}
        await db.log_money(user_id, "wordchain", amount, conn=conn)
    return amount, result


def first_word(difficulty: str = "normal") -> str:
    """게임을 시작할 단어. 아무 글자나 하나 골라서, 그 글자로 시작하는 2~3글자 단어 중 난이도에 맞게."""
    char = random.choice([c for c, n in _counts.items() if n >= 200])
    candidates = [w for w in words_starting_with(char) if len(w) <= 3]
    return pick_word(candidates, difficulty, set())


async def open_thread(message: discord.Message, name: str):
    """게임용 스레드를 만든다. (채널, 새로 만들었는지)
    이미 스레드 안이거나 권한이 없어서 못 만들면 그 채널에서 그대로 한다."""
    if isinstance(message.channel, discord.Thread):
        return message.channel, False
    try:
        return await message.create_thread(name=name[:100], auto_archive_duration=60), True
    except discord.HTTPException as e:
        print(f"[끝말잇기] 스레드 생성 실패, 채널에서 진행: {type(e).__name__}: {e}")
        return message.channel, False


async def close_thread(thread, created: bool):
    """게임이 끝난 스레드를 보관하고 잠근다. (잠그기는 스레드 관리 권한이 있어야 해서 실패하면 보관만)"""
    if not created:
        return
    try:
        await thread.edit(archived=True, locked=True)
    except discord.HTTPException:
        try:
            await thread.edit(archived=True)
        except discord.HTTPException:
            pass


async def take_turn(channel, player, word, used, seconds=TURN_SECONDS):
    """player 가 word 에 이을 단어를 낼 때까지 기다린다. (결과, 단어, 메시지, 걸린 초)
    ("ok", 단어, 메시지, 초) / ("timeout", None, None, None) / ("stop", None, 메시지, None)"""

    def check(m: discord.Message):
        return (
            m.author.id == player.id
            and m.channel.id == channel.id
            and not m.content.startswith(client.command_prefix)
        )

    started = time.monotonic()
    deadline = started + seconds
    while True:
        try:
            msg = await client.wait_for("message", check=check, timeout=deadline - time.monotonic())
        except asyncio.TimeoutError:
            return "timeout", None, None, None

        text = msg.content.strip()
        if text.lower() in STOP_WORDS:
            return "stop", None, msg, None

        if not re.fullmatch(r"[가-힣]{2,}", text):
            error = "한글 2글자 이상만 낼 수 있어요."
        elif text[0] not in next_starts(word):
            error = f"{start_hint(word)}(으)로 시작해야 해요."
        elif text in used:
            error = "이미 나온 단어예요."
        elif not is_word(text):
            error = "사전에 없는 단어예요."
        else:
            return "ok", text, msg, time.monotonic() - started
        left = max(0, int(deadline - time.monotonic()))
        await msg.reply(f"❌ {error} (남은 시간 {left}초)", mention_author=False)


async def check_can_play(ctx) -> bool:
    if ctx.author.id in playing:
        await ctx.send(f"{ctx.author.mention} ❌ 이미 끝말잇기를 하고 있어요!")
        return False
    if not await load_words():
        await ctx.send("❌ 단어 목록 파일(kkwords.txt)이 없어서 끝말잇기를 할 수 없어요. 관리자에게 알려주세요.")
        return False
    return True


@client.command(aliases=["끝말잇기", "끝말"])
async def wordchain(ctx, mode: str = None):
    """%끝말잇기 → 봇과 1대1, %끝말잇기 연습 → 1대1 연습, %끝말잇기 같이 → 친구들과 다같이"""
    if mode in MULTI_WORDS:
        await multi_lobby(ctx)
    else:
        await solo(ctx, practice=mode in PRACTICE_WORDS)


# ───────────── 봇과 1대1 ─────────────

class DifficultyView(discord.ui.View):
    """난이도 버튼 4개 + 연습 모드 켜기/끄기"""

    def __init__(self, user, remaining, practice=False):
        super().__init__(timeout=CHOOSE_SECONDS)
        self.user = user
        self.remaining = remaining
        self.practice = practice
        self.choice = None
        self.message: discord.Message | None = None
        for key, d in DIFFICULTIES.items():
            button = discord.ui.Button(label=d["name"], emoji=d["emoji"], style=discord.ButtonStyle.primary, row=0)
            button.callback = self.make_callback(key)
            self.add_item(button)
        self.update_practice_button()

    def update_practice_button(self):
        self.toggle_practice.label = f"연습 모드: {'켜짐' if self.practice else '꺼짐'}"
        self.toggle_practice.style = discord.ButtonStyle.success if self.practice else discord.ButtonStyle.secondary

    def embed(self, footer=None):
        lines = []
        for d in DIFFICULTIES.values():
            first = word_reward(1, 2, d["mult"])
            lines.append(f"{d['emoji']} **{d['name']}** — 보상 ×{d['mult']:g} (첫 단어 {num(first)} byte~)")
        embed = discord.Embed(
            title="🔤 끝말잇기 — 난이도를 고르세요" + (" (🧪 연습)" if self.practice else ""),
            description=(
                "\n".join(lines) + "\n\n"
                "어려울수록 봇이 **이을 단어가 적은 단어**를 내요. 대신 보상도 커요!\n"
                f"📏 긴 단어일수록 보상 UP (한 글자당 +{LENGTH_BONUS:.0%})\n"
                f"🎯 **미션 글자**가 들어간 단어를 내면 추가 보너스\n"
                f"🏆 봇이 못 이으면 승리 보너스 ({num(WIN_BONUS)} × 배율)\n"
                "⭐ 🟠어려움 · 🔴지옥은 **점수**가 랭킹에 기록돼요 (`%끝말잇기랭킹`)\n"
                "　 오래 이을수록 · 긴 단어일수록 · 빨리 낼수록 · 미션 글자를 넣을수록 점수 UP\n\n"
                + ("🧪 **연습 모드**: 보상이 없고 랭킹에도 기록되지 않아요."
                   if self.practice else
                   f"💰 오늘 더 벌 수 있는 돈: **{num(self.remaining)} byte**" if self.remaining > 0 else
                   "💰 오늘 보상은 다 받았어요. 해도 **점수만** 쌓여요.")
            ),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=footer or f"{CHOOSE_SECONDS}초 안에 골라 주세요.")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await respond.reply(interaction, "❌ 다른 사람의 끝말잇기예요. `%끝말잇기`로 직접 시작하세요!", ephemeral=True)
            return False
        return True

    def make_callback(self, key):
        async def callback(interaction: discord.Interaction):
            self.choice = key
            d = DIFFICULTIES[key]
            for item in self.children:
                item.disabled = True
            await respond.edit(
                interaction,
                embed=self.embed(f"{d['emoji']} {d['name']}{' (연습)' if self.practice else ''} 선택! 스레드에서 시작해요."),
                view=self,
            )
            self.stop()
        return callback

    @discord.ui.button(label="연습 모드", emoji="🧪", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_practice(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.practice = not self.practice
        self.update_practice_button()
        await respond.edit(interaction, embed=self.embed(), view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(embed=self.embed("⏰ 시간이 지나 닫혔어요."), view=self)
            except discord.HTTPException:
                pass


async def solo(ctx, practice=False):
    user = ctx.author
    if not await check_can_play(ctx):
        return

    playing.add(user.id)
    try:
        view = DifficultyView(user, await remaining_today(user.id), practice)
        view.message = await ctx.send(embed=view.embed(), view=view)
        await view.wait()
        if view.choice is None:
            return
        d = DIFFICULTIES[view.choice]
        label = f"{d['name']}{' 연습' if view.practice else ''}"
        thread, created = await open_thread(view.message, f"🔤 {user.display_name}의 끝말잇기 ({label})")
        await play_solo(thread, user, view.remaining, view.choice, view.practice)
        await close_thread(thread, created)
    finally:
        playing.discard(user.id)


def new_mission(old=None) -> str:
    return random.choice([c for c in MISSION_CHARS if c != old])


class ContinueView(discord.ui.View):
    """하루 보상 한도를 채웠을 때: 점수만 쌓으며 계속할지"""

    def __init__(self, user):
        super().__init__(timeout=CONTINUE_SECONDS)
        self.user = user
        self.keep_going = False
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await respond.reply(interaction, "❌ 다른 사람의 끝말잇기예요.", ephemeral=True)
            return False
        return True

    async def finish(self, interaction, keep_going):
        self.keep_going = keep_going
        for item in self.children:
            item.disabled = True
        await respond.edit(interaction, view=self)
        self.stop()

    @discord.ui.button(label="계속하기 (점수만)", emoji="▶️", style=discord.ButtonStyle.success)
    async def go(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.finish(interaction, True)

    @discord.ui.button(label="그만하기", emoji="🛑", style=discord.ButtonStyle.danger)
    async def quit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.finish(interaction, False)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


def turn_embed(count, word, elapsed, points, score, money_text, mission, hits, mission_money):
    """유저가 단어를 이었을 때 보여 줄 결과"""
    embed = discord.Embed(title=f"✅ {count}단어째 — {word}", color=discord.Color.green())
    embed.add_field(name="⭐ 점수", value=f"+{points:,} (총 **{score:,}**)", inline=True)
    embed.add_field(name="⚡ 입력 시간", value=f"{elapsed:.1f}초", inline=True)
    embed.add_field(name="💰 보상", value=money_text, inline=True)
    if hits:
        embed.add_field(
            name="🎯 미션 성공!",
            value=f"**{mission}** ×{hits} → +{SCORE_MISSION * hits}점"
                  + (f", +{num(mission_money)} byte" if mission_money else ""),
            inline=False,
        )
    return embed


def add_bot_word(embed, word, mission, seconds=TURN_SECONDS):
    embed.add_field(name="🤖 봇의 단어", value=f"**{word}**  →  {start_hint(word)}(으)로 시작", inline=False)
    embed.set_footer(text=f"🎯 미션 글자: {mission}  ·  ⏱️ {seconds}초 안에 입력")
    return embed


async def play_solo(channel, user, remaining, difficulty="normal", practice=False):
    d = DIFFICULTIES[difficulty]
    ranked = difficulty in RANKED and not practice
    reward_mult, seconds = await player_bonus(user.id)
    mult = d["mult"] * reward_mult
    if ranked:
        seconds = TURN_SECONDS  # 랭킹 판은 공평하게 ⌛ 끝말잇기 시간 능력을 쓰지 않는다
    used: set[str] = set()
    count = 0
    earned = 0
    score = 0
    mission = new_mission()
    capped = not practice and remaining <= 0   # 오늘 보상 한도를 다 채웠는지

    def gain(amount):
        """한도 안에서 번 돈에 더하고, 실제로 더한 금액을 돌려준다. (연습이면 0)"""
        nonlocal earned
        if practice:
            return 0
        amount = max(0, min(amount, remaining - earned))
        earned += amount
        return amount

    word = first_word(difficulty)
    used.add(word)

    if practice:
        money_line = "🧪 연습 모드라 보상이 없고 랭킹에도 기록되지 않아요."
    elif capped:
        money_line = "💰 오늘 보상은 다 받았어요. **점수만** 쌓여요."
    else:
        money_line = "💰 단어가 길수록, 오래 이을수록 보상이 커져요."
    embed = discord.Embed(
        title=f"🔤 끝말잇기 시작! {d['emoji']} {d['name']}" + (" (🧪 연습)" if practice else ""),
        description=(
            f"🤖 **{word}**\n\n"
            f"{start_hint(word)}(으)로 시작하는 단어를 입력하세요. (턴당 {seconds}초)\n"
            f"🎯 미션 글자: **{mission}** — 들어간 단어를 내면 보너스!\n"
            f"{money_line}\n"
            + ("⭐ 이 판의 점수는 **랭킹**에 기록돼요. 빨리 낼수록 점수 UP!\n" if ranked else "")
            + "`그만`을 입력하면 끝나요."
        ),
        color=discord.Color.blurple(),
    )
    if not practice and not capped:
        embed.set_footer(text=f"오늘 끝말잇기로 더 벌 수 있는 돈: {num(remaining)} byte")
    await channel.send(user.mention, embed=embed)

    while True:
        status, text, msg, elapsed = await take_turn(channel, user, word, used, seconds)
        if status == "timeout":
            end_reason = f"⏰ 시간 초과! 봇의 단어는 **{word}** 였어요."
            break
        if status == "stop":
            end_reason = "🛑 그만하기를 선택했어요."
            break

        used.add(text)
        count += 1
        hits = mission_hits(text, mission)
        points = word_score(count, text, elapsed, hits)
        score += points
        reward = gain(word_reward(count, len(text), mult))
        mission_money = gain(MISSION_BONUS * hits * mult) if hits else 0
        if practice:
            money_text = "연습 (없음)"
        elif capped:
            money_text = "한도 도달 (점수만)"
        else:
            money_text = f"+{num(reward + mission_money)} byte\n(누적 {num(earned)})"
        turn = turn_embed(count, text, elapsed, points, score, money_text, mission, hits, mission_money)
        if hits:
            mission = new_mission(mission)

        # 이번 단어로 오늘 보상 한도를 다 채웠으면 계속할지 물어본다
        if not practice and not capped and earned >= remaining:
            capped = True
            turn.add_field(
                name="🎉 오늘 보상 한도 달성!",
                value=(
                    f"오늘 끝말잇기로 받을 수 있는 **{num(await daily_max(user.id))} byte**를 다 채웠어요.\n"
                    "계속하면 **보상 없이 점수만** 쌓여요." + (" (랭킹 기록 O)" if ranked else "")
                ),
                inline=False,
            )
            view = ContinueView(user)
            view.message = await msg.reply(embed=turn, view=view, mention_author=False)
            await view.wait()
            if not view.keep_going:
                end_reason = "🎉 오늘 보상 한도를 다 채우고 끝냈어요."
                break
            turn = None   # 결과는 이미 보냈으니 봇의 단어만 따로 보낸다

        word = bot_pick(text, used, difficulty)
        if word is None:
            score += SCORE_WIN
            bonus = gain(WIN_BONUS * mult)
            if turn:
                await msg.reply(embed=turn, mention_author=False)
            end_reason = (
                f"🏆 봇이 **{text}**에 이을 단어를 못 찾았어요. 당신의 승리! (+{SCORE_WIN}점"
                + (f", +{num(bonus)} byte)" if bonus else ")")
            )
            break
        used.add(word)

        if turn:
            await msg.reply(embed=add_bot_word(turn, word, mission, seconds), mention_author=False)
        else:
            resume = discord.Embed(title="▶️ 계속! (점수만)", color=discord.Color.blurple())
            await channel.send(embed=add_bot_word(resume, word, mission, seconds))

    paid, result = (0, {"collected": 0}) if practice else await pay(user.id, earned)
    record = await db.record_wordchain(user.id, difficulty, score, count) if ranked and score > 0 else None

    embed = discord.Embed(
        title=f"🔤 끝말잇기 끝! {d['emoji']} {d['name']}" + (" (🧪 연습)" if practice else ""),
        description=end_reason + debt_line(result["collected"]),
        color=discord.Color.green() if paid > 0 else discord.Color.light_grey(),
    )
    embed.add_field(name="📝 이은 단어", value=f"{count}개", inline=True)
    embed.add_field(name="⭐ 점수", value=f"{score:,}점", inline=True)
    embed.add_field(name="💰 받은 돈", value="연습 (없음)" if practice else f"{num(paid)} byte", inline=True)
    if record:
        embed.add_field(
            name=f"🏆 {d['name']} 랭킹",
            value=(f"**최고 기록 갱신!** 현재 **{record['rank']}위**" if record["new_best"] else
                   f"최고 기록 {record['best']:,}점 · 현재 {record['rank']}위"),
            inline=False,
        )
    elif practice:
        embed.set_footer(text="연습 모드는 랭킹에 기록되지 않아요.")
    elif difficulty not in RANKED:
        embed.set_footer(text="🟠어려움 · 🔴지옥에서 하면 점수가 랭킹에 기록돼요. (%끝말잇기랭킹)")
    embed.set_author(name=str(user), icon_url=user.avatar.url if user.avatar else None)
    await channel.send(embed=embed)


# ───────────── 랭킹 ─────────────
MEDALS = ["🥇", "🥈", "🥉"]


@client.command(aliases=["끝말잇기랭킹", "끝말랭킹"])
async def wordchain_rank(ctx, level: str = None):
    """%끝말잇기랭킹 [어려움|지옥] — 생략하면 둘 다"""
    await ctx.message.delete()
    keys = [k for k in RANKED if level in (None, DIFFICULTIES[k]["name"])]
    if not keys:
        names = " / ".join(DIFFICULTIES[k]["name"] for k in RANKED)
        await ctx.send(f"❌ 랭킹은 {names}만 있어요. 예) `%끝말잇기랭킹 지옥`", delete_after=10)
        return

    embed = discord.Embed(
        title="🏆 끝말잇기 랭킹",
        description=(
            "봇과 1대1 **한 판 최고 점수** 기준이에요. (어려움 · 지옥만, 연습 제외)\n"
            "오래 이을수록 · 긴 단어일수록 · 빨리 낼수록 · 미션 글자를 넣을수록 점수 UP"
        ),
        color=discord.Color.gold(),
    )
    for key in keys:
        d = DIFFICULTIES[key]
        lines = []
        for i, row in enumerate(await db.top_wordchain(key, 10), start=1):
            member = ctx.guild.get_member(row["user_id"]) if ctx.guild else None
            name = member.display_name if member else f"알 수 없음 ({row['user_id']})"
            medal = MEDALS[i - 1] if i <= len(MEDALS) else f"{i}위"
            lines.append(f"{medal} {name} — **{row['best_score']:,}점** ({row['best_words']}단어)")
        embed.add_field(name=f"{d['emoji']} {d['name']}", value="\n".join(lines) or "아직 기록이 없어요.", inline=False)
    await ctx.send(embed=embed)


# ───────────── 친구들과 다같이 ─────────────
# 대기방에서 [참가]로 모이고, 방장이 [시작]을 누르면 스레드에서 순서대로 단어를 잇는다.
# 시간 안에 못 내거나 `그만`을 치면 탈락. 마지막까지 남은 사람이 우승.
# 보상: 단어마다 1대1과 같은 보상(사람마다 따로 늘어남) + 우승 보너스. 모두 각자의 하루 한도 안에서.

class LobbyView(discord.ui.View):
    def __init__(self, host: discord.Member):
        super().__init__(timeout=LOBBY_SECONDS)
        self.host = host
        self.players: list[discord.Member] = [host]
        self.started = False
        self.message: discord.Message | None = None

    def embed(self, footer=None):
        embed = discord.Embed(
            title="🔤 다같이 끝말잇기 — 참가자 모집 중!",
            description=(
                f"[참가]를 눌러 들어오세요. 방장({self.host.mention})이 [시작]을 누르면 스레드에서 시작해요.\n"
                f"순서대로 단어를 잇고, {TURN_SECONDS}초 안에 못 내면 탈락! 마지막까지 남으면 우승.\n\n"
                f"💰 단어마다 **{num(WORD_REWARD_BASE)} byte**부터 (사람마다 따로 늘어남, 긴 단어일수록 UP)\n"
                f"🏆 우승 보너스: **(참가자 수 - 1) × {num(MULTI_WIN_BONUS)} byte**"
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name=f"👥 참가자 ({len(self.players)}/{MULTI_MAX_PLAYERS})",
            value="\n".join(p.mention for p in self.players),
            inline=False,
        )
        embed.set_footer(text=footer or (
            f"{MULTI_MIN_PLAYERS}명부터 시작할 수 있어요. 보상은 각자 하루 한도 {num(DAILY_MAX)} byte 안에서"
        ))
        return embed

    def joined(self, user) -> bool:
        return any(p.id == user.id for p in self.players)

    @discord.ui.button(label="참가", emoji="🙋", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if self.joined(user):
            await respond.reply(interaction, "이미 참가했어요!", ephemeral=True)
        elif user.id in playing:
            await respond.reply(interaction, "❌ 이미 다른 끝말잇기를 하고 있어요.", ephemeral=True)
        elif len(self.players) >= MULTI_MAX_PLAYERS:
            await respond.reply(interaction, f"❌ 최대 {MULTI_MAX_PLAYERS}명까지예요.", ephemeral=True)
        else:
            self.players.append(user)
            playing.add(user.id)
            await respond.edit(interaction, embed=self.embed(), view=self)

    @discord.ui.button(label="나가기", emoji="🚪", style=discord.ButtonStyle.secondary)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if user.id == self.host.id:
            await respond.reply(interaction, "방장은 나갈 수 없어요. [취소]를 눌러 주세요.", ephemeral=True)
        elif not self.joined(user):
            await respond.reply(interaction, "참가하지 않았어요.", ephemeral=True)
        else:
            self.players = [p for p in self.players if p.id != user.id]
            playing.discard(user.id)
            await respond.edit(interaction, embed=self.embed(), view=self)

    @discord.ui.button(label="시작", emoji="▶️", style=discord.ButtonStyle.primary)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host.id:
            await respond.reply(interaction, "방장만 시작할 수 있어요.", ephemeral=True)
        elif len(self.players) < MULTI_MIN_PLAYERS:
            await respond.reply(interaction, f"❌ {MULTI_MIN_PLAYERS}명 이상 모여야 시작할 수 있어요.", ephemeral=True)
        else:
            self.started = True
            await self.close(interaction, "▶️ 게임 시작! 아래 스레드로 이동하세요.")

    @discord.ui.button(label="취소", emoji="✖️", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host.id:
            await respond.reply(interaction, "방장만 취소할 수 있어요.", ephemeral=True)
        else:
            await self.close(interaction, "✖️ 방장이 대기방을 닫았어요.")

    async def close(self, interaction, footer):
        for item in self.children:
            item.disabled = True
        await respond.edit(interaction, embed=self.embed(footer), view=self)
        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(embed=self.embed("⏰ 시간이 지나 대기방이 닫혔어요."), view=self)
            except discord.HTTPException:
                pass


async def multi_lobby(ctx):
    if not await check_can_play(ctx):
        return

    view = LobbyView(ctx.author)
    playing.add(ctx.author.id)
    try:
        view.message = await ctx.send(embed=view.embed(), view=view)
        await view.wait()
        if not view.started:
            return
        players = list(view.players)
        names = ", ".join(p.display_name for p in players)
        thread, created = await open_thread(view.message, f"🔤 다같이 끝말잇기 ({names})")
        await play_multi(thread, players)
        await close_thread(thread, created)
    finally:
        for p in view.players:
            playing.discard(p.id)


async def play_multi(channel, players):
    random.shuffle(players)
    alive = list(players)
    remaining = {p.id: await remaining_today(p.id) for p in players}
    # 🔤 끝말잇기 보상 능력만 적용 (⌛ 시간 능력은 친구끼리 겨루는 판이라 쓰지 않는다)
    reward_mult = {p.id: (await player_bonus(p.id))[0] for p in players}
    earned = {p.id: 0 for p in players}
    counts = {p.id: 0 for p in players}
    out = []   # 탈락한 순서
    used: set[str] = set()

    word = first_word()
    used.add(word)

    embed = discord.Embed(
        title="🔤 다같이 끝말잇기 시작!",
        description=(
            f"시작 단어: **{word}**\n"
            "순서: " + " → ".join(p.mention for p in alive) + "\n\n"
            f"차례가 되면 {TURN_SECONDS}초 안에 단어를 입력하세요. 못 내거나 `그만`을 치면 탈락!"
        ),
        color=discord.Color.blurple(),
    )
    await channel.send(" ".join(p.mention for p in players), embed=embed)

    turn = 0
    while len(alive) > 1:
        player = alive[turn]
        await channel.send(f"👉 {player.mention} 차례! **{word}** → {start_hint(word)}")
        status, text, msg, _ = await take_turn(channel, player, word, used)

        if status != "ok":
            alive.remove(player)
            out.append(player)
            reason = "⏰ 시간 초과" if status == "timeout" else "🏳️ 기권"
            await channel.send(f"{reason}! {player.mention} 탈락 (남은 사람 {len(alive)}명)")
            # 탈락한 사람 자리에 다음 사람이 오므로 turn 은 그대로 (끝이었으면 처음으로)
            turn %= len(alive)
            continue

        used.add(text)
        word = text
        counts[player.id] += 1
        reward = min(word_reward(counts[player.id], len(text), reward_mult[player.id]), remaining[player.id] - earned[player.id])
        earned[player.id] += reward
        if reward > 0:
            await msg.reply(f"✅ +{num(reward)} byte (누적 {num(earned[player.id])})", mention_author=False)
        else:
            await msg.add_reaction("✅")
        turn = (turn + 1) % len(alive)

    winner = alive[0]
    bonus = MULTI_WIN_BONUS * (len(players) - 1)
    earned[winner.id] += min(bonus, remaining[winner.id] - earned[winner.id])

    paid = {}
    debt_lines = []
    for p in players:
        paid[p.id], result = await pay(p.id, earned[p.id])
        if result["collected"]:
            debt_lines.append(f"{p.mention}: 미납금 {num(result['collected'])} byte 자동 징수")

    ranking = [winner] + out[::-1]
    embed = discord.Embed(
        title="🏆 다같이 끝말잇기 끝!",
        description=f"우승: {winner.mention} (우승 보너스 **{num(bonus)} byte**)\n마지막 단어: **{word}**",
        color=discord.Color.gold(),
    )
    embed.add_field(
        name="📊 결과",
        value="\n".join(
            f"**{i}위** {p.mention} — {counts[p.id]}단어, **+{num(paid[p.id])} byte**"
            for i, p in enumerate(ranking, start=1)
        ),
        inline=False,
    )
    if debt_lines:
        embed.add_field(name="🧾 미납금", value="\n".join(debt_lines), inline=False)
    embed.set_footer(text=f"보상은 각자 하루 끝말잇기 한도({num(DAILY_MAX)} byte) 안에서 지급돼요.")
    await channel.send(embed=embed)
