"""버튼 / 입력창(모달) 응답 도우미.

디스코드는 버튼을 누르면 3초 안에 응답해야 하고, 늦으면 실제로는 처리됐어도
화면에 "상호작용 실패"가 뜬다.

그래서 버튼 콜백은 맨 처음에 defer() 를 부르고, 일을 다 한 뒤에 edit() / reply() 로 결과를 보여준다.

    async def confirm_callback(interaction):
        await respond.defer(interaction)
        ... DB 작업 ...
        await respond.edit(interaction, embed=result, view=None)

defer() 는 바로 "받았어"라고 답하지 않고 DEFER_AFTER 초를 기다린다.
- 그 안에 일이 끝나면 (대부분) edit / reply 가 첫 응답이 되어서 디스코드 요청이 1번으로 끝난다.
  ("받았어" + "메시지 수정" 2번이면 그만큼 화면이 늦게 바뀌고, 그 사이 옛 버튼을 또 누르게 된다)
- 일이 오래 걸리면 DEFER_AFTER 초에 "받았어"라고 먼저 답해서 3초 제한을 넘기지 않는다.
edit / reply 는 먼저 답했는지에 따라 알맞은 방법을 고른다.

delete_soon(ctx.message): %명령어를 친 메시지를 지운다. 디스코드 응답을 기다리지 않고 뒤에서 지운다.

ConfirmView(ctx.author): 확인 / 취소처럼 한 번만 누르는 버튼 창. View() 대신 쓴다.
- 명령어를 친 사람만 누를 수 있다. (콜백에서 따로 검사하지 않아도 된다)
- 처음 누른 순간 창이 닫혀서, 확인을 빨리 두 번 눌러도 한 번만 처리된다.

시간이 지났거나 봇이 다시 켜져서 주인 없는 버튼을 누르면 features/errors.py 가 안내한다.
"""
import asyncio
import contextlib
from collections import deque

import discord

DEFER_AFTER = 1.2      # 초. 디스코드 제한(3초)까지 여유를 둔다

_pending = {}          # interaction.id → asyncio.Lock (아직 "받았어"를 안 보낸 상호작용)
_replied_first = deque(maxlen=500)   # 첫 응답이 새 메시지(reply)였던 상호작용. 이 뒤의 edit 은 버튼 메시지를 고쳐야 한다


async def defer(interaction: discord.Interaction) -> None:
    """DEFER_AFTER 초 안에 edit / reply 가 없으면 그때 "받았어"라고 답한다. (메시지는 그대로)"""
    if interaction.response.is_done() or interaction.id in _pending:
        return
    lock = _pending[interaction.id] = asyncio.Lock()

    async def later():
        await asyncio.sleep(DEFER_AFTER)
        async with lock:
            if not interaction.response.is_done():
                try:
                    await interaction.response.defer()
                except discord.HTTPException:
                    pass
            _pending.pop(interaction.id, None)   # 다 보낸 뒤에 빼야 그사이 온 edit 이 잠금을 기다린다

    asyncio.create_task(later())


async def _first_or_later(interaction, first, later):
    """아직 응답 전이면 first(), 이미 답했으면 later(). defer 의 타이머와 겹치지 않게 잠근다."""
    lock = _pending.get(interaction.id)
    if lock is None:
        return await (later() if interaction.response.is_done() else first())
    async with lock:
        _pending.pop(interaction.id, None)
        return await (later() if interaction.response.is_done() else first())


async def edit(interaction: discord.Interaction, **kwargs) -> None:
    """버튼이 달린 원래 메시지를 수정한다."""
    async def later():
        if interaction.id in _replied_first and interaction.message:
            return await interaction.message.edit(**kwargs)
        return await interaction.edit_original_response(**kwargs)

    await _first_or_later(interaction, lambda: interaction.response.edit_message(**kwargs), later)


async def reply(interaction: discord.Interaction, content=None, *, ephemeral: bool = False, **kwargs) -> None:
    """새 메시지로 답한다. ephemeral=True 면 누른 사람에게만 보인다."""
    async def first():
        _replied_first.append(interaction.id)
        return await interaction.response.send_message(content, ephemeral=ephemeral, **kwargs)

    await _first_or_later(interaction, first, lambda: interaction.followup.send(content, ephemeral=ephemeral, **kwargs))


_background = set()    # 뒤에서 도는 작업 (끝나기 전에 가비지 컬렉션되지 않게 잡아 둔다)


def delete_soon(message) -> None:
    """명령어 메시지를 뒤에서 지운다. 기다리면 명령어마다 디스코드 왕복(0.3~0.5초)만큼 답이 늦어진다.
    이미 지워졌거나 권한이 없어도 명령어는 그대로 진행한다."""
    async def run():
        with contextlib.suppress(discord.HTTPException):
            await message.delete()
    task = asyncio.create_task(run())
    _background.add(task)
    task.add_done_callback(_background.discard)


class ConfirmView(discord.ui.View):
    """확인 / 취소처럼 한 번만 누르는 버튼 창. owner = 누를 수 있는 사람 (Member 또는 ID)"""

    def __init__(self, owner, *, timeout: float = 180):
        super().__init__(timeout=timeout)
        self.owner_id = getattr(owner, "id", owner)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await reply(interaction, "이 버튼은 당신의 것이 아니에요!", ephemeral=True)
            return False
        # 두 번 누르면 두 콜백이 같이 돈다. 검사와 stop() 사이에 await 가 없어서 먼저 온 쪽만 통과한다
        if self.is_finished():
            await reply(interaction, "이미 처리한 버튼이에요.", ephemeral=True)
            return False
        self.stop()
        return True
