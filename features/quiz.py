"""선착순 퀴즈: 1~2시간마다 퀴즈 채널에 문제가 나오고, 가장 먼저 맞힌 사람이 돈을 받는다.

    %퀴즈채널 <채널ID>   (관리자) 퀴즈를 올릴 채널 설정
    %퀴즈출제 [종류]     (관리자) 지금 바로 퀴즈 하나 내기 (계산 / 초성 / 뜻풀이)

문제 종류
- 🧮 계산: 봇이 만든 계산 문제. 숫자로 답한다.
- 🔤 초성: 초성에 맞는 단어를 아무거나 하나. (끝말잇기 단어 목록에 있는 단어면 정답)
- 📖 뜻풀이: 국립국어원 한국어기초사전 오픈 API 에서 단어 뜻을 가져와서, 뜻(+초성 힌트)을 보고 단어를 맞힌다.
  무료지만 인증키가 필요하다: https://krdict.korean.go.kr/openApi/openApiInfo 에서 발급받아
  .env 에 KRDICT_API_KEY=발급받은키 를 적는다. (하루 5만 번까지)
  키가 없거나 불러오기에 실패하면 다른 문제로 대신 낸다.
"""
import asyncio
import random
import os
import re
import xml.etree.ElementTree as ET

import discord
import requests
from discord.ext import commands, tasks

import database as db
from bot import client
from features import wordchain
from fmt import debt_line, num

# ───────────── 밸런스 설정 ─────────────
QUIZ_INTERVAL_MINUTES = (60, 120)   # 다음 퀴즈까지 랜덤 간격
QUIZ_HOURS = range(8, 24)           # 퀴즈가 나오는 시간 (한국 시간 8시 ~ 23시대)
ANSWER_SECONDS = 60                 # 답할 수 있는 시간
REWARD = (2000, 4000)               # 정답 보상 (랜덤)
TRIES_PER_USER = 3                  # 한 사람이 한 문제에 낼 수 있는 답 수 (4지선다는 1번)

KIND_WEIGHTS = {"math": 3, "chosung": 3, "meaning": 4}
KIND_NAMES = {"계산": "math", "초성": "chosung", "뜻풀이": "meaning", "뜻": "meaning"}

KRDICT_URL = "https://krdict.korean.go.kr/api/search"
# 뜻풀이 문제의 단어는 이 글자로 시작하는 초급·중급 명사 중에서 고른다.
MEANING_STARTS = "가나다마바사아자차카타파하고노도모보소오조초코토포호구누두무부수우주추후기미비시이지치피히"

minutes_until_next = random.randint(*QUIZ_INTERVAL_MINUTES)
running_channels: set[int] = set()   # 지금 퀴즈가 진행 중인 채널


# ───────────── 문제 만들기 ─────────────
# 문제는 dict: title, question, hint, answer(정답 공개용 문자열), check(답 문자열 → True/False/None), tries
# check 가 None 을 돌려주면 답으로 치지 않는다 (그냥 채팅).

def make_math():
    form = random.randint(1, 3)
    if form == 1:
        a, b = random.randint(12, 99), random.randint(3, 19)
        text, answer = f"{a} × {b}", a * b
    elif form == 2:
        a, b, c = random.randint(100, 999), random.randint(100, 999), random.randint(10, 99)
        text, answer = f"{a} + {b} - {c}", a + b - c
    else:
        a, b, c = random.randint(11, 49), random.randint(3, 9), random.randint(10, 99)
        text, answer = f"{a} × {b} + {c}", a * b + c

    def check(msg):
        if not re.fullmatch(r"-?\d+", msg.replace(",", "")):
            return None
        return int(msg.replace(",", "")) == answer

    return {
        "title": "🧮 계산 퀴즈",
        "question": f"**{text} = ?**",
        "hint": "숫자로 답하세요.",
        "answer": num(answer),
        "check": check,
        "tries": TRIES_PER_USER,
    }


