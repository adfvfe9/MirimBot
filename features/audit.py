"""명령어 / 버튼 기록: 누가 언제 무엇을 했는지 남긴다

    %관리 로그 [@유저] [찾을 말 | 관리자] [개수]     (관리자만) 최근 기록 보기

- 모든 명령어: 친 메시지 그대로, 성공했는지 (에러면 에러 종류), 걸린 시간
- 모든 /명령어: 입력한 값 그대로
- 모든 버튼 / 메뉴 / 입력창: 누른 버튼 이름 (또는 고른 값, 입력한 값) + 버튼이 달린 메시지 제목
- 돈이 바뀐 기록은 따로 money_log 에 있다. 여기는 "누가 무엇을 눌렀나" 를 보는 곳.
- 기록은 명령어를 느리게 하지 않게 따로(백그라운드로) 저장하고, 90일이 지나면 지운다.
- `%관리 로그 관리자` 는 관리자 권한이 필요한 명령어(%관리 강화수정, %관리 머니추가 …)만 보여준다.
"""
import asyncio
import datetime
import time
import traceback
from typing import Optional

import discord
from discord.ext import commands

import database as db
from bot import client
from features import errors

KEEP_DAYS = 90
CONTENT_MAX = 500
VIEW_DEFAULT = 20
VIEW_MAX = 50


def save(**kwargs):
    """기록을 백그라운드로 저장한다. 실패해도 명령어에는 영향이 없다."""
    async def run():
        try:
            await db.add_command_log(**kwargs)
        except Exception as e:
            print(f"[기록] 저장 실패: {type(e).__name__} {e}")
    asyncio.create_task(run())


def clip(text):
    if text and len(text) > CONTENT_MAX:
        return text[:CONTENT_MAX] + "…"
    return text


# ───────────── 명령어 ─────────────

started = {}     # message.id → 시작 시각


@client.listen("on_command")
async def command_started(ctx):
    started[ctx.message.id] = time.perf_counter()


def save_command(ctx, result):
    begin = started.pop(ctx.message.id, None)
    save(
        user_id=ctx.author.id,
        guild_id=ctx.guild and ctx.guild.id,
        channel_id=ctx.channel and ctx.channel.id,
        kind="command",
        name=errors.command_name(ctx),        # 하위 명령어는 "주식 구매" 처럼
        content=clip(ctx.message.content),
        result=result,
        ms=None if begin is None else int((time.perf_counter() - begin) * 1000),
    )


@client.listen("on_command_completion")
async def command_done(ctx):
    save_command(ctx, "ok")


