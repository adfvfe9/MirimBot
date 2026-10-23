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
"""
import asyncio
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
