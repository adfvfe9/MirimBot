"""활동 보상: 통화방에 있거나 채팅하면 byte 가 조금씩 쌓인다 (명령어를 안 쳐도)

통화방
- 1분마다 VOICE_BASE byte. 통화방에 계속 있으면 1시간마다 VOICE_STEP 씩 올라서 최대 분당 VOICE_MAX.
- 사람이 2명 이상인 통화방에서만. 듣기를 끈(헤드셋 끔) 사람과 잠수 채널은 빼서 혼자 켜두고 자는 걸 막는다.
- 잠깐 나갔다 와도 VOICE_GAP 안에 돌아오면 계속 있던 것으로 친다. (더 길면 다시 분당 VOICE_BASE 부터)
채팅
- 1글자당 CHAT_PER_CHAR byte, 메시지 하나에 최대 CHAT_PER_MESSAGE, 한 시간(정각 기준)에 최대 CHAT_PER_HOUR.
- 명령어(%…) · 봇 메시지는 빼고, 공백은 안 센다. 같은 글자가 이어지면 3개까지만 센다 (ㅋㅋㅋㅋㅋ → ㅋㅋㅋ).
지급
- 알림은 없다. 메모리에 모아 두었다가 FLUSH_SECONDS 마다 한 번에 넣고 돈 기록(money_log)에 남긴다.
  source 'voice' (memo "N분") / 'chat' (memo "N개"). 매분 · 매 메시지마다 기록하면 너무 많아서 묶었다.
- 봇이 꺼지면 아직 안 넣은 몫(최대 FLUSH_SECONDS 만큼)은 사라진다.
"""
import asyncio
import datetime
import re
import time

import database as db
from bot import client

VOICE_BASE = 10
VOICE_STEP = 5
VOICE_MAX = 50
VOICE_MIN_PEOPLE = 2
VOICE_GAP = datetime.timedelta(minutes=5)

CHAT_PER_CHAR = 0.5
CHAT_PER_MESSAGE = 50
CHAT_PER_HOUR = 3000

FLUSH_SECONDS = 300

REPEAT_RE = re.compile(r"(.)\1{3,}")

sessions = {}      # user_id → {"start": 통화방에 계속 있기 시작한 시각, "seen": 마지막으로 확인한 시각}
pending = {}       # user_id → {"voice": byte, "minutes": 분, "chat": byte, "messages": 개}
chat_hour = {}     # user_id → (시간 key, 이번 시간에 받은 byte)


def voice_rate(start, now):
    """통화방에 start 부터 있었을 때 지금 1분에 받는 byte"""
    hours = int((now - start).total_seconds() // 3600)
    return min(VOICE_MAX, VOICE_BASE + VOICE_STEP * hours)


def chat_reward(text):
    """메시지 하나의 보상 (시간당 한도는 따로)"""
    text = REPEAT_RE.sub(lambda m: m.group(1) * 3, text)
    chars = len(re.sub(r"\s", "", text))
    return min(CHAT_PER_MESSAGE, chars * CHAT_PER_CHAR)


def add(user_id, **amounts):
    entry = pending.setdefault(user_id, {"voice": 0.0, "minutes": 0, "chat": 0.0, "messages": 0})
    for k, v in amounts.items():
        entry[k] += v


def eligible_members(guild):
    """지금 통화방 보상을 받는 멤버들"""
    afk = guild.afk_channel
    result = []
    for channel in guild.voice_channels:
        if afk is not None and channel.id == afk.id:
            continue
        people = [m for m in channel.members if not m.bot]
        if len(people) < VOICE_MIN_PEOPLE:
            continue
        for m in people:
            v = m.voice
            if v is None or v.self_deaf or v.deaf:
                continue
            result.append(m)
    return result


def voice_tick(members, now):
    """1분에 한 번. members = 지금 보상을 받는 사람들. 이번 분에 준 byte 합계"""
    given = 0
    for m in members:
        s = sessions.get(m.id)
        if s is None or now - s["seen"] > VOICE_GAP:
            s = sessions[m.id] = {"start": now, "seen": now}
        s["seen"] = now
        rate = voice_rate(s["start"], now)
        add(m.id, voice=rate, minutes=1)
        given += rate
    return given


async def flush():
    """모아 둔 몫을 넣고 기록한다. 넣은 사람 수"""
    batch = {uid: e for uid, e in pending.items() if e["voice"] or e["chat"]}
    pending.clear()
    for uid, e in batch.items():
        try:
            async with db.user_tx(uid) as conn:
                await db.receive(uid, e["voice"] + e["chat"], conn)
                if e["voice"]:
                    await db.log_money(uid, "voice", e["voice"], f"{e['minutes']}분", conn)
                if e["chat"]:
                    await db.log_money(uid, "chat", e["chat"], f"{e['messages']}개", conn)
        except Exception as ex:
            print(f"[활동 보상] {uid} 지급 실패: {type(ex).__name__} {ex}")
    return len(batch)


async def loop():
    """setup_hook 에서 한 번 시작한다. 1분마다 통화방을 보고, FLUSH_SECONDS 마다 지급한다."""
    await client.wait_until_ready()
    last_flush = time.monotonic()
    while True:
        try:
            now = db.now()
            members = {m.id: m for guild in client.guilds for m in eligible_members(guild)}   # 한 사람은 한 통화방에만
            voice_tick(members.values(), now)
            if time.monotonic() - last_flush >= FLUSH_SECONDS:
                await flush()
                last_flush = time.monotonic()
        except Exception as e:
            print(f"[활동 보상] 확인 실패: {type(e).__name__} {e}")
        await asyncio.sleep(60)


@client.listen("on_message")
async def chat_message(message):
    if message.guild is None or message.author.bot:
        return
    if message.content.startswith(client.command_prefix):
        return
    reward = chat_reward(message.content)
    if reward <= 0:
        return
    hour_key = db.now().strftime("%Y%m%d%H")
    key, earned = chat_hour.get(message.author.id, (hour_key, 0.0))
    if key != hour_key:
        earned = 0.0
    reward = min(reward, CHAT_PER_HOUR - earned)
    if reward <= 0:
        return
    chat_hour[message.author.id] = (hour_key, earned + reward)
    add(message.author.id, chat=reward, messages=1)
