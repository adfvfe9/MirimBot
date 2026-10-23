"""음악: 유튜브 노래를 통화방에서 재생한다

    %재생 <유튜브 링크 | 제목>   호출한 사람이 있는 통화방에 들어가서 재생 (재생 중이면 대기열에 추가)
    %스킵                       지금 곡 넘기기
    %일시정지 / %다시재생
    %정지                       재생을 멈추고 대기열을 비운 뒤 나가기 (%나가기)
    %대기열                     지금 곡과 다음 곡들
    %지금곡                     지금 곡 정보 + 버튼 (⏯️ ⏭️ ⏹️)
    %볼륨 [0~100]

- 노래 찾기 / 주소 얻기는 yt-dlp, 소리 변환은 ffmpeg 가 한다.
  ffmpeg 는 서버에 설치돼 있지 않아도 되게 pip 패키지(imageio-ffmpeg)에 들어 있는 것을 쓴다.
  (서버에 ffmpeg 가 있으면 그걸 먼저 쓴다)
- 유튜브 재생 주소는 몇 시간 뒤 만료돼서, 대기열에는 영상 주소만 넣고 재생할 때 다시 받아온다.
- 조작(스킵 / 정지 등)은 봇과 같은 통화방에 있는 사람만 할 수 있다.
- 대기열이 끝나고 5분 동안 아무것도 안 틀거나, 통화방에 봇만 남으면 나간다.
"""
import asyncio
import functools
import shutil
from collections import deque

import discord
import yt_dlp
from discord.ui import Button, View

import respond
from bot import client

QUEUE_MAX = 50
MAX_DURATION = 3 * 60 * 60     # 3시간보다 긴 영상은 안 받는다 (라이브 방송 포함)
IDLE_SECONDS = 300
DEFAULT_VOLUME = 0.5

YDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "default_search": "ytsearch1",   # 링크가 아니면 유튜브에서 제목으로 찾는다
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
}
FFMPEG_BEFORE = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"   # 스트림이 잠깐 끊겨도 다시 붙는다
FFMPEG_OPTIONS = "-vn"


def ffmpeg_path():
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def fmt_time(seconds):
    if not seconds:
        return "?"
    seconds = int(seconds)
    h, m, s = seconds // 3600, seconds // 60 % 60, seconds % 60
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


def _extract(query):
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        info = ydl.extract_info(query, download=False)
    if info and "entries" in info:          # 검색 결과
        entries = [e for e in info["entries"] if e]
        info = entries[0] if entries else None
    return info


async def extract(query):
    """노래 정보 (블로킹이라 다른 스레드에서). 못 찾으면 None"""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, functools.partial(_extract, query))
    except yt_dlp.utils.DownloadError as e:
        print(f"[음악] 찾기 실패 {query!r}: {e}")
        return None


class Track:
    def __init__(self, info, requester):
        self.title = info.get("title") or "제목 없음"
        self.url = info.get("webpage_url") or info.get("original_url")
        self.duration = info.get("duration")
        self.thumbnail = info.get("thumbnail")
        self.requester = requester


class Player:
    """서버(길드) 하나의 재생 상태"""
    def __init__(self, guild):
        self.guild = guild
        self.queue = deque()
        self.current = None
        self.channel = None          # 안내를 보낼 텍스트 채널
        self.volume = DEFAULT_VOLUME
        self.idle_task = None

    @property
    def voice(self):
        return self.guild.voice_client

    async def play_next(self):
        if self.voice is None or not self.voice.is_connected():
            return
        if not self.queue:
            self.current = None
            self.start_idle_timer()
            return
        track = self.queue.popleft()
        info = await extract(track.url)        # 재생 주소는 만료되니까 지금 다시 받는다
        if info is None or not info.get("url"):
            await self.say(f"⚠️ **{track.title}** 을(를) 재생할 수 없어서 넘겼어요.")
            return await self.play_next()
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(info["url"], executable=ffmpeg_path(),
                                   before_options=FFMPEG_BEFORE, options=FFMPEG_OPTIONS),
            volume=self.volume,
        )
        self.current = track
        self.cancel_idle_timer()

        def after(error):
            if error:
                print(f"[음악] 재생 오류: {error}")
            asyncio.run_coroutine_threadsafe(self.play_next(), client.loop)

        self.voice.play(source, after=after)
        await self.say(embed=now_playing_embed(self), view=ControlView(self))

    async def say(self, content=None, **kwargs):
        if self.channel:
            try:
                await self.channel.send(content, **kwargs)
            except discord.HTTPException as e:
                print(f"[음악] 메시지 전송 실패: {e}")

    def start_idle_timer(self):
        self.cancel_idle_timer()
        self.idle_task = asyncio.create_task(self.leave_when_idle())

    def cancel_idle_timer(self):
        if self.idle_task and not self.idle_task.done():
            self.idle_task.cancel()
        self.idle_task = None

    async def leave_when_idle(self):
        await asyncio.sleep(IDLE_SECONDS)
        if self.voice and not self.voice.is_playing() and not self.voice.is_paused():
            await self.say(f"💤 {IDLE_SECONDS // 60}분 동안 재생할 노래가 없어서 나갈게요.")
            await self.stop()

    async def stop(self):
        self.queue.clear()
        self.current = None
        self.cancel_idle_timer()
        if self.voice:
            await self.voice.disconnect(force=True)


