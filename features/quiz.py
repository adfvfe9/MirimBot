"""선착순 퀴즈: 1~2시간마다 퀴즈 채널에 문제가 나오고, 가장 먼저 맞힌 사람이 돈을 받는다.

    %퀴즈채널 <채널ID>          (관리자) 퀴즈를 올릴 채널 설정
    %퀴즈출제 [과목] [난이도]   (관리자) 지금 바로 퀴즈 하나 내기. 예) %퀴즈출제 수학 상

과목: 수학 / 국어 / 영어 / 사회 / 한국사 / 과학 / 상식
난이도: 하(1분) / 중(5분) / 상(10분) — 어려울수록 보상이 크다.

- 🧮 수학: quiz_math.py 가 고2 2학기 범위(대수, 미적분 I)에서 매번 새 문제를 만든다. 그래프 그림이 나오는 문제도 있다.
- 국어: 문제 은행(quiz_bank.py) + 초성 퀴즈(끝말잇기 단어 목록) + 뜻풀이 퀴즈(한국어기초사전 API)
  뜻풀이는 국립국어원 한국어기초사전 오픈 API 키가 필요하다. (.env 의 KRDICT_API_KEY, 하루 5만 번까지)
  키가 없거나 불러오기에 실패하면 문제 은행에서 낸다.
- 나머지 과목: 대부분(GENERATED_SHARE)은 quiz_gen.py 가 사실 표로 매번 새로 만들고,
  나머지는 직접 쓴 문제 은행(quiz_bank.py)에서 낸다. 문제를 늘리려면 두 파일의 표/목록에 줄을 추가하면 된다.

답하는 법
- 객관식: 번호만 입력. 한 사람당 한 번.
- 숫자 답: 숫자만 입력. 한 사람당 3번.
- 글자 답: 그냥 입력. (띄어쓰기/대소문자 무시, 횟수 제한 없음)
"""
import asyncio
import io
import os
import random
import re
import xml.etree.ElementTree as ET
from collections import deque

import discord
import requests
from discord.ext import commands, tasks

import database as db
from bot import client
from features import abilities, quiz_bank, quiz_gen, quiz_math, stocks, wordchain
from fmt import debt_line, num

# ───────────── 밸런스 설정 ─────────────
QUIZ_INTERVAL_MINUTES = (10, 20)   # 다음 퀴즈까지 랜덤 간격
QUIZ_HOURS = range(8, 24)           # 퀴즈가 나오는 시간 (한국 시간 8시 ~ 23시대)
NUMBER_TRIES = 3                    # 숫자 답: 한 사람이 한 문제에 낼 수 있는 답 수 (객관식은 1번)

LEVELS = {   # 제한 시간(초), 보상 범위, 나올 확률(가중치), 정답자가 토큰 1개를 받을 확률(%)
    "하": {"seconds": 60,  "reward": (1500, 2500),  "weight": 45, "token": 10},
    "중": {"seconds": 300, "reward": (3000, 5000),  "weight": 35, "token": 30},
    "상": {"seconds": 600, "reward": (6000, 10000), "weight": 20, "token": 60},
}
SUBJECTS = {  # 이모지, 나올 확률(가중치)
    "수학": ("🧮", 30), "국어": ("📚", 15), "영어": ("🔠", 15), "사회": ("🏛️", 10),
    "한국사": ("📜", 10), "과학": ("🔬", 10), "상식": ("💡", 10),
}
RECENT_SIZE = 40                    # 최근에 낸 문제 은행 문제는 이만큼 다시 안 낸다
GENERATED_SHARE = 0.75              # 수학 말고 다른 과목에서 자동 출제(quiz_gen) 문제가 나올 확률

KRDICT_URL = "https://krdict.korean.go.kr/api/search"
# 뜻풀이 문제의 단어는 이 글자로 시작하는 초급·중급 명사 중에서 고른다.
MEANING_STARTS = "가나다마바사아자차카타파하고노도모보소오조초코토포호구누두무부수우주추후기미비시이지치피히"
CHOICE_MARKS = "①②③④⑤"

minutes_until_next = random.randint(*QUIZ_INTERVAL_MINUTES)
running_channels: set[int] = set()   # 지금 퀴즈가 진행 중인 채널
recent_bank: deque[int] = deque(maxlen=RECENT_SIZE)


# ───────────── 답 확인 ─────────────
# check(메시지) → True(정답) / False(오답) / None(답이 아님: 그냥 채팅)

