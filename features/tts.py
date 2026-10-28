"""TTS: 채팅 채널의 메시지를 통화방에서 읽어준다

    %읽기 시작                         호출한 사람이 있는 통화방에 들어가서, 명령어를 쓴 채널의 메시지를 읽어준다
                                  (다른 채널에서 다시 쓰면 그 채널로 바뀐다)
    %읽기 나가기                         통화방에서 나간다 (TTS · 음악 둘 다 끝) (%읽기 나가기)
    %읽기 줄임말설정 <글자> <읽을말>   이 서버에서 그 글자를 어떻게 읽을지 정한다 (읽을말이 - 면 안 읽는다)
    %읽기 줄임말설정 삭제 <글자>
    %읽기 줄임말                       이 서버의 줄임말 목록

- 목소리는 Edge TTS (마이크로소프트, 무료) 의 한국어 목소리. mp3 를 받아서 ffmpeg 로 바꾼다.
- 음악(music.py) 과 같이 voice.py 의 Mixer 로 내보내서 노래를 들으면서 TTS 도 들린다.
- 봇 메시지, 명령어(%...)는 안 읽는다. 링크 / 이모지는 줄여서 읽는다.
- MAX_CHARS 보다 긴 글은 읽지 않고 ❌ 반응을 단다.
- 밀린 메시지가 많으면 (QUEUE_MAX 넘게) 새 메시지는 건너뛴다.
- 줄임말은 긴 것부터 한 번에 바꾼다 (바꾼 결과를 또 바꾸지 않는다). 영어는 대소문자를 구분하지 않는다.
"""
import asyncio
import io
import re

import discord
from discord.ext import commands
import edge_tts

import database as db
from bot import client
from features import voice
from features.music import ffmpeg_path

VOICE_NAME = "ko-KR-SunHiNeural"
MAX_CHARS = 80          # 이보다 긴 글은 안 읽는다
QUEUE_MAX = 10
TOO_LONG_REACTION = "❌"

ABBREV_MAX = 100        # 서버마다 줄임말 개수
WORD_MAX = 20
READING_MAX = 30
SILENT = "-"            # 읽을말이 이거면 안 읽는다

URL_RE = re.compile(r"https?://\S+")
CUSTOM_EMOJI_RE = re.compile(r"<a?:(\w+):\d+>")
REPEAT_RE = re.compile(r"(.)\1{4,}")      # ㅋㅋㅋㅋㅋㅋㅋ → ㅋㅋㅋㅋ


class Reader:
    """서버 하나의 TTS 상태"""
    def __init__(self, guild, channel):
        self.guild = guild
        self.channel = channel        # 읽을 채팅 채널
        self.queue = asyncio.Queue(maxsize=QUEUE_MAX)
        self.task = asyncio.create_task(self.worker())

    async def worker(self):
        """글을 차례로 음성으로 바꿔서 Mixer 에 넣는다 (Mixer 가 앞 문장이 끝나면 다음 문장을 읽는다)"""
        while True:
            text = await self.queue.get()
            try:
                audio = await synthesize(text)
            except Exception as e:     # 네트워크 오류 등 → 이번 문장만 건너뛴다
                print(f"[TTS] 음성 만들기 실패 {text!r}: {type(e).__name__} {e}")
                continue
            if not audio or self.guild.voice_client is None:
                continue
            source = discord.FFmpegPCMAudio(io.BytesIO(audio), pipe=True, executable=ffmpeg_path())
            voice.mixer_of(self.guild).add_speech(source)

    def stop(self):
        self.task.cancel()


readers = {}


async def synthesize(text):
    """글 → mp3 바이트"""
    audio = bytearray()
    async for chunk in edge_tts.Communicate(text, VOICE_NAME).stream():
        if chunk["type"] == "audio":
            audio += chunk["data"]
    return bytes(audio)