def make_chosung():
    word = wordchain.random_word(lengths=(3, 4))
    initials = wordchain.chosung(word)

    def check(msg):
        if not re.fullmatch(r"[가-힣]+", msg):
            return None
        return len(msg) == len(word) and wordchain.chosung(msg) == initials and wordchain.is_word(msg)

    return {
        "title": "🔤 초성 퀴즈",
        "question": f"**{' '.join(initials)}**",
        "hint": "이 초성으로 된 단어를 아무거나 입력하세요. (사전에 있는 단어만 정답)",
        "answer": f"{word} 등",
        "check": check,
        "tries": TRIES_PER_USER,
    }


def fetch_meaning(key):
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
        "title": "📖 뜻풀이 퀴즈",
        "question": f"**{definition}**\n\n힌트: **{' '.join(wordchain.chosung(word))}** ({len(word)}글자)",
        "hint": "이 뜻을 가진 단어를 입력하세요.",
        "answer": word,
        "check": check,
        "tries": TRIES_PER_USER,
    }


async def make_quiz(kind=None):
    kind = kind or random.choices(list(KIND_WEIGHTS), weights=KIND_WEIGHTS.values())[0]
    if kind == "chosung" and not await wordchain.load_words():
        kind = "math"
    if kind == "meaning":
        key = os.getenv("KRDICT_API_KEY")
        try:
            if not key:
                raise RuntimeError(".env 에 KRDICT_API_KEY 가 없음")
            return await asyncio.to_thread(fetch_meaning, key)
        except Exception as e:
            print(f"[퀴즈] 뜻풀이 문제 불러오기 실패, 다른 문제로 대신: {type(e).__name__}: {e}")
            kind = random.choice(["math", "chosung"])
            if kind == "chosung" and not await wordchain.load_words():
                kind = "math"
    return make_chosung() if kind == "chosung" else make_math()


# ───────────── 진행 ─────────────

async def run_quiz(channel, quiz):
    """한 채널에서 퀴즈 하나를 진행한다."""
    if channel.id in running_channels:
        return
    running_channels.add(channel.id)
    try:
        reward = random.randint(*REWARD)
        embed = discord.Embed(
            title=f"{quiz['title']} — 선착순!",
            description=f"{quiz['question']}\n\n{quiz['hint']}",
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"가장 먼저 맞힌 사람에게 {num(reward)} byte! ({ANSWER_SECONDS}초)")
        await channel.send(embed=embed)

        tries: dict[int, int] = {}
        loop = asyncio.get_running_loop()
        deadline = loop.time() + ANSWER_SECONDS
        winner = None

        def is_attempt(m: discord.Message):
            return (
                m.channel.id == channel.id
                and not m.author.bot
                and quiz["check"](m.content.strip()) is not None
            )

        while winner is None:
            try:
                msg = await client.wait_for("message", check=is_attempt, timeout=deadline - loop.time())
            except asyncio.TimeoutError:
                break
            used = tries.get(msg.author.id, 0)
            if used >= quiz["tries"]:
                continue
            tries[msg.author.id] = used + 1
            if quiz["check"](msg.content.strip()):
                winner = msg
            else:
                try:
                    await msg.add_reaction("❌")
                except discord.HTTPException:
                    pass

        if winner is None:
            embed = discord.Embed(
                title="⏰ 퀴즈 종료",
                description=f"아무도 못 맞혔어요. 정답: **{quiz['answer']}**",
                color=discord.Color.light_grey(),
            )
            await channel.send(embed=embed)
            return

        result = await db.receive(winner.author.id, reward)
        embed = discord.Embed(
            title="🎉 정답!",
            description=(
                f"{winner.author.mention}님이 가장 먼저 맞혔어요! **+{num(reward)} byte**\n"
                f"정답: **{winner.content.strip()}**"
                + (f" (예시 답: {quiz['answer']})" if quiz["title"].startswith("🔤") else "")
                + debt_line(result["collected"])
            ),
            color=discord.Color.green(),
        )
        await winner.reply(embed=embed, mention_author=False)
    finally:
        running_channels.discard(channel.id)


async def publish(channel_ids, kind=None):
    quiz = await make_quiz(kind)
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
async def publish_quiz(ctx, kind: str = None):
    """%퀴즈출제 [계산|초성|뜻풀이]"""
    await ctx.message.delete()
    kind = KIND_NAMES.get(kind)
    channel_ids = await db.get_quiz_channels() or [ctx.channel.id]
    await publish(channel_ids, kind)
