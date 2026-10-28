"""관리: 경고, 경고확인, 이용제한 역할 자동 해제"""
import asyncio
import datetime

import discord
from discord.ext import commands
from discord.ui import Button

import database as db
import respond
from bot import client


# ───────────── 이용제한 역할 자동 해제 ─────────────
RESTRICTED_ROLE_ID = 1352540239985643571

async def auto_remove_expired_roles():
    await client.wait_until_ready()
    while True:
        try:
            for guild_id, user_id in await db.expired_restrictions(db.now()):
                guild = client.get_guild(guild_id)
                if guild:
                    role = guild.get_role(RESTRICTED_ROLE_ID)
                    member = guild.get_member(user_id)
                    if role and member and role in member.roles:
                        await member.remove_roles(role)
                        print(f"✅ 역할 제거됨: {member.display_name}")
                await db.set_restriction(guild_id, user_id, None)
        except Exception as e:
            print(f"❌ 이용제한 해제 확인 실패: {e}")

        await asyncio.sleep(60)  # 1분마다 확인


# 유저 찾기 함수
async def find_member(ctx, name_or_mention):
    if name_or_mention.startswith("<@") and name_or_mention.endswith(">"):
        user_id = int(name_or_mention.strip("<@!>"))
        return ctx.guild.get_member(user_id)
    for member in ctx.guild.members:
        if member.name == name_or_mention or member.display_name == name_or_mention:
            return member
    return None

# 경고 명령어
@client.command(aliases=["경고"], usage="<이름 | @유저> [횟수] [사유]")
@commands.has_permissions(administrator=True)
async def warn(ctx, name: str, amount: int = 1, *, reason: str = None):
    respond.delete_soon(ctx.message)
    member = await find_member(ctx, name)

    if not member:
        await ctx.send(f"❌ 유저 `{name}` 을 찾을 수 없습니다. 정확한 닉네임이나 멘션을 입력해주세요.")
        return

    guild_id = ctx.guild.id
    user_id = member.id
    view = respond.ConfirmView(ctx.author)

    async def confirm_callback(interaction):
        await respond.defer(interaction)

        # 경고 수 갱신 (0 미만으로는 내려가지 않음)
        count = await db.add_warning_count(guild_id, user_id, amount)

        now = db.now().strftime("%Y-%m-%d %H:%M:%S")
        punishment = "없음"

        try:
            if amount >= 0:
                if count == 1:
                    await member.timeout(datetime.timedelta(minutes=5))
                    punishment = "타임아웃 5분"
                elif count == 2:
                    await member.timeout(datetime.timedelta(minutes=10))
                    punishment = "타임아웃 10분"
                elif count == 3:
                    await member.timeout(datetime.timedelta(hours=1))
                    punishment = "타임아웃 1시간"
                elif count == 4:
                    await member.timeout(datetime.timedelta(days=1))
                    punishment = "타임아웃 1일"
                elif count == 5:
                    await member.timeout(datetime.timedelta(days=7))
                    punishment = "타임아웃 7일"
                elif 6 <= count <= 9:
                    # 이용제한 역할 부여 (해제 시각은 DB 에 저장 → auto_remove_expired_roles 가 해제)
                    days = {6: 3, 7: 7, 8: 30, 9: 90}[count]
                    role = ctx.guild.get_role(RESTRICTED_ROLE_ID)
                    await member.add_roles(role)
                    end_time = db.now() + datetime.timedelta(days=days)
                    await db.set_restriction(guild_id, user_id, end_time)
                    punishment = f"서버 이용제한 역할 부여 ({days}일)"
                elif count >= 10:
                    await member.ban(reason="경고 10회 누적 - 자동 차단")
                    punishment = "영구 차단 (자동 밴)"

                await db.add_warning_log(guild_id, user_id, f"{now} - {reason} (처벌: {punishment})")
            else:
                await db.add_warning_log(guild_id, user_id, f"{now} - ❌ 경고 취소: {reason}")
        except Exception as e:
            punishment += f" ⚠️ 제재 실패: {e}"

        embed = discord.Embed(
            title="⚠️ 경고 완료",
            description=f"{member.mention}님에게 경고 {amount}회를 적용했습니다.\n현재 총 경고 수: {count}회\n처벌: {punishment}",
            color=discord.Color.red()
        )
        await respond.edit(interaction, embed=embed, view=None)

    async def cancel_callback(interaction):
        await respond.defer(interaction)
        embed = discord.Embed(title="❌ 작업 취소됨", color=discord.Color.light_grey())
        await respond.edit(interaction, embed=embed, view=None)

    yes = Button(label="확인", style=discord.ButtonStyle.red)
    no = Button(label="취소", style=discord.ButtonStyle.grey)
    yes.callback = confirm_callback
    no.callback = cancel_callback
    view.add_item(yes)
    view.add_item(no)

    embed = discord.Embed(
        title="🚨 경고 확인",
        description=f"{member.mention}에게 경고 {amount}회를 적용하려고 합니다.\n사유: {reason}\n정말 진행하시겠습니까?",
        color=discord.Color.orange()
    )
    await ctx.send(embed=embed, view=view)

@client.command(aliases=["경고확인"])
async def check_warning(ctx, *, target: str = None):
    respond.delete_soon(ctx.message)
    if target:
        member = None
        # 멘션일 경우
        if target.startswith("<@") and target.endswith(">"):
            try:
                user_id = int(target.strip("<@!>"))
                member = ctx.guild.get_member(user_id)
            except:
                pass
        # 이름으로 찾기
        if not member:
            for m in ctx.guild.members:
                if m.name == target or m.display_name == target:
                    member = m
                    break
        if not member:
            await ctx.send(f"❌ 유저 `{target}` 를 찾을 수 없습니다.")
            return
    else:
        member = ctx.author

    data = await db.get_warning(ctx.guild.id, member.id)

    if not data:
        await ctx.send(f"✅ {member.display_name}님은 경고 기록이 없습니다.")
        return

    embed = discord.Embed(
        title=f"⚠️ {member.display_name}님의 경고 내역",
        color=discord.Color.orange()
    )
    embed.add_field(name="총 경고 수", value=f"{data.get('count', 0)}회", inline=False)

    reasons = data.get("reasons", [])
    if reasons:
        for i, reason in enumerate(reasons[-10:], 1):  # 최근 10개만 표시
            embed.add_field(name=f"{i}.", value=reason, inline=False)
    else:
        embed.add_field(name="📄 사유 없음", value="경고 사유가 없습니다.", inline=False)

    if data["restriction_until"]:
        until = data["restriction_until"].astimezone(db.KST).strftime("%Y-%m-%d %H:%M:%S")
        embed.add_field(name="⏳ 이용제한 만료 예정", value=until, inline=False)

    await ctx.send(embed=embed)
