"""봇 상태 진단: 어디가 느린지 재서 보여준다

    %봇 핑     디스코드 / DB / 봇 멈춤 시간

- 디스코드: 게이트웨이 핑, 메시지 보내기 · 수정에 걸린 시간 (버튼 누른 뒤 화면이 바뀌는 속도와 비슷하다)
- DB: 연결 하나 빌리는 시간, SELECT 1 왕복 시간, 연결 풀 상태
- 봇 멈춤: 봇은 한 스레드에서 일을 하나씩 처리해서, 오래 걸리는 일 하나가 그동안 모든 명령어를 멈춘다.
  watch_loop_lag() 가 TICK 초마다 깨어나서 늦게 깨어난 만큼을 "멈춘 시간"으로 기록한다.
  (멈춤이 틱 중간에 시작되면 최대 TICK 만큼 짧게 잡힌다)
  LAG_WARN 초보다 길게 멈추면 콘솔에도 남긴다.
"""
import asyncio
import statistics
import time
from collections import deque

import discord
from discord.ext import commands

import database as db
from bot import client

TICK = 0.1
LAG_WARN = 0.2           # 초
LAG_KEEP = 60 * 60       # 1시간 동안의 멈춤 기록만 남긴다
DB_PINGS = 5

lags = deque()           # (기록한 시각, 멈춘 초)


async def watch_loop_lag():
    """setup_hook 에서 한 번 시작한다."""
    loop = asyncio.get_running_loop()
    while True:
        start = loop.time()
        await asyncio.sleep(TICK)
        lag = loop.time() - start - TICK
        now = time.time()
        if lag > LAG_WARN:
            lags.append((now, lag))
            print(f"[봇 멈춤] {lag:.2f}초")
        while lags and lags[0][0] < now - LAG_KEEP:
            lags.popleft()


def grade(ms):
    return "🟢" if ms < 100 else "🟡" if ms < 300 else "🔴"


def ms_text(ms):
    return f"{grade(ms)} {ms:.0f}ms"


async def measure_db():
    t = time.perf_counter()
    async with db.pool().acquire() as conn:
        acquire = (time.perf_counter() - t) * 1000
        rtts = []
        for _ in range(DB_PINGS):
            t = time.perf_counter()
            await conn.fetchval("SELECT 1")
            rtts.append((time.perf_counter() - t) * 1000)
    return acquire, rtts


@commands.command(name="핑")
async def health_ping(ctx):
    t = time.perf_counter()
    message = await ctx.send("🏓 재는 중…")
    send_ms = (time.perf_counter() - t) * 1000

    t = time.perf_counter()
    await message.edit(content="🏓 재는 중… (DB)")
    edit_ms = (time.perf_counter() - t) * 1000

    acquire_ms, rtts = await measure_db()
    pool = db.pool()

    embed = discord.Embed(title="🏓 퐁! 어디가 느린지 재봤어요", color=discord.Color.blurple())
    embed.add_field(
        name="💬 디스코드",
        value=(
            f"게이트웨이 {ms_text(client.latency * 1000)}\n"
            f"메시지 보내기 {ms_text(send_ms)}\n"
            f"메시지 수정 {ms_text(edit_ms)}"
        ),
        inline=True,
    )
    embed.add_field(
        name="🗄️ DB",
        value=(
            f"왕복 {ms_text(statistics.median(rtts))} (최소 {min(rtts):.0f} · 최대 {max(rtts):.0f})\n"
            f"연결 빌리기 {ms_text(acquire_ms)}\n"
            f"연결 {pool.get_size() - pool.get_idle_size()}/{pool.get_size()}개 사용 중 (최대 {pool.get_max_size()})"
        ),
        inline=True,
    )
    worst = max((lag for _, lag in lags), default=0)
    recent = sum(1 for at, _ in lags if at > time.time() - 600)
    embed.add_field(
        name="⏸️ 봇 멈춤 (최근 1시간)",
        value=(
            f"{LAG_WARN}초 넘게 멈춘 횟수 {len(lags)}번 (최근 10분 {recent}번)\n"
            f"가장 길게 멈춘 시간 {grade(worst * 1000)} {worst:.2f}초"
        ),
        inline=False,
    )
    embed.set_footer(text="🟢 100ms 미만 · 🟡 300ms 미만 · 🔴 그 이상 · 명령어 하나는 보통 DB 왕복 몇 번 + 디스코드 1~2번")
    await message.edit(content=None, embed=embed)
