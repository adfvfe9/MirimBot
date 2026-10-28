"""학사정보: 급식 / 시간표 / 학사일정 (나이스 교육정보 API) + 매일 아침 자동 알림

    %학교 급식 [내일 | 날짜]            이 서버 학교의 급식 (날짜: 1024, 10/24, 2026-10-24)
    %학교 시간표 [학년 반] [내일 | 날짜]  학년 반을 안 쓰면 %학교 내반 으로 정한 반
    %학교 내반 <학년> <반>               내 반 저장 (%학교 시간표 에 쓰인다)
    %학교 학사일정 [월]                  이번 달 (또는 그 달) 학사일정
    %관리 학사설정                       (관리자) 학교 · 알림 채널 · 시간 · 보낼 것 · 기본 반 설정 패널

- 서버마다 학교를 정할 수 있다. 안 정하면 미림마이스터고. (나이스에서 이름으로 검색)
- 알림 채널을 정하면 평일 정해진 시간(기본 08:00)에 급식 / 오늘 일정 / 기본 반 시간표를 보낸다.
  봇이 그 시간에 꺼져 있었으면 켜진 뒤 POST_GRACE 안에서만 늦게라도 보낸다.
  급식도 시간표도 일정도 없는 날(공휴일 등)은 보내지 않는다.
- 나이스 API 는 기다리는 동안 봇이 멈추지 않게 다른 스레드에서 부르고, 같은 내용은 CACHE_SECONDS 동안 다시 묻지 않는다.
"""
import asyncio
import datetime
import os
import re
import time

import discord
import requests
from discord.ext import commands
from discord.ui import Button, ChannelSelect, Modal, Select, TextInput, View

import database as db
import respond
from bot import client

NEIS_URL = "https://open.neis.go.kr/hub/"
TIMEOUT = 5
CACHE_SECONDS = 30 * 60
POST_GRACE = datetime.timedelta(hours=2)
SKIP_EVENTS = {"토요휴업일"}          # 학사일정에서 빼는 것 (매주 있어서 의미가 없다)
WEEKDAYS = "월화수목금토일"

DEFAULT_SCHOOL = {
    "edu_code": "B10", "school_code": "7011569",
    "school_name": "미림마이스터고등학교", "school_kind": "고등학교",
}
TIMETABLE_SERVICE = {
    "초등학교": "elsTimetable", "중학교": "misTimetable", "고등학교": "hisTimetable", "특수학교": "spsTimetable",
}


class NeisError(Exception):
    pass


# ───────────── 나이스 API ─────────────

_cache = {}     # (서비스, 파라미터) → (시각, rows)