def normalize(text: str) -> str:
    return re.sub(r"[\s.!?~'\"]", "", text).lower()


def number_check(answer: int):
    def check(msg):
        text = msg.replace(",", "").replace("−", "-")
        if not re.fullmatch(r"-?\d+", text):
            return None
        return int(text) == answer
    return check


def choice_check(count: int, answer: int):
    def check(msg):
        text = msg.strip()
        if text in CHOICE_MARKS[:count]:
            text = str(CHOICE_MARKS.index(text) + 1)
        if text not in {str(i) for i in range(1, count + 1)}:
            return None
        return int(text) == answer
    return check


def text_check(accepts):
    targets = {normalize(a) for a in accepts}

    def check(msg):
        return normalize(msg) in targets
    return check


# ───────────── 문제 만들기 ─────────────
# 퀴즈 = dict: subject, unit, level, question, hint, answer(정답 공개용), check, tries(None = 무제한), image, explain

def from_math(level):
    m = quiz_math.make(level)
    return {
        "subject": "수학", "unit": m["unit"], "level": level,
        "question": m["question"], "hint": "정답을 숫자로 입력하세요.",
        "answer": str(m["answer"]), "check": number_check(m["answer"]), "tries": NUMBER_TRIES,
        "image": m["image"], "explain": m["explain"],
    }


def to_quiz(subject, level, b):
    """문제 은행 / 자동 출제 모양의 dict 를 퀴즈로 바꾼다."""
    quiz = {
        "subject": subject, "unit": b.get("unit"), "level": level, "question": f"**{b['q']}**",
        "image": None, "explain": b.get("explain"),
    }
    if b.get("choices"):
        quiz["question"] += "\n\n" + "\n".join(f"{CHOICE_MARKS[i]} {c}" for i, c in enumerate(b["choices"]))
        quiz.update(hint="정답 번호를 입력하세요. (한 사람당 한 번!)",
                    answer=f"{CHOICE_MARKS[b['answer'] - 1]} {b['choices'][b['answer'] - 1]}",
                    check=choice_check(len(b["choices"]), b["answer"]), tries=1)
    elif all(re.fullmatch(r"-?\d+", a) for a in b["answer"]):
        quiz.update(hint="정답을 숫자로 입력하세요.", answer=b["answer"][0],
                    check=number_check(int(b["answer"][0])), tries=NUMBER_TRIES)
    else:
        quiz.update(hint="정답을 입력하세요.", answer=b["answer"][0], check=text_check(b["answer"]), tries=None)
    return quiz


def from_bank(subject, level):
    pool = [i for i, b in enumerate(quiz_bank.BANK) if b["subject"] == subject]
    same_level = [i for i in pool if quiz_bank.BANK[i]["level"] == level]
    fresh = [i for i in same_level if i not in recent_bank] or [i for i in pool if i not in recent_bank] or pool
    index = random.choice(fresh)
    recent_bank.append(index)
    b = quiz_bank.BANK[index]
    # 같은 난이도 문제가 다 나왔으면 다른 난이도 문제가 나올 수 있다
    return to_quiz(subject, b["level"], b)


def from_generated_or_bank(subject, level):
    if random.random() < GENERATED_SHARE:
        generated = quiz_gen.make(subject, level)
        if generated:
            return to_quiz(subject, level, generated)
    return from_bank(subject, level)


def make_chosung(level):
    word = wordchain.random_word(lengths=(3, 4))
    initials = wordchain.chosung(word)

    def check(msg):
        if not re.fullmatch(r"[가-힣]+", msg):
            return None
        return len(msg) == len(word) and wordchain.chosung(msg) == initials and wordchain.is_word(msg)

    return {
        "subject": "국어", "unit": "초성 퀴즈", "level": level,
        "question": f"**{' '.join(initials)}**",
        "hint": "이 초성으로 된 단어를 아무거나 입력하세요. (사전에 있는 단어면 정답)",
        "answer": f"{word} 등", "check": check, "tries": None, "image": None, "explain": None,
    }