players = {}


def get_player(guild):
    if guild.id not in players:
        players[guild.id] = Player(guild)
    return players[guild.id]


def now_playing_embed(player):
    t = player.current
    embed = discord.Embed(title="🎵 지금 재생 중", color=discord.Color.red())
    if t is None:
        embed.description = "재생 중인 노래가 없어요."
        return embed
    embed.description = f"**[{t.title}]({t.url})**"
    embed.add_field(name="길이", value=fmt_time(t.duration), inline=True)
    embed.add_field(name="신청", value=t.requester.mention, inline=True)
    embed.add_field(name="대기열", value=f"{len(player.queue)}곡", inline=True)
    if t.thumbnail:
        embed.set_thumbnail(url=t.thumbnail)
    embed.set_footer(text=f"볼륨 {int(player.volume * 100)}% · %대기열 · %스킵 · %정지")
    return embed


def same_channel(member, player):
    """조작하는 사람이 봇과 같은 통화방에 있는지"""
    return bool(player.voice and member.voice and member.voice.channel == player.voice.channel)


class ControlView(View):
    def __init__(self, player):
        super().__init__(timeout=None)
        self.player = player
        for emoji, callback in (("⏯️", self.pause_resume), ("⏭️", self.skip), ("⏹️", self.stop)):
            button = Button(emoji=emoji, style=discord.ButtonStyle.secondary)
            button.callback = callback
            self.add_item(button)

    async def interaction_check(self, interaction):
        if not same_channel(interaction.user, self.player):
            await respond.reply(interaction, "🎧 봇과 같은 통화방에 있어야 조작할 수 있어요.", ephemeral=True)
            return False
        return True

    async def pause_resume(self, interaction):
        voice = self.player.voice
        if voice.is_paused():
            voice.resume()
            await respond.reply(interaction, f"▶️ {interaction.user.display_name}님이 다시 재생했어요.")
        elif voice.is_playing():
            voice.pause()
            await respond.reply(interaction, f"⏸️ {interaction.user.display_name}님이 일시정지했어요.")
        else:
            await respond.reply(interaction, "재생 중인 노래가 없어요.", ephemeral=True)

    async def skip(self, interaction):
        if self.player.voice.is_playing() or self.player.voice.is_paused():
            await respond.reply(interaction, f"⏭️ {interaction.user.display_name}님이 넘겼어요.")
            self.player.voice.stop()     # after 콜백이 다음 곡을 튼다
        else:
            await respond.reply(interaction, "재생 중인 노래가 없어요.", ephemeral=True)

    async def stop(self, interaction):
        await respond.reply(interaction, f"⏹️ {interaction.user.display_name}님이 재생을 멈췄어요. 안녕!")
        await self.player.stop()


# ───────────── 명령어 ─────────────

async def check_control(ctx):
    """조작 명령어 공통: 봇이 통화방에 있고, 같은 통화방에 있어야 한다. 되면 Player, 안 되면 None"""
    if ctx.guild is None:
        return None
    player = get_player(ctx.guild)
    if player.voice is None:
        await ctx.send("🎧 지금 재생 중이 아니에요. `%재생 <제목>`으로 틀어보세요!")
        return None
    if not same_channel(ctx.author, player):
        await ctx.send("🎧 봇과 같은 통화방에 있어야 조작할 수 있어요.")
        return None
    return player


@client.command(aliases=["재생", "play", "p"])
async def music_play(ctx, *, query: str = None):
    if ctx.guild is None:
        return
    if not query:
        await ctx.send("사용법: `%재생 <유튜브 링크 | 제목>` 예) `%재생 아이유 밤편지`")
        return
    if ctx.author.voice is None or ctx.author.voice.channel is None:
        await ctx.send("🎧 먼저 통화방에 들어가 주세요! 들어가 있는 통화방으로 봇이 따라가요.")
        return
    player = get_player(ctx.guild)
    target = ctx.author.voice.channel
    if player.voice and player.voice.channel != target:
        if player.voice.is_playing() or player.voice.is_paused() or player.queue:
            await ctx.send(f"🎧 지금 **{player.voice.channel.name}**에서 재생 중이에요. 그 통화방으로 와주세요!")
            return
        await player.voice.move_to(target)
    if len(player.queue) >= QUEUE_MAX:
        await ctx.send(f"❌ 대기열은 {QUEUE_MAX}곡까지예요.")
        return

    async with ctx.typing():
        info = await extract(query)
    if info is None:
        await ctx.send(f"❌ `{query}` 노래를 찾지 못했어요.")
        return
    if info.get("is_live") or (info.get("duration") or 0) > MAX_DURATION:
        await ctx.send(f"❌ 라이브 방송이나 {MAX_DURATION // 3600}시간이 넘는 영상은 재생할 수 없어요.")
        return

    if player.voice is None:
        try:
            await target.connect(self_deaf=True)
        except (discord.ClientException, asyncio.TimeoutError) as e:
            await ctx.send(f"❌ 통화방에 들어가지 못했어요. ({type(e).__name__})")
            return
    player.channel = ctx.channel
    track = Track(info, ctx.author)
    player.queue.append(track)
    if player.voice.is_playing() or player.voice.is_paused():
        await ctx.send(f"➕ 대기열 {len(player.queue)}번에 추가: **{track.title}** ({fmt_time(track.duration)})")
    else:
        await player.play_next()