def _fetch(service, params):
    key = os.getenv("NEIS_API_KEY")
    if not key:
        raise NeisError("나이스 API 키가 없어요 (.env 의 NEIS_API_KEY)")
    response = requests.get(
        NEIS_URL + service,
        params={"KEY": key, "Type": "json", "pIndex": 1, "pSize": 100, **params},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    if service not in data:
        return []        # INFO-200: 해당하는 데이터가 없음 (주말 · 공휴일 등)
    return data[service][1]["row"]


async def neis(service, **params):
    """rows (없으면 []). 네트워크 문제면 NeisError"""
    cache_key = (service, tuple(sorted(params.items())))
    hit = _cache.get(cache_key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    try:
        rows = await asyncio.to_thread(_fetch, service, params)
    except requests.RequestException as e:
        raise NeisError(f"나이스 서버에 연결하지 못했어요 ({type(e).__name__})") from e
    _cache[cache_key] = (time.monotonic(), rows)
    return rows


def ymd(day):
    return day.strftime("%Y%m%d")


async def search_schools(name):
    rows = await neis("schoolInfo", SCHUL_NM=name)
    return [
        {"edu_code": r["ATPT_OFCDC_SC_CODE"], "school_code": r["SD_SCHUL_CODE"],
         "school_name": r["SCHUL_NM"], "school_kind": r["SCHUL_KND_SC_NM"], "region": r.get("LCTN_SC_NM", "")}
        for r in rows
    ]


def school_params(school):
    return {"ATPT_OFCDC_SC_CODE": school["edu_code"], "SD_SCHUL_CODE": school["school_code"]}


async def meals(school, day):
    """[(식사 이름, 메뉴 글)]"""
    rows = await neis("mealServiceDietInfo", **school_params(school), MLSV_YMD=ymd(day))
    result = []
    for r in rows:
        dishes = r["DDISH_NM"].replace("<br/>", "\n")
        dishes = re.sub(r"\([^)]*\)", "", dishes)      # 알레르기 번호 (1.2.5.) 같은 괄호 지우기
        # 괄호 없이 뒤에 붙은 알레르기 번호 (돈육갈비구이1.5.) 도 지운다
        lines = [re.sub(r"[\d.]+$", "", line.strip()).strip() for line in dishes.splitlines()]
        result.append((r["MMEAL_SC_NM"], "\n".join(line for line in lines if line)))
    return result


async def timetable(school, day, grade, class_nm):
    """[(교시, 과목)]"""
    service = TIMETABLE_SERVICE.get(school["school_kind"])
    if service is None:
        return []
    rows = await neis(service, **school_params(school), ALL_TI_YMD=ymd(day), GRADE=str(grade), CLASS_NM=str(class_nm))
    seen, result = set(), []
    for r in sorted(rows, key=lambda r: int(r["PERIO"])):
        if r["PERIO"] in seen:          # 같은 교시가 두 번 오는 학교가 있다 (선택 과목)
            continue
        seen.add(r["PERIO"])
        result.append((r["PERIO"], r["ITRT_CNTNT"].lstrip("* ").strip()))
    return result


async def schedule(school, start, end):
    """[(날짜, 일정 이름)] 토요휴업일은 뺀다"""
    rows = await neis("SchoolSchedule", **school_params(school), AA_FROM_YMD=ymd(start), AA_TO_YMD=ymd(end))
    result = []
    for r in rows:
        if r["EVENT_NM"] in SKIP_EVENTS:
            continue
        result.append((datetime.datetime.strptime(r["AA_YMD"], "%Y%m%d").date(), r["EVENT_NM"]))
    return sorted(set(result))


# ───────────── 설정 ─────────────

async def settings_of(guild_id):
    row = await db.get_school_settings(guild_id) if guild_id else None
    return row or {**DEFAULT_SCHOOL, "guild_id": guild_id, "channel_id": None, "post_time": "08:00",
                   "post_meal": True, "post_schedule": True, "post_timetable": False,
                   "grade": None, "class_nm": None, "last_posted": None}


def parse_day(text, today=None):
    """'내일' / '모레' / '어제' / 1024 / 10/24 / 10-24 / 2026-10-24 → date. 못 읽으면 None"""
    today = today or db.today()
    text = (text or "").strip()
    if not text or text == "오늘":
        return today
    shift = {"어제": -1, "내일": 1, "모레": 2}.get(text)
    if shift is not None:
        return today + datetime.timedelta(days=shift)
    m = re.fullmatch(r"(?:(\d{4})[-./])?(\d{1,2})[-./]?(\d{2})", text)
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1) or today.year), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_time(text):
    """'8:00' / '08:30' / '8시' / '8시 30분' → 'HH:MM'. 못 읽으면 None"""
    m = re.fullmatch(r"\s*(\d{1,2})\s*(?::|시)\s*(\d{1,2})?\s*분?\s*", text or "")
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if not (0 <= h < 24 and 0 <= mi < 60):
        return None
    return f"{h:02}:{mi:02}"


def day_text(day):
    return f"{day.month}월 {day.day}일 ({WEEKDAYS[day.weekday()]})"


# ───────────── 화면 ─────────────