def fetch_meaning(key, level):
    """한국어기초사전에서 단어 하나와 뜻을 가져온다."""
    params = {
        "key": key, "q": random.choice(MEANING_STARTS), "part": "word", "sort": "popular",
        "num": 100, "advanced": "y", "method": "start", "pos": 1,          # pos 1 = 명사
        "level": "level1,level2", "letter_s": 2, "letter_e": 4,         # 초급·중급, 2~4글자
    }
    root = ET.fromstring(requests.get(KRDICT_URL, params=params, timeout=5).content)
    if root.tag == "error":
        raise RuntimeError(f"API 오류 {root.findtext('error_code')}: {root.findtext('message')}")

    candidates = []
    for item in root.iter("item"):
        word = (item.findtext("word") or "").strip()
        definition = (item.findtext("sense/definition") or "").strip()
        if re.fullmatch(r"[가-힣]{2,4}", word) and definition:
            candidates.append((word, definition))
    if not candidates:
        raise RuntimeError("조건에 맞는 단어가 없음")
    word, definition = random.choice(candidates)
    definition = definition.replace(word, "○" * len(word))   # 뜻 안에 정답이 그대로 있으면 가린다

    def check(msg):
        if not re.fullmatch(r"[가-힣]+", msg):
            return None
        return msg == word

    return {
        "subject": "국어", "unit": "뜻풀이", "level": level,
        "question": f"**{definition}**\n\n힌트: **{' '.join(wordchain.chosung(word))}** ({len(word)}글자)",
        "hint": "이 뜻을 가진 단어를 입력하세요.",
        "answer": word, "check": check, "tries": NUMBER_TRIES, "image": None,
        "explain": "국립국어원 한국어기초사전",
    }


async def make_korean(level):
    """국어: 하는 초성 퀴즈도, 중은 뜻풀이도 섞어서 낸다."""
    roll = random.random()
    if level == "하" and roll < 0.4 and await wordchain.load_words():
        return make_chosung(level)
    if level == "중" and roll < 0.5:
        key = os.getenv("KRDICT_API_KEY")
        try:
            if not key:
                raise RuntimeError(".env 에 KRDICT_API_KEY 가 없음")
            return await asyncio.to_thread(fetch_meaning, key, level)
        except Exception as e:
            print(f"[퀴즈] 뜻풀이 문제 불러오기 실패, 다른 문제로 대신: {type(e).__name__}: {e}")
    return from_generated_or_bank("국어", level)


async def make_quiz(subject=None, level=None):
    subject = subject or random.choices(list(SUBJECTS), weights=[w for _, w in SUBJECTS.values()])[0]
    level = level or random.choices(list(LEVELS), weights=[v["weight"] for v in LEVELS.values()])[0]
    if subject == "수학":
        return await stocks.in_plot_thread(from_math, level)   # 그래프 그리기는 조금 걸려서 따로 (그래프 스레드)
    if subject == "국어":
        return await make_korean(level)
    return from_generated_or_bank(subject, level)


# ───────────── 진행 ─────────────

def time_text(seconds):
    return f"{seconds // 60}분" if seconds >= 60 else f"{seconds}초"


