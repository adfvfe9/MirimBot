"""관리자: 전체 데이터 초기화"""
import discord
from discord.ext import commands

import database as db
import respond
from bot import client
from features import stocks


@client.command(aliases=["초기화"])
@commands.has_permissions(administrator=True)
async def reset_all_data(ctx):
    respond.delete_soon(ctx.message)

    embed = discord.Embed(
        title="⚠️ 전체 초기화 확인",
        description=(
            "**모든 유저의 데이터가 삭제됩니다. 되돌릴 수 없습니다.**\n\n"
            "• 돈, 도박 기록, 기초수급/위로금/파산 기록\n"
            "• 토큰, 상점 아이템, 강화 아이템\n"
            "• 은행 대출/적금/미납금\n"
            "• 보유 주식, 레버리지 포지션, 주가 기록 (주가는 기본가로)\n"
            "• 경고 기록, 건의 내용\n\n"
            "건의 관리자 목록은 유지됩니다."
        ),
        color=discord.Color.red()
    )

    class ResetView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=30)

        async def interaction_check(self, interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await respond.reply(interaction,
                    "❌ 명령어를 실행한 사람만 선택할 수 있습니다.",
                    ephemeral=True
                )
                return False
            return True

        @discord.ui.button(label="전부 초기화", style=discord.ButtonStyle.danger, emoji="🗑️")
        async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
            await respond.defer(interaction)
            self.stop()
            await db.reset_all()

            # 메모리에 들고 있던 주가/시장 상태도 처음 상태로 (DB 가 비어 있으면 기본값으로 다시 만든다)
            await stocks.load_stock_prices()
            await stocks.load_market_state()

            await respond.edit(interaction,
                embed=discord.Embed(
                    title="🗑️ 전체 초기화 완료",
                    description="모든 데이터가 삭제되었습니다.",
                    color=discord.Color.red()
                ).set_footer(text=f"실행자: {ctx.author.display_name}"),
                view=None
            )

        @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary, emoji="❌")
        async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
            await respond.defer(interaction)
            self.stop()
            await respond.edit(interaction,
                embed=discord.Embed(
                    title="✅ 초기화 취소",
                    description="아무것도 삭제되지 않았습니다.",
                    color=discord.Color.green()
                ),
                view=None
            )

        async def on_timeout(self):
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass

    view = ResetView()
    view.message = await ctx.send(embed=embed, view=view)


@reset_all_data.error
async def reset_all_data_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ 이 명령어는 관리자만 사용할 수 있어요!")