MEAL_ICON = {"조식": "🌅", "중식": "🍱", "석식": "🌙"}


def meal_text(meal_rows):
    return "\n\n".join(f"{MEAL_ICON.get(name, '🍴')} **[{name}]**\n{dishes}" for name, dishes in meal_rows)


def timetable_text(rows):
    return "\n".join(f"`{p}교시` {subject}" for p, subject in rows)


def schedule_text(rows, today=None):
    today = today or db.today()
    lines = []
    for day, name in rows:
        mark = " ⬅️ 오늘" if day == today else ""
        lines.append(f"`{day.month:>2}/{day.day:02} {WEEKDAYS[day.weekday()]}` {name}{mark}")
    return "\n".join(lines)


async def daily_embed(settings, day):
    """자동 알림 embed. 보낼 게 하나도 없으면 None (공휴일 등)"""
    embed = discord.Embed(title=f"📚 {day_text(day)} 학사정보", color=0x2ecc71)
    embed.set_footer(text=f"{settings['school_name']} · %학교 급식 %학교 시간표 %학교 학사일정")
    has = False
    if settings["post_meal"]:
        rows = await meals(settings, day)
        if rows:
            embed.description = meal_text(rows)[:4000]
            has = True
    if settings["post_timetable"] and settings["grade"] and settings["class_nm"]:
        rows = await timetable(settings, day, settings["grade"], settings["class_nm"])
        if rows:
            embed.add_field(name=f"📖 {settings['grade']}학년 {settings['class_nm']}반 시간표", value=timetable_text(rows)[:1024], inline=False)
            has = True
    if settings["post_schedule"]:
        rows = await schedule(settings, day, day + datetime.timedelta(days=7))
        if any(d == day for d, _ in rows):
            has = True
        if rows:
            embed.add_field(name="📅 오늘부터 일주일 일정", value=schedule_text(rows, day)[:1024], inline=False)
    return embed if has else None


# ───────────── 명령어 ─────────────

async def send_error(ctx, e):
    await ctx.send(f"🥲 {e}")


@commands.command(name="급식", usage="[내일 | 1024 | 10/24]")
async def school_meal(ctx, *, when: str = None):
    day = parse_day(when)
    if day is None:
        await ctx.send("사용법: `%학교 급식 [내일 | 1024 | 10/24]`")
        return
    settings = await settings_of(ctx.guild and ctx.guild.id)
    try:
        rows = await meals(settings, day)
    except NeisError as e:
        return await send_error(ctx, e)
    if not rows:
        await ctx.send(f"🥲 {day_text(day)}에는 급식 정보가 없어요. (주말 / 공휴일 / 방학일 수 있어요)")
        return
    embed = discord.Embed(title=f"🍴 {day_text(day)} 급식", description=meal_text(rows)[:4000], color=0x2ecc71)
    embed.set_footer(text=settings["school_name"])
    await ctx.send(embed=embed)


@commands.command(name="내반", usage="<학년> <반>")
async def my_class(ctx, grade: int = None, class_nm: str = None):
    if ctx.guild is None:
        return
    if grade is None or class_nm is None:
        saved = await db.get_user_class(ctx.guild.id, ctx.author.id)
        now = f"지금: **{saved['grade']}학년 {saved['class_nm']}반**" if saved else "아직 안 정했어요."
        await ctx.send(f"사용법: `%학교 내반 <학년> <반>` 예) `%학교 내반 2 1` · {now}")
        return
    await db.set_user_class(ctx.guild.id, ctx.author.id, grade, class_nm)
    await ctx.send(f"🎓 내 반을 **{grade}학년 {class_nm}반**으로 정했어요. 이제 `%학교 시간표`만 쳐도 돼요.")


