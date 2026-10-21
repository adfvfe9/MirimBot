"""선착순 퀴즈: 1~2시간마다 퀴즈 채널에 문제가 나오고, 가장 먼저 맞힌 사람이 돈을 받는다.

    %퀴즈채널 <채널ID>   (관리자) 퀴즈를 올릴 채널 설정
    %퀴즈출제            (관리자) 지금 바로 퀴즈 하나 내기

문제 종류
- 🧮 계산: 봇이 만든 계산 문제. 숫자로 답한다.
- 🔤 초성: 초성에 맞는 단어를 아무거나 하나. (끝말잇기 단어 목록에 있는 단어면 정답)
- 🌍 상식: Open Trivia DB(https://opentdb.com, 무료/키 필요 없음)에서 가져온 영어 4지선다. 번호로 답한다.
  불러오기에 실패하면 계산 문제로 대신 낸다.
"""
import asyncio
import random
import re
import urllib.parse

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

KIND_WEIGHTS = {"math": 4, "chosung": 3, "trivia": 3}
TRIVIA_URL = "https://opentdb.com/api.php?amount=1&type=multiple&encode=url3986"

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


def fetch_trivia():
    data = requests.get(TRIVIA_URL, timeout=5).json()
    item = data["results"][0]
    unquote = urllib.parse.unquote
    correct = unquote(item["correct_answer"])
    choices = [correct] + [unquote(c) for c in item["incorrect_answers"]]
    random.shuffle(choices)
    answer_no = choices.index(correct) + 1

    def check(msg):
        if msg not in {"1", "2", "3", "4"}:
            return None
        return int(msg) == answer_no

    return {
        "title": f"🌍 상식 퀴즈 ({unquote(item['category'])})",
        "question": f"**{unquote(item['question'])}**\n\n"
                    + "\n".join(f"**{i}.** {c}" for i, c in enumerate(choices, start=1)),
        "hint": "정답 번호(1~4)를 입력하세요. 한 사람당 한 번만!",
        "answer": f"{answer_no}. {correct}",
        "check": check,
        "tries": 1,
    }


async def make_quiz(kind=None):
    kind = kind or random.choices(list(KIND_WEIGHTS), weights=KIND_WEIGHTS.values())[0]
    if kind == "chosung" and not await wordchain.load_words():
        kind = "math"
    if kind == "trivia":
        try:
            return await asyncio.to_thread(fetch_trivia)
        except Exception as e:
            print(f"[퀴즈] 상식 문제 불러오기 실패, 계산 문제로 대신: {type(e).__name__}: {e}")
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
    """%퀴즈출제 [계산|초성|상식]"""
    await ctx.message.delete()
    kind = {"계산": "math", "초성": "chosung", "상식": "trivia"}.get(kind)
    channel_ids = await db.get_quiz_channels() or [ctx.channel.id]
    await publish(channel_ids, kind)
