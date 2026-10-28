"""잘못 쓴 명령어와 주인 없는 버튼에 답하기

- %명령어를 잘못 쓰면 (빠진 칸, 숫자 자리에 글자, 없는 유저 등) 사용법을 알려준다.
  예전에는 아무 답이 없어서 왜 안 되는지 알 수 없었다.
  사용법은 명령어 인자 이름으로 만든다: %롱 <종목> <증거금> [배율]  (usage= 를 적은 명령어는 그것을 쓴다)
- 시간이 지났거나, 이미 처리했거나, 봇이 다시 켜져서 주인 없는 버튼을 누르면
  디스코드가 "상호작용 실패"를 띄운다. 대신 "이제 쓸 수 없는 버튼"이라고 알려주고 버튼을 치운다.
"""
import contextlib
import inspect

import discord
from discord.ext import commands

from bot import client
from fmt import Amount

# 명령어 인자 이름 → 사용법에 보일 이름
PARAM_NAMES = {
    "member": "@유저",
    "amount": "금액",
    "stock_name": "종목",
    "item_name": "아이템",
    "minutes": "분",
    "margin": "증거금",
    "leverage": "배율",
    "target": "번호 | 전체",
    "riot_id": "닉네임#태그",
    "game_word": "롤 | 발로",
    "command": "명령어",
    "number": "번호",
    "name": "이름",
    "tokens": "토큰",
    "count": "개수",
    "reason": "사유",
    "value": "값",
    "when": "날짜",
    "grade": "학년",
    "class_nm": "반",
    "month": "월",
    "content": "내용",
    "new_price": "가격",
    "word": "줄임말",
    "reading": "읽는 법",
    "mode": "모드",
    "level": "레벨",
    "channel_id": "#채널",
}


def usage(ctx) -> str:
    """%명령어 사용법 한 줄. 예) %롱 <종목> <증거금 | 올인 | 절반> [배율]"""
    command = ctx.command
    name = f"%{ctx.invoked_with or command.name}"
    if command.usage:
        return f"{name} {command.usage}"
    parts = []
    for param in command.clean_params.values():
        label = PARAM_NAMES.get(param.name, param.name)
        if param.converter is Amount:
            label += " | 올인 | 절반"
        if param.kind is inspect.Parameter.VAR_POSITIONAL:
            parts.append(f"[{label} ...]")
        else:
            parts.append(f"<{label}>" if param.required else f"[{label}]")
    return " ".join([name, *parts])


def explain(ctx, error) -> str | None:
    """에러를 유저에게 보여줄 말로. None 이면 답하지 않는다."""
    if isinstance(error, (commands.MemberNotFound, commands.UserNotFound)):
        return f"❌ `{error.argument}` 유저를 찾을 수 없어요. @멘션으로 써 주세요.\n사용법: `{usage(ctx)}`"
    if isinstance(error, commands.MissingRequiredArgument):
        return f"❌ 명령어에 빠진 부분이 있어요.\n사용법: `{usage(ctx)}`"
    if isinstance(error, commands.UserInputError):
        wrong = f"`{ctx.current_argument}` 부분을 알아들을 수 없어요." if ctx.current_argument else "명령어를 알아들을 수 없어요."
        return f"❌ {wrong}\n사용법: `{usage(ctx)}`"
    if isinstance(error, (commands.MissingPermissions, commands.NotOwner)):
        return "❌ 이 명령어는 관리자만 쓸 수 있어요."
    if isinstance(error, commands.NoPrivateMessage):
        return "❌ 서버에서만 쓸 수 있는 명령어예요."
    if isinstance(error, commands.CommandInvokeError):
        return "❌ 처리하다가 오류가 났어요. 다시 해보고, 계속되면 `%건의`로 알려주세요."
    return None


@client.listen("on_command_error")
async def command_failed(ctx, error):
    # 에러 기록 / 출력은 features/audit.py 가 한다
    if ctx.command is None or ctx.command.has_error_handler():
        return
    text = explain(ctx, error)
    if text:
        with contextlib.suppress(discord.HTTPException):
            await ctx.send(text)


# ───────────── 주인 없는 버튼 ─────────────

def live_views():
    """discord.py 가 들고 있는 버튼 창 목록. {메시지 ID (또는 None): {(종류, custom_id): 버튼}}
    discord.py 내부 값이라 버전이 바뀌면 이름이 바뀔 수 있다. (2.7.1 기준, 없으면 검사를 건너뛴다)"""
    return getattr(getattr(client._connection, "_view_store", None), "_views", None)


@client.listen("on_interaction")
async def stale_button(interaction: discord.Interaction):
    if interaction.type is not discord.InteractionType.component or interaction.message is None:
        return
    views = live_views()
    if views is None:
        return
    # discord.py 가 버튼을 찾는 방법(ViewStore.dispatch_view)과 똑같이 찾는다. 찾았으면 그 창이 답한다
    key = (interaction.data["component_type"], interaction.data["custom_id"])
    message_id = interaction.message.id
    if key in views.get(message_id, {}) or key in views.get(None, {}):
        return

    text = "⌛ 이제 쓸 수 없는 버튼이에요. (시간이 지났거나, 이미 처리했거나, 봇이 다시 켜졌어요) 명령어를 다시 입력해 주세요."
    with contextlib.suppress(discord.HTTPException):
        if message_id in views:
            # 메시지에 살아 있는 다른 버튼이 있으면 (창이 바뀐 직전에 옛 버튼을 누른 것) 버튼은 그대로 둔다
            await interaction.response.send_message(text, ephemeral=True)
        else:
            await interaction.response.edit_message(view=None)   # 죽은 버튼 치우기
            await interaction.followup.send(text, ephemeral=True)