@commands.command(name="시간표", usage="[학년 반] [내일 | 날짜]")
async def school_timetable(ctx, *args: str):
    if ctx.guild is None:
        return
    nums = [a for a in args if a.isdigit() and len(a) <= 2]
    rest = [a for a in args if a not in nums[:2]]
    if len(nums) >= 2:
        grade, class_nm = int(nums[0]), nums[1]
    else:
        saved = await db.get_user_class(ctx.guild.id, ctx.author.id)
        if saved is None:
            await ctx.send("사용법: `%학교 시간표 <학년> <반> [내일 | 날짜]` · `%학교 내반 2 1`로 내 반을 저장하면 `%학교 시간표`만 쳐도 돼요.")
            return
        grade, class_nm = saved["grade"], saved["class_nm"]
    day = parse_day(" ".join(rest))
    if day is None:
        await ctx.send("날짜는 `내일`, `1024`, `10/24`처럼 써주세요.")
        return
    settings = await settings_of(ctx.guild.id)
    try:
        rows = await timetable(settings, day, grade, class_nm)
    except NeisError as e:
        return await send_error(ctx, e)
    if not rows:
        await ctx.send(f"🥲 {day_text(day)} {grade}학년 {class_nm}반 시간표가 없어요. (주말 / 공휴일이거나 반 번호가 다를 수 있어요)")
        return
    embed = discord.Embed(title=f"📖 {day_text(day)} {grade}학년 {class_nm}반 시간표", description=timetable_text(rows), color=0x3498db)
    embed.set_footer(text=settings["school_name"])
    await ctx.send(embed=embed)


@commands.command(name="학사일정")
async def school_schedule(ctx, month: int = None):
    today = db.today()
    month = month or today.month
    if not 1 <= month <= 12:
        await ctx.send("사용법: `%학교 학사일정 [월]` 예) `%학교 학사일정 12`")
        return
    year = today.year if month >= today.month - 6 else today.year + 1     # 지난 달을 물으면 올해, 한참 전이면 내년 (학년도 넘어가는 1~2월)
    start = datetime.date(year, month, 1)
    end = (start + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1)
    settings = await settings_of(ctx.guild and ctx.guild.id)
    try:
        rows = await schedule(settings, start, end)
    except NeisError as e:
        return await send_error(ctx, e)
    embed = discord.Embed(
        title=f"📅 {year}년 {month}월 학사일정",
        description=schedule_text(rows, today)[:4000] if rows else "등록된 일정이 없어요.",
        color=0x9b59b6,
    )
    embed.set_footer(text=f"{settings['school_name']} · 토요휴업일은 뺐어요")
    await ctx.send(embed=embed)


# ───────────── 관리자 설정 패널 ─────────────

def settings_embed(s):
    channel = f"<#{s['channel_id']}>" if s["channel_id"] else "❌ 꺼짐 (채널을 고르면 켜져요)"
    on = lambda flag: "✅" if flag else "⬜"
    cls = f"{s['grade']}학년 {s['class_nm']}반" if s["grade"] else "안 정함"
    embed = discord.Embed(title="🏫 학사정보 설정", color=0x2ecc71)
    embed.add_field(name="학교", value=f"{s['school_name']} ({s['school_kind']})", inline=False)
    embed.add_field(name="알림 채널", value=channel, inline=True)
    embed.add_field(name="보내는 시간", value=f"평일 {s['post_time']}", inline=True)
    embed.add_field(
        name="보낼 것",
        value=f"{on(s['post_meal'])} 급식 · {on(s['post_schedule'])} 학사일정 · {on(s['post_timetable'])} 시간표 ({cls})",
        inline=False,
    )
    embed.set_footer(text="급식도 시간표도 일정도 없는 날(공휴일 등)은 보내지 않아요")
    return embed