async def run_quiz(channel, quiz):
    """한 채널에서 퀴즈 하나를 진행한다."""
    if channel.id in running_channels:
        return
    running_channels.add(channel.id)
    reminder = None
    try:
        level = LEVELS[quiz["level"]]
        seconds = level["seconds"]
        reward = random.randint(*level["reward"])
        emoji = SUBJECTS[quiz["subject"]][0]
        unit = f" · {quiz['unit']}" if quiz["unit"] else ""

        embed = discord.Embed(
            title=f"{emoji} {quiz['subject']}{unit} — 난이도 {quiz['level']}",
            description=f"{quiz['question']}\n\n{quiz['hint']}",
            color={"하": discord.Color.green(), "중": discord.Color.gold(), "상": discord.Color.red()}[quiz["level"]],
        )
        embed.set_footer(
            text=f"⏱️ 제한 시간 {time_text(seconds)} · 가장 먼저 맞힌 사람에게 {num(reward)} byte! (🪙 토큰 {level['token']}% 확률)"
        )
        if quiz["image"]:
            embed.set_image(url="attachment://quiz.png")
            await channel.send(embed=embed, file=discord.File(io.BytesIO(quiz["image"]), filename="quiz.png"))
        else:
            await channel.send(embed=embed)

        if seconds > 60:
            async def remind():
                await asyncio.sleep(seconds - 60)
                await channel.send(f"⏰ {emoji} {quiz['subject']} 퀴즈 **1분** 남았어요!")
            reminder = asyncio.create_task(remind())

        tries: dict[int, int] = {}
        loop = asyncio.get_running_loop()
        deadline = loop.time() + seconds
        winner = None

        def is_attempt(m: discord.Message):
            return (
                m.channel.id == channel.id
                and not m.author.bot
                and not m.content.startswith(client.command_prefix)
                and quiz["check"](m.content.strip()) is not None
            )

        while winner is None:
            try:
                msg = await client.wait_for("message", check=is_attempt, timeout=deadline - loop.time())
            except asyncio.TimeoutError:
                break
            if quiz["tries"] is not None:
                used = tries.get(msg.author.id, 0)
                if used >= quiz["tries"]:
                    continue
                tries[msg.author.id] = used + 1
            if quiz["check"](msg.content.strip()):
                winner = msg
            elif quiz["tries"] is not None:   # 글자 답은 채팅과 구분이 안 돼서 ❌ 를 달지 않는다
                try:
                    await msg.add_reaction("❌")
                except discord.HTTPException:
                    pass

        explain = f"\n💬 {quiz['explain']}" if quiz["explain"] else ""
        if winner is None:
            embed = discord.Embed(
                title="⏰ 퀴즈 종료",
                description=f"아무도 못 맞혔어요. 정답: **{quiz['answer']}**{explain}",
                color=discord.Color.light_grey(),
            )
            await channel.send(embed=embed)
            return

        result = await db.receive(winner.author.id, reward)
        await db.log_money(winner.author.id, "quiz", reward)
        # 🪙 토큰 보상 (강화 능력 리롤 재료). 🪙 퀴즈 토큰 확률 능력만큼 확률이 오른다
        token_chance = level["token"] + await abilities.total(winner.author.id, "quiz_token")
        got_token = abilities.chance(token_chance)
        if got_token:
            await db.add_tokens(winner.author.id, 1)
        embed = discord.Embed(
            title="🎉 정답!",
            description=(
                f"{winner.author.mention}님이 가장 먼저 맞혔어요! **+{num(reward)} byte**"
                + (" **+🪙 토큰 1개**" if got_token else "") + "\n"
                f"정답: **{quiz['answer']}**{explain}"
                + debt_line(result["collected"])
            ),
            color=discord.Color.green(),
        )
        await winner.reply(embed=embed, mention_author=False)
    finally:
        if reminder:
            reminder.cancel()
        running_channels.discard(channel.id)


async def publish(channel_ids, subject=None, level=None):
    quiz = await make_quiz(subject, level)
    channels = [c for c in map(client.get_channel, channel_ids) if c is not None]
    await asyncio.gather(*(run_quiz(c, quiz) for c in channels), return_exceptions=True)


@tasks.loop(minutes=1)
async def quiz_loop():
    global minutes_until_next
    try:
        minutes_until_next -= 1
        if minutes_until_next <= 0 and db.now().hour in QUIZ_HOURS:
            minutes_until_next = random.randint(*QUIZ_INTERVAL_MINUTES)
            channel_ids = await db.get_quiz_channels()
            if channel_ids:
                # 퀴즈가 끝날 때까지 기다리지 않도록 따로 돌린다
                asyncio.create_task(publish(channel_ids))
    except Exception as e:
        print(f"[퀴즈 오류] {type(e).__name__}: {e}")


@quiz_loop.before_loop
async def before_quiz_loop():
    await client.wait_until_ready()


@client.listen("on_ready")
async def start_quiz_loop():
    if not quiz_loop.is_running():
        quiz_loop.start()


# ───────────── 명령어 ─────────────

@client.command(aliases=["퀴즈채널"])
@commands.has_permissions(administrator=True)
async def set_quiz_channel(ctx, channel_id: int):
    await ctx.message.delete()
    await db.set_quiz_channel(ctx.guild.id, channel_id)
    await ctx.send(f"✅ 퀴즈 채널이 <#{channel_id}>로 설정되었습니다.")


@client.command(aliases=["퀴즈출제"])
@commands.has_permissions(administrator=True)
async def publish_quiz(ctx, *args):
    """%퀴즈출제 [과목] [난이도] (순서 상관없음, 생략하면 랜덤)"""
    await ctx.message.delete()
    subject = next((a for a in args if a in SUBJECTS), None)
    level = next((a for a in args if a in LEVELS), None)
    unknown = [a for a in args if a not in SUBJECTS and a not in LEVELS]
    if unknown:
        await ctx.send(
            f"❌ 모르는 값: {', '.join(unknown)}\n"
            f"과목: {' / '.join(SUBJECTS)} · 난이도: {' / '.join(LEVELS)}",
            delete_after=10,
        )
        return
    channel_ids = await db.get_quiz_channels() or [ctx.channel.id]
    await publish(channel_ids, subject, level)