def clean(message):
    """메시지 → 읽을 글 (줄임말 바꾸기 전). 읽을 게 없으면 빈 글"""
    text = message.clean_content           # 멘션 → @이름
    text = URL_RE.sub(" 링크 ", text)
    text = CUSTOM_EMOJI_RE.sub(r" \1 ", text)
    text = REPEAT_RE.sub(lambda m: m.group(1) * 4, text)
    text = " ".join(text.split())
    if not text:
        if message.attachments:
            text = "파일"
        elif message.stickers:
            text = "스티커"
    return text


# ───────────── 줄임말 ─────────────

abbrev_cache = {}    # guild_id → (정규식 | None, {글자: 읽을말})


async def abbrevs_of(guild_id):
    if guild_id not in abbrev_cache:
        mapping = {r["word"]: r["reading"] for r in await db.tts_abbrevs(guild_id)}
        pattern = None
        if mapping:
            words = sorted(mapping, key=len, reverse=True)     # 긴 것부터 (ㅋㅋ 가 ㅋ 보다 먼저)
            pattern = re.compile("|".join(map(re.escape, words)), re.IGNORECASE)
        abbrev_cache[guild_id] = (pattern, mapping)
    return abbrev_cache[guild_id]


async def expand(guild_id, text):
    pattern, mapping = await abbrevs_of(guild_id)
    if pattern is None:
        return text
    text = pattern.sub(lambda m: mapping[m.group(0).lower()], text)
    return " ".join(text.split())


# ───────────── 통화방 상태 ─────────────

def tts_in_use(guild):
    return guild.id in readers


def on_leave(guild):
    if reader := readers.pop(guild.id, None):
        reader.stop()


async def on_alone(guild):
    from features import music
    if guild.id in readers and not music.music_in_use(guild):   # 음악이 켜져 있으면 music 이 알린다
        await readers[guild.id].channel.send("👋 통화방에 아무도 없어서 나갈게요.")


voice.in_use.append(tts_in_use)
voice.on_leave.append(on_leave)
voice.alone_hooks.append(on_alone)


# ───────────── 명령어 ─────────────

@commands.command(name="시작")
async def tts_start(ctx):
    if ctx.guild is None:
        return
    if ctx.author.voice is None or ctx.author.voice.channel is None:
        await ctx.send("🎧 먼저 통화방에 들어가 주세요! 들어가 있는 통화방으로 봇이 따라가요.")
        return
    target = ctx.author.voice.channel
    current = ctx.guild.voice_client
    if current and current.channel != target and voice.busy(ctx.guild):
        await ctx.send(f"🎧 지금 **{current.channel.name}**에서 쓰는 중이에요. 그 통화방으로 와주세요!")
        return
    if error := await voice.join(target):
        await ctx.send(f"❌ 통화방에 들어가지 못했어요. ({error})")
        return
    reader = readers.get(ctx.guild.id)
    if reader is None:
        readers[ctx.guild.id] = Reader(ctx.guild, ctx.channel)
    elif reader.channel == ctx.channel:
        await ctx.send(f"📢 이미 이 채널을 **{target.name}**에서 읽고 있어요. 그만하려면 `%읽기 나가기`")
        return
    else:
        reader.channel = ctx.channel
    await ctx.send(
        f"📢 이제 이 채널의 메시지를 **{target.name}**에서 읽어줄게요! 노래(`%음악 재생`)도 같이 들을 수 있어요. 그만하려면 `%읽기 나가기`\n"
        f"-# {MAX_CHARS}자가 넘는 글은 안 읽고 {TOO_LONG_REACTION} 를 달아요 · 읽는 법 바꾸기: `%읽기 줄임말설정`"
    )


@commands.command(name="나가기")
async def voice_leave(ctx):
    if ctx.guild is None:
        return
    if ctx.guild.voice_client is None:
        await ctx.send("🎧 지금 통화방에 없어요.")
        return
    if not voice.same_channel(ctx.author, ctx.guild):
        await ctx.send("🎧 봇과 같은 통화방에 있어야 내보낼 수 있어요.")
        return
    await voice.leave(ctx.guild)
    await ctx.send("👋 통화방에서 나왔어요. (TTS · 음악 끝)")