class SchoolSettingsView(View):
    def __init__(self, guild_id, user_id):
        super().__init__(timeout=600)
        self.guild_id = guild_id
        self.user_id = user_id
        self.message = None

        channel = ChannelSelect(placeholder="📢 알림 채널 고르기", channel_types=[discord.ChannelType.text], row=0)
        channel.callback = self.on_channel
        self.add_item(channel)
        for label, emoji, callback, row in (
            ("학교 바꾸기", "🏫", self.on_school, 1), ("시간", "⏰", self.on_time, 1), ("기본 반", "🎓", self.on_class, 1),
            ("급식", "🍱", self.toggle("post_meal"), 2), ("학사일정", "📅", self.toggle("post_schedule"), 2),
            ("시간표", "📖", self.toggle("post_timetable"), 2),
            ("지금 보내보기", "📨", self.on_test, 3), ("알림 끄기", "🔕", self.on_off, 3),
        ):
            button = Button(label=label, emoji=emoji, style=discord.ButtonStyle.secondary, row=row)
            button.callback = callback
            self.add_item(button)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await respond.reply(interaction, "❌ `%관리 학사설정`을 연 관리자만 쓸 수 있어요.", ephemeral=True)
            return False
        return True

    async def save_and_show(self, interaction, **changes):
        await db.update_school_settings(self.guild_id, await settings_of(self.guild_id), **changes)
        await respond.edit(interaction, embed=settings_embed(await settings_of(self.guild_id)), view=self)

    async def on_channel(self, interaction):
        await respond.defer(interaction)
        await self.save_and_show(interaction, channel_id=int(interaction.data["values"][0]))

    def toggle(self, key):
        async def run(interaction):
            await respond.defer(interaction)
            s = await settings_of(self.guild_id)
            if key == "post_timetable" and not s[key] and not s["grade"]:
                await respond.reply(interaction, "🎓 먼저 **기본 반**을 정해주세요. 그 반 시간표를 보내요.", ephemeral=True)
                return
            await self.save_and_show(interaction, **{key: not s[key]})
        return run

    async def on_off(self, interaction):
        await respond.defer(interaction)
        await self.save_and_show(interaction, channel_id=None)

    async def on_school(self, interaction):
        await interaction.response.send_modal(SchoolSearchModal(self))

    async def on_time(self, interaction):
        await interaction.response.send_modal(TimeModal(self))

    async def on_class(self, interaction):
        await interaction.response.send_modal(ClassModal(self))

    async def on_test(self, interaction):
        await respond.defer(interaction)
        s = await settings_of(self.guild_id)
        try:
            embed = await daily_embed(s, db.today())
        except NeisError as e:
            await respond.reply(interaction, f"🥲 {e}", ephemeral=True)
            return
        if embed is None:
            await respond.reply(interaction, "📭 오늘은 보낼 게 없어요. (급식 · 시간표 · 오늘 일정이 없는 날)", ephemeral=True)
            return
        await respond.reply(interaction, "📨 이렇게 보내져요. (나만 보임)", embed=embed, ephemeral=True)

    async def refresh(self):
        if self.message:
            try:
                await self.message.edit(embed=settings_embed(await settings_of(self.guild_id)), view=self)
            except discord.HTTPException:
                pass


class SchoolSearchModal(Modal, title="🏫 학교 검색"):
    name = TextInput(label="학교 이름 (일부만 써도 돼요)", placeholder="예: 미림, 선린인터넷")

    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    async def on_submit(self, interaction):
        await respond.defer(interaction)
        try:
            found = await search_schools(self.name.value.strip())
        except NeisError as e:
            await respond.reply(interaction, f"🥲 {e}", ephemeral=True)
            return
        if not found:
            await respond.reply(interaction, f"❌ '{self.name.value}' 학교를 찾지 못했어요.", ephemeral=True)
            return
        view = View(timeout=120)
        menu = Select(
            placeholder="학교를 골라주세요",
            options=[discord.SelectOption(label=f["school_name"][:100], description=f"{f['region']} · {f['school_kind']}"[:100], value=str(i))
                     for i, f in enumerate(found[:25])],
        )

        async def pick(inner):
            await respond.defer(inner)
            school = found[int(inner.data["values"][0])]
            # 학교가 바뀌면 기본 반은 의미가 없어진다
            await db.update_school_settings(self.panel.guild_id, await settings_of(self.panel.guild_id),
                                            **{k: school[k] for k in DEFAULT_SCHOOL}, grade=None, class_nm=None, post_timetable=False)
            await respond.edit(inner, content=f"🏫 **{school['school_name']}**(으)로 바꿨어요.", view=None)
            await self.panel.refresh()

        menu.callback = pick
        view.add_item(menu)
        more = " (앞의 25개만 보여요, 더 자세히 써주세요)" if len(found) > 25 else ""
        await respond.reply(interaction, f"🔍 {len(found)}개 찾았어요{more}", view=view, ephemeral=True)