@client.listen("on_command_error")
async def command_failed(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return      # 없는 명령어 (%ㅋㅋ 같은 것)는 기록하지 않는다
    save_command(ctx, type(getattr(error, "original", error)).__name__)
    # on_command_error 를 듣는 순간 discord.py 가 에러를 출력해주지 않아서 직접 출력한다
    if ctx.command and ctx.command.has_error_handler():
        return
    print(f"[명령어 에러] %{errors.command_name(ctx)} ({ctx.author}): {type(error).__name__}")
    traceback.print_exception(type(error), error, error.__traceback__)


# ───────────── 버튼 / 메뉴 / 입력창 ─────────────

def find_component(message, custom_id):
    if message is None:
        return None
    for row in message.components:
        for child in getattr(row, "children", [row]):
            if getattr(child, "custom_id", None) == custom_id:
                return child
    return None


def message_title(message):
    if message is None:
        return None
    if message.embeds and message.embeds[0].title:
        return message.embeds[0].title
    return (message.content or "")[:60] or None


def slash_text(data):
    """/명령어 입력을 '/관리 로그 유저:123 개수:5' 처럼 한 줄로 (하위 명령어는 이름을 이어 붙인다)"""
    parts = ["/" + data.get("name", "?")]
    options = data.get("options", [])
    while options and options[0].get("type") in (1, 2):        # 1 = 하위 명령어, 2 = 하위 명령어 묶음
        parts.append(options[0]["name"])
        options = options[0].get("options", [])
    return " ".join(parts), " ".join(f"{o['name']}:{o.get('value')}" for o in options)


def describe(interaction):
    """(kind, name, content) 또는 None"""
    data = interaction.data or {}
    if interaction.type == discord.InteractionType.application_command:
        name, args = slash_text(data)
        return "slash", name, f"{name} {args}".strip()
    title = message_title(interaction.message)
    if interaction.type == discord.InteractionType.component:
        component = find_component(interaction.message, data.get("custom_id"))
        if data.get("component_type") == discord.ComponentType.button.value:
            name = None
            if component is not None:
                name = component.label or (str(component.emoji) if component.emoji else None)
            return "button", name or "버튼", title
        values = data.get("values", [])
        labels = values
        if component is not None and getattr(component, "options", None):
            by_value = {o.value: o.label for o in component.options}
            labels = [by_value.get(v, v) for v in values]
        name = (component.placeholder if component is not None and component.placeholder else None) or "메뉴"
        return "select", name, f"{title} · 고름: {', '.join(labels)}" if title else f"고름: {', '.join(labels)}"
    if interaction.type == discord.InteractionType.modal_submit:
        inputs = [
            c.get("value", "")
            for row in data.get("components", [])
            for c in row.get("components", [])
        ]
        return "modal", "입력창", f"{title} · 입력: {' / '.join(inputs)}" if title else f"입력: {' / '.join(inputs)}"
    return None


@client.listen("on_interaction")
async def interaction_used(interaction):
    try:
        described = describe(interaction)
    except Exception as e:
        print(f"[기록] 버튼 정보 읽기 실패: {type(e).__name__} {e}")
        return
    if described is None:
        return
    kind, name, content = described
    save(
        user_id=interaction.user.id,
        guild_id=interaction.guild_id,
        channel_id=interaction.channel_id,
        kind=kind,
        name=name[:100],
        content=clip(content),
    )


# ───────────── 오래된 기록 지우기 ─────────────

async def prune_loop():
    """setup_hook 에서 한 번 시작한다. 하루에 한 번 KEEP_DAYS 가 지난 기록을 지운다."""
    while True:
        try:
            removed = await db.prune_command_log(db.now() - datetime.timedelta(days=KEEP_DAYS))
            if removed:
                print(f"[기록] {KEEP_DAYS}일 지난 기록 {removed}개 삭제")
        except Exception as e:
            print(f"[기록] 오래된 기록 지우기 실패: {type(e).__name__} {e}")
        await asyncio.sleep(24 * 60 * 60)


# ───────────── 보기 ─────────────

def admin_command_names():
    """관리자 권한 등 검사가 붙은 명령어의 이름과 별칭 전부 (v1.3.9 전 기록은 '머니추가', 그 뒤는 '관리 머니추가')"""
    names = []
    for command in client.walk_commands():
        if command.checks:
            names += [command.qualified_name, command.name, *command.aliases]
    group = client.tree.get_command("관리")          # 슬래시 관리자 명령어 (/관리 …)
    if group is not None:
        names += [f"/관리 {c.name}" for c in group.commands]
    return names


KIND_ICON = {"command": "⌨️", "slash": "⌨️", "button": "🔘", "select": "📋", "modal": "📝"}


def log_line(row):
    at = row["created_at"].astimezone(db.KST).strftime("%m-%d %H:%M:%S")
    icon = KIND_ICON.get(row["kind"], "•")
    if row["kind"] in ("command", "slash"):
        body = f"`{(row['content'] or '%' + row['name'])[:120]}`"
        result = "" if row["result"] in ("ok", None) else f" ❌ {row['result']}"
        timing = f" · {row['ms']}ms" if row["ms"] is not None else ""
        tail = result + timing
    else:
        body = f"**{row['name']}**" + (f" — {row['content'][:100]}" if row["content"] else "")
        tail = ""
    return f"`{at}` <@{row['user_id']}> {icon} {body}{tail}"


@commands.command(name="로그", usage="[@유저] [찾을 말 | 관리자] [개수]")
@commands.has_permissions(administrator=True)
async def audit_log(ctx, member: Optional[discord.Member] = None, *args: str):
    count = VIEW_DEFAULT
    words = []
    for a in args:
        if a.isdigit():
            count = max(1, min(VIEW_MAX, int(a)))
        else:
            words.append(a)
    text = " ".join(words) or None
    names = None
    if text == "관리자":
        text, names = None, admin_command_names()

    rows = await db.command_logs(
        guild_id=ctx.guild and ctx.guild.id,
        user_id=member and member.id,
        text=text,
        names=names,
        limit=count,
    )
    who = f"{member.display_name}님의 " if member else ""
    what = " · 관리자 명령어" if names else (f" · '{text}'" if text else "")
    embed = discord.Embed(title=f"📜 {who}최근 기록 {len(rows)}개{what}", color=discord.Color.dark_grey())
    lines = [log_line(r) for r in reversed(rows)]     # 오래된 것 → 최근 순으로 읽기 쉽게
    description = ""
    for line in reversed(lines):                     # 넘치면 오래된 것부터 버린다
        if len(description) + len(line) + 1 > 4000:
            break
        description = line + "\n" + description
    embed.description = description or "기록이 없어요."
    embed.set_footer(text=f"%관리 로그 [@유저] [찾을 말 | 관리자] [개수(최대 {VIEW_MAX})] · ⌨️ 명령어 🔘 버튼 📋 메뉴 📝 입력창 · {KEEP_DAYS}일 보관")
    await ctx.send(embed=embed)