ABBREV_USAGE = (
    "`%읽기 줄임말설정 <글자> <읽을말>` 예) `%읽기 줄임말설정 ㅇㅈ 인정` · `%읽기 줄임말설정 ㅋ 크`\n"
    f"`%읽기 줄임말설정 <글자> {SILENT}` 그 글자는 안 읽기 · `%읽기 줄임말설정 삭제 <글자>` · `%읽기 줄임말` 목록"
)


@commands.command(name="줄임말설정", usage="<글자> <읽을말 | ->")
async def tts_abbrev_set(ctx, word: str = None, *, reading: str = None):
    if ctx.guild is None:
        return
    if word is None or reading is None:
        await ctx.send(f"사용법\n{ABBREV_USAGE}")
        return
    if word == "삭제":
        target = reading.strip().lower()
        if await db.delete_tts_abbrev(ctx.guild.id, target):
            abbrev_cache.pop(ctx.guild.id, None)
            await ctx.send(f"🗑️ 줄임말 삭제: `{target}`")
        else:
            await ctx.send(f"❌ 그런 줄임말이 없어요: `{target}` (`%읽기 줄임말`로 목록 보기)")
        return

    word = word.lower()
    reading = " ".join(reading.split())
    if len(word) > WORD_MAX or len(reading) > READING_MAX:
        await ctx.send(f"❌ 글자는 {WORD_MAX}자, 읽을말은 {READING_MAX}자까지예요.")
        return
    existing = {r["word"] for r in await db.tts_abbrevs(ctx.guild.id)}
    if word not in existing and len(existing) >= ABBREV_MAX:
        await ctx.send(f"❌ 줄임말은 서버마다 {ABBREV_MAX}개까지예요. `%읽기 줄임말설정 삭제 <글자>`로 지워주세요.")
        return
    await db.set_tts_abbrev(ctx.guild.id, word, "" if reading == SILENT else reading, ctx.author.id)
    abbrev_cache.pop(ctx.guild.id, None)
    if reading == SILENT:
        await ctx.send(f"🔇 줄임말 저장: `{word}` → 안 읽음")
    else:
        await ctx.send(f"✅ 줄임말 저장: `{word}` → **{reading}**")


@commands.command(name="줄임말삭제", usage="<글자>")
async def tts_abbrev_delete(ctx, *, word: str = None):
    await tts_abbrev_set(ctx, "삭제", reading=word)


@commands.command(name="줄임말")
async def tts_abbrev_list(ctx):
    if ctx.guild is None:
        return
    rows = await db.tts_abbrevs(ctx.guild.id)
    embed = discord.Embed(title=f"🗣️ TTS 줄임말 ({len(rows)}/{ABBREV_MAX})", color=discord.Color.blurple())
    lines = [f"`{r['word']}` → {r['reading'] or '🔇 안 읽음'} · <@{r['set_by']}>" for r in rows]
    description = ""
    for i, line in enumerate(lines):
        if len(description) + len(line) > 3900:
            description += f"… 외 {len(lines) - i}개"
            break
        description += line + "\n"
    embed.description = description or "아직 없어요."
    embed.add_field(name="사용법", value=ABBREV_USAGE, inline=False)
    await ctx.send(embed=embed)


@client.listen("on_message")
async def read_message(message):
    if message.guild is None or message.author.bot:
        return
    reader = readers.get(message.guild.id)
    if reader is None or message.channel != reader.channel:
        return
    if message.content.startswith(client.command_prefix):
        return
    text = clean(message)
    if len(text) > MAX_CHARS:
        try:
            await message.add_reaction(TOO_LONG_REACTION)
        except discord.HTTPException:
            pass
        return
    text = await expand(message.guild.id, text)
    if not text:
        return
    try:
        reader.queue.put_nowait(text)
    except asyncio.QueueFull:
        pass
