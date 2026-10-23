"""통화방 소리: 음악과 TTS 를 한 통화방에서 동시에 내보낸다

디스코드 봇은 서버마다 소리를 하나만 틀 수 있어서, 음악을 틀다가 TTS 를 틀면 음악이 끊긴다.
그래서 서버마다 Mixer 하나를 틀어두고, 음악 / TTS 소리를 20ms 씩 읽어서 더한 뒤 내보낸다.
  - 음악: 한 번에 한 곡 (끝나면 on_music_end 로 알린다) · 볼륨 · 일시정지
  - TTS: 문장을 차례로 (앞 문장이 끝나야 다음 문장). 읽는 동안 음악 소리를 조금 줄인다
  - 낼 소리가 없으면 멈추고, 새 소리가 들어오면 kick() 으로 다시 튼다.

통화방에 들어가고 나가는 것도 여기서 한다. (music.py / tts.py 가 같이 쓴다)
  - in_use: 각 기능이 "지금 쓰는 중" 인지 알려주는 함수들 → busy()
  - on_leave: 봇이 나갈 때 각 기능이 자기 상태를 정리하는 함수들
  - 통화방에 봇만 남으면 알아서 나간다.
"""
import discord
import numpy as np
from collections import deque

from bot import client

FRAME = discord.opus.Encoder.FRAME_SIZE      # 20ms (48kHz · 스테레오 · 16비트) = 3840바이트
DUCK = 0.5                                   # TTS 를 읽는 동안 음악 볼륨에 곱하는 값

in_use = []      # guild → bool
on_leave = []    # guild → None
alone_hooks = [] # guild → 코루틴. 통화방에 봇만 남아서 나가기 직전에 (안내 메시지)


class Mixer(discord.AudioSource):
    """read() 는 디스코드 재생 스레드에서, 나머지는 봇 이벤트 루프에서 불린다."""
    def __init__(self, guild):
        self.guild = guild
        self.music = None
        self.music_volume = 0.5
        self.music_paused = False
        self.on_music_end = None      # 음악이 끝까지 재생되면 이벤트 루프에서 불린다
        self.speech = deque()

    def is_opus(self):
        return False

    def cleanup(self):
        pass    # 소리가 없어서 멈출 때마다 불린다. 소리는 clear() 로만 정리한다

    def active(self):
        return bool((self.music and not self.music_paused) or self.speech)

    def read(self):
        mixed = None
        speech_data = self._read_speech()
        music = self.music
        if music is not None and not self.music_paused:
            data = music.read()
            if len(data) < FRAME:
                if self.music is music:      # 끝까지 재생했다 (스킵이면 이미 바뀌어 있다)
                    self.music = None
                    client.loop.call_soon_threadsafe(self._music_ended, music)
            else:
                volume = self.music_volume * (DUCK if speech_data else 1)
                mixed = np.frombuffer(data, dtype=np.int16).astype(np.float32) * volume
        if speech_data:
            speech = np.frombuffer(speech_data, dtype=np.int16).astype(np.float32)
            mixed = speech if mixed is None else mixed + speech
        if mixed is None:
            return b""      # 낼 소리가 없다 → 멈춤 (새 소리가 오면 kick)
        return np.clip(mixed, -32768, 32767).astype(np.int16).tobytes()

    def _read_speech(self):
        while True:
            try:
                current = self.speech[0]
            except IndexError:
                return None
            data = current.read()
            if len(data) == FRAME:
                return data
            if self.speech and self.speech[0] is current:   # 다 읽었다 → 다음 문장
                self.speech.popleft()
            current.cleanup()

    def _music_ended(self, source):
        source.cleanup()
        if self.on_music_end:
            self.on_music_end()

    # ── 이벤트 루프에서 ──

    def set_music(self, source):
        old, self.music = self.music, source
        self.music_paused = False
        if old:
            old.cleanup()
        self.kick()

    def stop_music(self, notify=False):
        """지금 곡을 내린다. notify 면 끝까지 들은 것처럼 on_music_end 를 부른다 (스킵)"""
        old, self.music = self.music, None
        self.music_paused = False
        if old:
            old.cleanup()
            if notify and self.on_music_end:
                self.on_music_end()

    def add_speech(self, source):
        self.speech.append(source)
        self.kick()

    def clear(self):
        self.on_music_end = None
        self.stop_music()
        while self.speech:
            self.speech.popleft().cleanup()

    def kick(self):
        """멈춰 있는데 낼 소리가 있으면 다시 튼다"""
        voice = self.guild.voice_client
        if voice is None or not voice.is_connected() or voice.is_playing() or not self.active():
            return

        def after(error):
            if error:
                print(f"[통화방] 재생 오류: {error}")
            client.loop.call_soon_threadsafe(self.kick)   # 멈추는 사이에 들어온 소리가 있으면

        voice.play(self, after=after)


mixers = {}


def mixer_of(guild):
    if guild.id not in mixers:
        mixers[guild.id] = Mixer(guild)
    return mixers[guild.id]


def busy(guild):
    return any(check(guild) for check in in_use)


async def join(channel):
    """channel 로 들어간다 (이미 다른 통화방이면 옮긴다). 실패하면 이유를, 되면 None"""
    voice = channel.guild.voice_client
    try:
        if voice is None:
            await channel.connect(self_deaf=True)
        elif voice.channel != channel:
            await voice.move_to(channel)
    except (discord.ClientException, TimeoutError) as e:
        return type(e).__name__
    return None


def _reset(guild):
    mixer = mixers.pop(guild.id, None)
    if mixer:
        mixer.clear()
    for hook in on_leave:
        hook(guild)


async def leave(guild):
    _reset(guild)
    if guild.voice_client:
        await guild.voice_client.disconnect(force=True)


def same_channel(member, guild):
    """member 가 봇과 같은 통화방에 있는지"""
    voice = guild.voice_client
    return bool(voice and member.voice and member.voice.channel == voice.channel)


@client.listen("on_voice_state_update")
async def leave_when_alone(member, before, after):
    """통화방에 봇만 남으면 나간다. 봇이 강제로 끊기면 상태를 정리한다."""
    guild = member.guild
    if member.id == client.user.id:
        if after.channel is None:
            _reset(guild)
        return
    voice = guild.voice_client
    if voice and before.channel == voice.channel and not any(not m.bot for m in voice.channel.members):
        for hook in alone_hooks:
            await hook(guild)
        await leave(guild)

