"""버튼 / 입력창(모달) 응답 도우미.

디스코드는 버튼을 누르면 3초 안에 응답해야 하고, 늦으면 실제로는 처리됐어도
화면에 "상호작용 실패"가 뜬다. DB 가 느릴 때(서버가 멀거나 DB 가 잠에서 깰 때) 3초를 넘기기 쉽다.

그래서 버튼 콜백은 맨 처음에 defer() 로 "받았어"라고 먼저 답하고, 일을 다 한 뒤에
edit() / reply() 로 결과를 보여준다. edit / reply 는 먼저 답했는지에 따라 알맞은 방법을 고른다.

    async def confirm_callback(interaction):
        await respond.defer(interaction)
        ... DB 작업 ...
        await respond.edit(interaction, embed=result, view=None)
"""
import discord


async def defer(interaction: discord.Interaction) -> None:
    """아직 응답 전이면 "받았어"라고만 먼저 답한다. (메시지는 그대로)"""
    if not interaction.response.is_done():
        try:
            await interaction.response.defer()
        except discord.HTTPException:
            pass


async def edit(interaction: discord.Interaction, **kwargs) -> None:
    """버튼이 달린 원래 메시지를 수정한다."""
    if interaction.response.is_done():
        await interaction.edit_original_response(**kwargs)
    else:
        await interaction.response.edit_message(**kwargs)


async def reply(interaction: discord.Interaction, content=None, *, ephemeral: bool = False, **kwargs) -> None:
    """새 메시지로 답한다. ephemeral=True 면 누른 사람에게만 보인다."""
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=ephemeral, **kwargs)
    else:
        await interaction.response.send_message(content, ephemeral=ephemeral, **kwargs)