class TimeModal(Modal, title="⏰ 보내는 시간"):
    when = TextInput(label="평일 몇 시에 보낼까요?", placeholder="예: 8:00, 7시 30분")

    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    async def on_submit(self, interaction):
        await respond.defer(interaction)
        t = parse_time(self.when.value)
        if t is None:
            await respond.reply(interaction, "❌ `8:00`, `7시 30분`처럼 써주세요.", ephemeral=True)
            return
        await db.update_school_settings(self.panel.guild_id, await settings_of(self.panel.guild_id), post_time=t)
        await respond.reply(interaction, f"⏰ 이제 평일 **{t}**에 보내요.", ephemeral=True)
        await self.panel.refresh()


class ClassModal(Modal, title="🎓 기본 반 (알림에 넣을 시간표)"):
    grade = TextInput(label="학년", placeholder="예: 2", max_length=1)
    class_nm = TextInput(label="반", placeholder="예: 1", max_length=3)

    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    async def on_submit(self, interaction):
        await respond.defer(interaction)
        if not self.grade.value.strip().isdigit():
            await respond.reply(interaction, "❌ 학년은 숫자로 써주세요.", ephemeral=True)
            return
        await db.update_school_settings(self.panel.guild_id, await settings_of(self.panel.guild_id),
                                        grade=int(self.grade.value), class_nm=self.class_nm.value.strip(), post_timetable=True)
        await respond.reply(interaction, f"🎓 알림에 **{self.grade.value}학년 {self.class_nm.value}반** 시간표를 넣어요.", ephemeral=True)
        await self.panel.refresh()


@commands.command(name="학사설정")
@commands.has_permissions(administrator=True)
async def school_settings(ctx):
    if ctx.guild is None:
        return
    view = SchoolSettingsView(ctx.guild.id, ctx.author.id)
    view.message = await ctx.send(embed=settings_embed(await settings_of(ctx.guild.id)), view=view)


# ───────────── 자동 알림 ─────────────

async def post_due(now=None):
    """보낼 때가 된 서버에 보낸다. 보낸 서버 수"""
    now = now or db.now()
    if now.weekday() >= 5:
        return 0
    sent = 0
    for s in await db.school_channels():
        h, m = map(int, s["post_time"].split(":"))
        due = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if not (due <= now < due + POST_GRACE) or s["last_posted"] == now.date():
            continue
        await db.update_school_settings(s["guild_id"], s, last_posted=now.date())   # 실패해도 오늘은 다시 안 보낸다 (도배 방지)
        channel = client.get_channel(s["channel_id"])
        if channel is None:
            continue
        try:
            embed = await daily_embed(s, now.date())
            if embed is not None:
                await channel.send(embed=embed)
                sent += 1
        except (NeisError, discord.HTTPException) as e:
            print(f"[학사정보] {s['guild_id']} 알림 실패: {type(e).__name__} {e}")
    return sent


async def post_loop():
    """setup_hook 에서 한 번 시작한다. 30초마다 보낼 때가 됐는지 본다."""
    await client.wait_until_ready()
    while True:
        try:
            await post_due()
        except Exception as e:
            print(f"[학사정보] 알림 확인 실패: {type(e).__name__} {e}")
        await asyncio.sleep(30)
