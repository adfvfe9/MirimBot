"""일반 명령어: 시간, 패치노트, 도움말, 청소, 장난 명령어 (급식은 school.py)"""

import discord
from discord.ext import commands

import database as db
from bot import client


@client.command(aliases=['시간'])
async def timeget(ctx):
    await ctx.message.delete()
    now = db.now()  # 한국 시간
    current_time = now.strftime("%Y년 %m월 %d일 %H시 %M분 %S초")
    embed = discord.Embed(title="현재 시간 ⏰", description=f"{current_time}", color=0x3498db)
    await ctx.send(embed=embed)

@client.command(aliases=['패치노트'])
async def patchnote(ctx):
    await ctx.message.delete()
    # 패치노트에는 가장 최근 a.b.c 버전의 내용만 보여준다. (d 자리 수정 · 지난 버전은 노션 "미림봇 업데이트 내용")
    embed = discord.Embed(
        title="📜 패치노트 v1.3.7 — 슬래시(/) 명령어",
        description="가장 최근 업데이트 내용이에요. 지난 업데이트와 작은 수정은 노션 **미림봇 업데이트 내용**에서, 명령어는 `%도움말`에서!",
        color=0xf1c40f,  # 노란색
        url=UPDATES_URL,
    )
    embed.add_field(
        name="⌨️ 슬래시(/) 명령어",
        value=(
            "- 채팅창에 `/`를 치면 미림봇 명령어 목록이 뜨고, 고르면 무엇을 넣어야 하는지 입력칸이 나와요\n"
            "- 주식 이름 · 내 강화 아이템 · 내 칭호 · 포지션 번호는 **자동완성**으로 골라요\n"
            "- 이름은 %명령어와 같아요 (`%주식구매` = `/주식구매`). %명령어도 그대로 쓸 수 있어요\n"
            "- 관리자 명령어는 `/관리` 아래에 모여 있고 관리자에게만 보여요 · TTS 줄임말 지우기는 `/줄임말삭제`"
        ),
        inline=False
    )
    embed.add_field(
        name="🧭 길라잡이 · 기타",
        value=(
            "- `%도움말`에 처음 온 사람을 위한 **미림봇 길라잡이** 링크가 생겼어요\n"
            "- `%패치노트`는 이제 가장 최근 업데이트만 보여줘요\n"
            "- `%주식절반구매` 확인창 · `%주식` 뉴스 표시 안내 문구를 실제 동작에 맞게 고쳤어요"
        ),
        inline=False
    )
    embed.set_footer(text="업데이트: 2026-10-25 · 버전은 a.b.c.d (대격변 · 큰 기능 · 기능 추가 · 수정)")
    await ctx.send(embed=embed)

GUIDE_URL = "https://www.notion.so/402f2c1e985981099ce1d05399425c39"      # 🧭 미림봇 길라잡이
UPDATES_URL = "https://www.notion.so/20bf2c1e985980d0bf91e2c6a6e63dd7"    # 📜 미림봇 업데이트 내용
COMMANDS_URL = "https://www.notion.so/20cf2c1e9859807781bac6f3ce06c317?v=20cf2c1e98598080afbc000cdbab9133"


@client.command(aliases=["도움말", "가이드"])
async def 명령어(ctx):
    await ctx.message.delete()

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


@client.command(aliases=["청소"])
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