@client.command(aliases=["스킵", "skip"])
async def music_skip(ctx):
    player = await check_control(ctx)
    if player is None:
        return
    if not (player.voice.is_playing() or player.voice.is_paused()):
        await ctx.send("재생 중인 노래가 없어요.")
        return
    await ctx.send(f"⏭️ **{player.current.title if player.current else '지금 곡'}** 을(를) 넘겼어요.")
    player.voice.stop()


@client.command(aliases=["일시정지", "pause"])
async def music_pause(ctx):
    player = await check_control(ctx)
    if player and player.voice.is_playing():
        player.voice.pause()
        await ctx.send("⏸️ 일시정지했어요. `%다시재생`으로 이어서 들을 수 있어요.")


@client.command(aliases=["다시재생", "resume"])
async def music_resume(ctx):
    player = await check_control(ctx)
    if player and player.voice.is_paused():
        player.voice.resume()
        await ctx.send("▶️ 다시 재생해요.")


@client.command(aliases=["정지", "나가기", "stop"])
async def music_stop(ctx):
    player = await check_control(ctx)
    if player is None:
        return
    await player.stop()
    await ctx.send("⏹️ 재생을 멈추고 나왔어요.")


@client.command(aliases=["대기열", "queue", "q"])
async def music_queue(ctx):
    if ctx.guild is None:
        return
    player = get_player(ctx.guild)
    if player.current is None and not player.queue:
        await ctx.send("📭 대기열이 비어 있어요. `%재생 <제목>`으로 추가해보세요!")
        return
    embed = discord.Embed(title="🎶 대기열", color=discord.Color.red())
    if player.current:
        embed.add_field(name="▶️ 지금", value=f"[{player.current.title}]({player.current.url}) · {fmt_time(player.current.duration)}", inline=False)
    lines = [
        f"`{i}.` {t.title[:60]} · {fmt_time(t.duration)} · {t.requester.display_name}"
        for i, t in enumerate(list(player.queue)[:15], start=1)
    ]
    if lines:
        more = f"\n… 외 {len(player.queue) - 15}곡" if len(player.queue) > 15 else ""
        embed.add_field(name=f"다음 ({len(player.queue)}곡)", value="\n".join(lines) + more, inline=False)
    total = sum(t.duration or 0 for t in player.queue)
    embed.set_footer(text=f"남은 시간 약 {fmt_time(total)}")
    await ctx.send(embed=embed)


@client.command(aliases=["지금곡", "np"])
async def music_now(ctx):
    if ctx.guild is None:
        return
    player = get_player(ctx.guild)
    await ctx.send(embed=now_playing_embed(player), view=ControlView(player) if player.current else None)


@client.command(aliases=["볼륨", "volume"])
async def music_volume(ctx, value: int = None):
    player = await check_control(ctx)
    if player is None:
        return
    if value is None:
        await ctx.send(f"🔊 지금 볼륨 {int(player.volume * 100)}%  (`%볼륨 0~100`)")
        return
    if not 0 <= value <= 100:
        await ctx.send("❌ 0~100 사이로 입력해주세요.")
        return
    player.volume = value / 100
    if player.voice.source and isinstance(player.voice.source, discord.PCMVolumeTransformer):
        player.voice.source.volume = player.volume
    await ctx.send(f"🔊 볼륨을 {value}%로 바꿨어요.")


@client.listen("on_voice_state_update")
async def leave_when_alone(member, before, after):
    """통화방에 봇만 남으면 나간다. 봇이 강제로 끊기면 상태를 정리한다."""
    guild = member.guild
    player = players.get(guild.id)
    if player is None:
        return
    if member.id == client.user.id and after.channel is None:   # 봇이 나가졌다
        player.queue.clear()
        player.current = None
        player.cancel_idle_timer()
        return
    voice = player.voice
    if voice and before.channel == voice.channel and not any(not m.bot for m in voice.channel.members):
        await player.say("👋 통화방에 아무도 없어서 나갈게요.")
        await player.stop()
