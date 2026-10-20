"""건의: 건의, 건의목록, 건의제거 (목록/삭제는 DM 에서 관리자만)"""


import discord

import database as db
from bot import client


SUGGESTION_COOLDOWN = 3600  # 초 단위 (1시간)


@client.command(aliases=["건의"])
async def suggestion(ctx, *, content: str = None):
    await ctx.message.delete()
    user_id = ctx.author.id
    now = db.now()

    if not content:
        await ctx.send("❌ 건의 내용을 입력해주세요.\n예: `%건의 강화 시스템 개선해주세요`")
        return

    last_time = (await db.get_user(user_id))["suggestion_last_at"]

    if last_time:
        diff = (now - last_time).total_seconds()
        if diff < SUGGESTION_COOLDOWN:
            remain = int(SUGGESTION_COOLDOWN - diff)
            minutes, seconds = divmod(remain, 60)
            await ctx.send(f"⏳ 아직 건의를 할 수 없어요! 다시 시도하려면 **{minutes}분 {seconds}초** 후에 가능해요.")
            return

    # 건의 저장
    await db.add_suggestion(user_id, content, now)

    embed = discord.Embed(
        title="📮 건의 접수 완료",
        description=f"{ctx.author.mention}님의 건의가 접수되었습니다!\n```{content}```",
        color=discord.Color.blurple()
    )
    embed.set_footer(text="관리자가 확인할 수 있도록 저장되었습니다.")
    await ctx.send(embed=embed)

@client.command(aliases=["건의목록"])
async def suggestion_list(ctx):
    if not isinstance(ctx.channel, discord.DMChannel):
        return  # ❌ DM에서만 허용

    if not await db.is_suggestion_admin(ctx.author.id):
        await ctx.send("❌ 이 명령어를 사용할 수 있는 권한이 없습니다.")
        return

    all_logs = [
        (s["user_id"], s["created_at"].astimezone(db.KST).strftime("%Y-%m-%d %H:%M:%S"), s["content"])
        for s in await db.list_suggestions()
    ]

    if not all_logs:
        await ctx.send("📭 현재 등록된 건의가 없습니다.")
        return

    embed = discord.Embed(
        title="📮 전체 건의사항 목록",
        description="`%건의제거 <번호>`로 개별 삭제 가능",
        color=discord.Color.blurple()
    )

    for idx, (uid, time_str, content) in enumerate(all_logs, start=1):
        try:
            user = await client.fetch_user(int(uid))
            username = f"{user.name}#{user.discriminator}"
        except:
            username = f"Unknown ({uid})"

        embed.add_field(
            name=f"{idx}. ({username}) {time_str}",
            value=content,
            inline=False
        )

    await ctx.send(embed=embed)

@client.command(aliases=["건의제거"])
async def remove_suggestion(ctx, number: int = None):
    if not isinstance(ctx.channel, discord.DMChannel):
        return  # ❌ DM에서만 허용

    if not await db.is_suggestion_admin(ctx.author.id):
        await ctx.send("❌ 이 명령어를 사용할 수 있는 권한이 없습니다.")
        return

    if number is None:
        await ctx.send("❗ 삭제할 건의 번호를 입력해주세요.\n예: `%건의제거 2`")
        return

    # %건의목록 에 보이는 번호 순서와 같다 (오래된 순)
    all_logs = await db.list_suggestions()

    if number <= 0 or number > len(all_logs):
        await ctx.send("❌ 올바른 건의 번호를 입력해주세요.")
        return

    # 삭제할 항목
    del_entry = await db.delete_suggestion(all_logs[number - 1]["id"])
    if del_entry is None:
        await ctx.send("❌ 이미 삭제된 건의입니다.")
        return

    del_time = del_entry["created_at"].astimezone(db.KST).strftime("%Y-%m-%d %H:%M:%S")

    embed = discord.Embed(
        title="🗑️ 건의 삭제 완료",
        description=f"{number}번 건의가 삭제되었습니다.",
        color=discord.Color.red()
    )
    embed.add_field(name="삭제된 건의 내용", value=del_entry["content"], inline=False)
    embed.set_footer(text=f"작성자 ID: {del_entry['user_id']}, 시간: {del_time}")

    await ctx.send(embed=embed)
