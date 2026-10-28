"""일반 명령어: 시간, 패치노트, 도움말, 청소, 장난 명령어 (급식은 school.py)"""

import discord
from discord.ext import commands

import database as db
import respond
from bot import client


@client.command(aliases=['시간'])
async def timeget(ctx):
    respond.delete_soon(ctx.message)
    now = db.now()  # 한국 시간
    current_time = now.strftime("%Y년 %m월 %d일 %H시 %M분 %S초")
    embed = discord.Embed(title="현재 시간 ⏰", description=f"{current_time}", color=0x3498db)
    await ctx.send(embed=embed)

@client.command(aliases=['패치노트'])
async def patchnote(ctx):
    respond.delete_soon(ctx.message)
    # 패치노트에는 가장 최근 a.b.c 버전의 내용만 보여준다. (d 자리 수정 · 지난 버전은 노션 "미림봇 업데이트 내용")
    embed = discord.Embed(
        title="📜 패치노트 v1.3.8 — 롤 · 발로 연동 · 오늘의 미림봇 · 활동 보상",
        description="가장 최근 업데이트 내용이에요. 지난 업데이트와 작은 수정은 노션 **미림봇 업데이트 내용**에서, 명령어는 `%도움말`에서!",
        color=0xf1c40f,  # 노란색
        url=UPDATES_URL,
    )
    embed.add_field(
        name="🎮 롤 · 발로란트 연동",
        value=(
            "- `%롤등록 닉네임#태그` · `%발로등록 닉네임#태그` 하면 **랭크 게임**이 끝날 때마다 소식 채널에 결과가 떠요\n"
            "- `%베팅 @친구 승 5000` 친구 **다음 랭크 판**에 걸기 · 맞힌 사람끼리 건 비율대로 나눠 가져요 (수수료 5%)\n"
            "- 자기 판엔 못 걸고, 한쪽에만 걸리거나 다시하기 · 무승부면 돌려줘요 · `%베팅목록` `%전적`"
        ),
        inline=False
    )
    embed.add_field(
        name="🌙 오늘의 미림봇 · 📣 자랑 알림",
        value=(
            "- 매일 밤 9시 소식 채널에 **오늘의 미림봇**: 많이 번 / 잃은 사람, 랭크 MVP, 강화 · 잭팟, 통화방 · 수다왕 …\n"
            "- 도박 잭팟 · 레버리지 대박 · 강제청산 · 가위바위보 5연승 · 칭호 획득을 바로 알려줘요"
        ),
        inline=False
    )
    embed.add_field(
        name="🎧 활동 보상",
        value=(
            "- **통화방**에 2명 이상 있으면 1분마다 10 byte, 1시간마다 +5 (최대 분당 50) · 헤드셋 끈 사람 · 잠수 채널 제외\n"
            "- **채팅**하면 1글자당 0.5 byte (메시지당 최대 50, 시간당 최대 3,000) · 명령어는 제외"
        ),
        inline=False
    )
    embed.set_footer(text="업데이트: 2026-10-26 · 버전은 a.b.c.d (대격변 · 큰 기능 · 기능 추가 · 수정)")
    await ctx.send(embed=embed)

GUIDE_URL = "https://www.notion.so/402f2c1e985981099ce1d05399425c39"      # 🧭 미림봇 길라잡이
UPDATES_URL = "https://www.notion.so/20bf2c1e985980d0bf91e2c6a6e63dd7"    # 📜 미림봇 업데이트 내용
COMMANDS_URL = "https://www.notion.so/20cf2c1e9859807781bac6f3ce06c317?v=20cf2c1e98598080afbc000cdbab9133"


@client.command(aliases=["도움말", "가이드"])
async def 명령어(ctx):
    respond.delete_soon(ctx.message)

    embed = discord.Embed(
        title="📘 미림봇 도움말 (노션)",
        description="처음이라면 **길라잡이**부터 읽어보세요! 모든 명령어는 명령어 목록에 있어요.",
        color=discord.Color.blue(),
        url=GUIDE_URL
    )
    embed.add_field(
        name="🧭 처음이라면: 미림봇 길라잡이",
        value=f"[👉 무엇을 할 수 있는지, 어떻게 시작하는지]({GUIDE_URL})",
        inline=False
    )
    embed.add_field(
        name="📋 모든 명령어",
        value=f"[👉 명령어 목록 열기]({COMMANDS_URL})",
        inline=False
    )
    embed.set_footer(text="노션에서 실시간으로 최신 내용이 갱신됩니다. · %패치노트")

    await ctx.send(embed=embed)


@client.command(aliases=["청소"], usage="<개수>")
@commands.has_permissions(administrator=True)
async def clean(ctx, amount: int):
    # 명령어 메시지 + 그 위의 메시지 amount 개를 지운다 (14일 지난 메시지는 디스코드가 막아서 못 지움)
    await ctx.channel.purge(limit=amount + 1)

@client.command(aliases=["박준현", "ㅄ", "영포티"])
async def fourty(ctx, member: discord.Member = None):
    embed = discord.Embed(
        title='영포티'
    )
    await ctx.send(embed = embed)

@client.command(aliases=["홍성재"])
async def goa(ctx, member: discord.Member = None):
    embed = discord.Embed(
            title='고아',
            description=(
                        "김미영\n"
                        "홍창균\n"
                        "펑"
            ),
            color=discord.Color.gold()
        )
    await ctx.send(embed = embed)
