"""서버 연장 알림: 무료 호스팅을 주기적으로 연장해야 해서, 봇 주인에게 DM 으로 알려준다.

- 마지막 연장 후 REMIND_AFTER 가 지나면 DM 을 보내고,
  [연장 완료] 버튼을 누를 때까지 REMIND_REPEAT 마다 다시 보낸다.
- 봇 주인 = 디스코드 개발자 페이지에서 이 봇을 만든 계정 (따로 설정할 필요 없음)
- %연장 명령어로도 연장 완료를 기록할 수 있다. (봇 주인만)
"""
import datetime

import discord
from discord.ext import tasks

import database as db
from bot import client

REMIND_AFTER = datetime.timedelta(days=3)     # 호스팅은 4일마다 연장 → 하루 전에 알림
REMIND_REPEAT = datetime.timedelta(hours=12)  # 연장할 때까지 반복 알림 간격

LAST_RENEWED = "renewal_last_renewed_at"
LAST_REMINDED = "renewal_last_reminded_at"


async def get_time(key):
    value = await db.get_state(key)
    return datetime.datetime.fromisoformat(value) if value else None


async def mark_renewed():
    await db.set_state(LAST_RENEWED, db.now().isoformat())


async def get_owner() -> discord.User:
    app = await client.application_info()
    return app.team.owner if app.team else app.owner


def kst(dt):
    return dt.astimezone(db.KST).strftime("%m월 %d일 %H시 %M분")


class RenewView(discord.ui.View):
    """DM 에 붙는 [연장 완료] 버튼. 봇을 재시작해도 동작한다. (main.py 의 add_view)"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="연장 완료", style=discord.ButtonStyle.green, emoji="✅", custom_id="renewal_done")
    async def done(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != (await get_owner()).id:
            await interaction.response.send_message("❌ 봇 주인만 누를 수 있어요.", ephemeral=True)
            return

        await mark_renewed()
        next_at = db.now() + REMIND_AFTER
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="✅ 연장 완료 기록됨",
                description=f"다음 알림: **{kst(next_at)}**",
                color=discord.Color.green()
            ),
            view=None
        )


@tasks.loop(minutes=30)
async def renewal_reminder_loop():
    try:
        now = db.now()
        last_renewed = await get_time(LAST_RENEWED)

        # 처음 켜졌을 때는 지금 배포(=연장)했다고 보고 기록만 한다.
        if last_renewed is None:
            await mark_renewed()
            return

        if now - last_renewed < REMIND_AFTER:
            return

        last_reminded = await get_time(LAST_REMINDED)
        if last_reminded and last_reminded > last_renewed and now - last_reminded < REMIND_REPEAT:
            return

        days = (now - last_renewed).days
        owner = await get_owner()
        await owner.send(
            embed=discord.Embed(
                title="⏰ 서버 연장할 시간이에요!",
                description=(
                    f"마지막 연장: **{kst(last_renewed)}** ({days}일 전)\n\n"
                    "호스팅 사이트에서 서버를 연장한 뒤 아래 버튼을 눌러주세요.\n"
                    f"버튼을 누를 때까지 {int(REMIND_REPEAT.total_seconds() // 3600)}시간마다 다시 알려드려요."
                ),
                color=discord.Color.orange()
            ),
            view=RenewView()
        )
        await db.set_state(LAST_REMINDED, now.isoformat())
        print(f"[연장 알림] {owner} 에게 DM 전송")

    except discord.Forbidden:
        print("[연장 알림] DM 을 보낼 수 없어요. (봇 주인의 DM 이 막혀 있음)")
    except Exception as e:
        print(f"[연장 알림 오류] {type(e).__name__}: {e}")


@renewal_reminder_loop.before_loop
async def before_renewal_reminder_loop():
    await client.wait_until_ready()


@client.listen("on_ready")
async def start_renewal_reminder_loop():
    if not renewal_reminder_loop.is_running():
        renewal_reminder_loop.start()


@client.command(aliases=["연장"])
async def renewed(ctx):
    """서버를 연장했다고 기록한다. (봇 주인만)"""
    if ctx.author.id != (await get_owner()).id:
        await ctx.send("❌ 봇 주인만 사용할 수 있어요.")
        return

    await mark_renewed()
    await ctx.send(f"✅ 연장 완료로 기록했어요. 다음 알림: **{kst(db.now() + REMIND_AFTER)}**")


@client.command(aliases=["연장확인"])
async def renewal_status(ctx):
    """마지막 연장 시각과 다음 알림 시각을 보여준다. (봇 주인만)"""
    if ctx.author.id != (await get_owner()).id:
        await ctx.send("❌ 봇 주인만 사용할 수 있어요.")
        return

    last_renewed = await get_time(LAST_RENEWED)
    if last_renewed is None:
        await ctx.send("아직 연장 기록이 없어요.")
        return
    await ctx.send(
        f"🗓️ 마지막 연장: **{kst(last_renewed)}**\n"
        f"⏰ 다음 알림: **{kst(last_renewed + REMIND_AFTER)}**"
    )
