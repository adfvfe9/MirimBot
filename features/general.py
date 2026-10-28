"""일반 명령어: 시간, 패치노트, 도움말, 청소, 장난 명령어 (급식은 school.py)"""

import discord
from discord.ext import commands

import database as db
import respond
from bot import client
from features import errors


@commands.command(name="시간")
async def timeget(ctx):
    respond.delete_soon(ctx.message)
    now = db.now()  # 한국 시간
    current_time = now.strftime("%Y년 %m월 %d일 %H시 %M분 %S초")
    embed = discord.Embed(title="현재 시간 ⏰", description=f"{current_time}", color=0x3498db)
    await ctx.send(embed=embed)

@commands.command(name="패치노트")
async def patchnote(ctx):
    respond.delete_soon(ctx.message)
    # 패치노트에는 가장 최근 a.b.c 버전의 내용만 보여준다. (d 자리 수정 · 지난 버전은 노션 "미림봇 업데이트 내용")
    embed = discord.Embed(
        title="📜 패치노트 v1.3.9 — 명령어 개편",
        description="가장 최근 업데이트 내용이에요. 지난 업데이트와 작은 수정은 노션 **미림봇 업데이트 내용**에서, 명령어는 `%봇 도움말`에서!",
        color=0xf1c40f,  # 노란색
        url=UPDATES_URL,
    )
    embed.add_field(
        name="📂 명령어를 상위 명령어 아래로 묶었어요",
        value=(
            "- `%주식 구매 JAVA 10` `%주식 롱 JAVA 5만 5` `%머니 송금 @친구 1000` `%게임 전적` … `/`도 똑같이 `/주식 구매`\n"
            "- 머니 · 자산 · 주식 · 강화 · 토큰 · 코인 · 채굴 · 도박 · 끝말잇기 · 게임 · 칭호 · 역할 · 학교 · 음악 · 읽기 · 봇 "
            "(+ 은행 · 미션 · 관리)\n"
            "- `/`를 치면 상위 명령어가 보이고, 고르면 그 아래 명령어와 입력칸이 나와요"
        ),
        inline=False
    )
    embed.add_field(
        name="⌨️ 짧게 치기",
        value=(
            "- 상위 명령어만 쳐도 돼요: `%주식` = 시세 · `%머니` = 잔액 · `%도박 5만` = 걸기 · `%강화 칼` = 강화 · `%게임` = 전적\n"
            "- 예전 명령어(`%주식구매` `%포지션` `%도박올인` …)도 그대로 돼요"
        ),
        inline=False
    )
    embed.add_field(
        name="🧩 합친 명령어 · 💰 금액",
        value=(
            "- 주식올인 · 절반구매 → `%주식 구매 JAVA 올인 | 절반` · 도박올인 → `%도박 올인` · 토큰최대교환 → `%토큰 구매 최대`\n"
            "- 롤등록 · 발로등록 → `%게임 등록 롤 | 발로 닉네임#태그`\n"
            "- 금액 칸에 `5만` `1,000` `올인` `절반`을 `/`에서도 쓸 수 있어요"
        ),
        inline=False
    )
    embed.set_footer(text="업데이트: 2026-10-28 · 버전은 a.b.c.d (대격변 · 큰 기능 · 기능 추가 · 수정)")
    await ctx.send(embed=embed)

GUIDE_URL = "https://www.notion.so/402f2c1e985981099ce1d05399425c39"      # 🧭 미림봇 길라잡이
UPDATES_URL = "https://www.notion.so/20bf2c1e985980d0bf91e2c6a6e63dd7"    # 📜 미림봇 업데이트 내용
COMMANDS_URL = "https://www.notion.so/20cf2c1e9859807781bac6f3ce06c317?v=20cf2c1e98598080afbc000cdbab9133"


@commands.command(name="도움말")
async def 명령어(ctx):
    respond.delete_soon(ctx.message)

    # 상위 명령어와 하위 명령어 (features/groups.py 에서 단 그대로)
    lines = [
        f"`%{group.name}` " + " · ".join(sub.name for sub in errors.subcommands(group))
        for group in client.commands if isinstance(group, commands.Group) and group.name != "관리"
    ]
    embed = discord.Embed(
        title="📘 미림봇 도움말 (노션)",
        description=(
            "처음이라면 **길라잡이**부터 읽어보세요! 자세한 설명은 노션 명령어 목록에 있어요.\n"
            "명령어는 `%주식 구매 JAVA 10` 처럼 **상위 명령어 + 하위 명령어**예요. `/`도 똑같아요.\n\n"
            + "\n".join(lines) + "\n`%은행` `%미션`"
        ),
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
    embed.set_footer(text="노션에서 실시간으로 최신 내용이 갱신됩니다. · %봇 패치노트")

    await ctx.send(embed=embed)


@commands.command(name="청소", usage="<개수>")
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
