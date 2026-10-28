"""아이템 강화 (피파 인생강화 스타일)

    %강화 <이름> [목표] [제물 ...]   아이템 제작(1만) / 강화 패널 열기. 목표를 쓰면 [목표까지 자동] 버튼이 생긴다.
                                    제물을 쓰면 다음 한 번의 강화 성공률이 오르고 제물은 사라진다. (sacrifice_mult)
    %강화판매 <이름>      판매가에 팔기
    %강화목록 [@유저]     보유 아이템
    %강화랭킹             서버 전체 최고 강화 아이템
    %강화확률             확률표
    %강화제작 <이름> <레벨> [@유저]   (관리자) 원하는 레벨의 아이템 바로 만들기
    %강화수정 <이름> <레벨> [@유저]   (관리자) 아이템 레벨 바꾸기

- 아이템은 +1 로 시작해서 최대 +13.
- +3 / +5 / +7 / +9 / +11 / +13 에 처음 도달하면 능력 슬롯이 열린다. (features/abilities.py)
- 낮은 레벨은 실패해도 유지, +6 부터는 떨어질 수 있고, +7 부터는 파괴될 수 있다. (최대 10%)
- 한 번 더 누를 때마다 평균적으로 가진 가치의 3~10% 를 잃는다. 고강일수록 확률은 낮고 대박은 크다. (로또 구조)
"""
import asyncio
import random
import time

import asyncpg
import discord
from discord.ext import commands
from discord.ui import Button, View

import database as db
import respond
from bot import client
from features import abilities
from fmt import debt_line, num

# ───────────── 밸런스 설정 ─────────────
CRAFT_COST = 10000        # 아이템 제작비 (+1 로 시작)
MAX_ITEMS = 5             # 1인 최대 보유 개수
MAX_LEVEL = 13
NAME_MAX_LEN = 20
ANNOUNCE_LEVEL = 10       # 이 레벨 이상 성공 / 이 레벨 이상 아이템 파괴 시 채널에 공지
AUTO_MAX_TRIES = 100      # [목표까지 자동] 한 번에 최대 시도 횟수
AUTO_CHUNK = 10           # 자동 강화는 이만큼씩 몰아서 계산한다 (DB 한 번에)
AUTO_EDIT_EVERY = 1.5     # 자동 강화 중 진행 상황 메시지는 이 초마다 고친다 (디스코드 수정 횟수 제한)

# 목표 레벨: (성공률 %, 실패했을 때 [유지, 한 단계 하락, 파괴] 비율 %)
# +1 부터 노렸을 때 도달 확률: +10 약 1/6.6, +11 약 1/54, +12 약 1/920, +13 약 1/53,000
ENHANCE_TABLE = {
    2:  (100, (100, 0, 0)),
    3:  (85,  (100, 0, 0)),
    4:  (70,  (100, 0, 0)),
    5:  (55,  (100, 0, 0)),
    6:  (43,  (70, 30, 0)),
    7:  (20,  (66, 33, 1)),
    8:  (16,  (63, 35, 2)),
    9:  (12,  (60, 37, 3)),
    10: (8,   (55, 40, 5)),
    11: (5,   (50, 42, 8)),
    12: (3,   (45, 45, 10)),
    13: (1,   (40, 50, 10)),
}

# 지금 레벨에서 한 번 시도할 때 드는 비용
ATTEMPT_COST = {
    1: 500, 2: 800, 3: 1200, 4: 1800, 5: 2500, 6: 4000,
    7: 6000, 8: 9000, 9: 13000, 10: 20000, 11: 30000, 12: 45000,
}

# 레벨별 판매가 (한 번 더 누를 때 평균 3~10% 손해, 고강을 노리면 평균 30~60%만 돌아오는 로또 구조)
SELL_PRICE = {
    1: 10000, 2: 10200, 3: 10800, 4: 12000, 5: 14500, 6: 20000, 7: 45000,
    8: 120000, 9: 370000, 10: 1600000, 11: 12000000, 12: 170000000, 13: 8000000000,
}

# DB 연결이 중간에 끊겼을 때 나는 에러들 (네트워크 문제). 이때 트랜잭션은 통째로 취소된다
DB_DISCONNECTED = (asyncpg.ConnectionDoesNotExistError, asyncpg.InterfaceError, ConnectionError, OSError, TimeoutError)

# ───────────── 계산 ─────────────

def outcome_chances(level, mult=1.0):
    """지금 레벨에서 누를 때 결과별 확률(%): (성공, 유지, 하락, 파괴)
    mult: 제물로 늘어난 성공률 배율 (최대 100%). 남은 실패 확률은 원래 비율대로 유지/하락/파괴로 나눈다."""
    success, (keep, down, destroy) = ENHANCE_TABLE[level + 1]
    success = min(100, success * mult)
    fail = 100 - success
    return success, fail * keep / 100, fail * down / 100, fail * destroy / 100


def sacrifice_mult(level, sacrifice_levels):
    """제물로 늘어나는 성공률 배율. 제물마다 (제물 판매가 ÷ 강화할 아이템 판매가) 만큼 더한다.
    같은 레벨 제물 하나면 2배. 레벨 차이(3^차이) 대신 판매가 비율을 쓰는 이유: 판매가가 위로 갈수록
    한 단계에 7~47배씩 뛰어서, 레벨 차이로 계산하면 +11/+12 에 싼 제물을 바치는 게 돈 복사가 된다.
    판매가 비율이면 어떤 제물을 몇 개 바쳐도 늘어나는 기대값이 제물 값보다 작다. (개수 제한 없음)"""
    return 1 + sum(SELL_PRICE[s] / SELL_PRICE[level] for s in sacrifice_levels)


def roll(level, bonus=None, mult=1.0):
    """한 번 굴린다. (결과, 새 레벨 또는 None, 발동한 능력 또는 None)
    결과: 'success' | 'keep' | 'down' | 'destroy'. bonus 는 abilities.totals 결과 (대성공 / 하락 방지 / 파괴 방지)
    mult 는 제물 성공률 배율."""
    bonus = bonus or {}
    success, keep, down, destroy = outcome_chances(level, mult)
    result = random.choices(
        ["success", "keep", "down", "destroy"], weights=[success, keep, down, destroy]
    )[0]
    new_level = {
        "success": level + 1,
        "keep": level,
        "down": max(1, level - 1),
        "destroy": None,
    }[result]

    special = None
    if result == "success" and level + 2 <= abilities.GREAT_SUCCESS_MAX_LEVEL and abilities.chance(bonus.get("great_success", 0)):
        new_level, special = level + 2, "great_success"
    elif result == "down" and abilities.chance(bonus.get("down_guard", 0)):
        result, new_level, special = "keep", level, "down_guard"
    elif result == "destroy" and abilities.chance(bonus.get("destroy_guard", 0)):
        # 파괴 대신 한 단계 하락 (하락 방지는 다시 굴리지 않는다)
        result, new_level, special = "down", max(1, level - 1), "destroy_guard"
    return result, new_level, special


RESULT_TEXT = {
    "success": "✅ 강화 성공",
    "keep": "⚪ 강화 실패 (레벨 유지)",
    "down": "📉 강화 실패 (레벨 하락)",
    "destroy": "💥 강화 실패 (아이템 파괴)",
}

SPECIAL_TEXT = {
    "great_success": "💥 **대성공!** 한 번에 +2",
    "down_guard": "🍀 하락 방지 발동!",
    "destroy_guard": "🛡️ **파괴 방지 발동!** (파괴 대신 하락)",
}


def result_line(r):
    """'✅ 강화 성공: +3 → +4' + 능력 발동 / 제물"""
    new_text = "파괴" if r["new"] is None else f"+{r['new']}"
    line = f"{RESULT_TEXT[r['result']]}: +{r['old']} → {new_text}"
    if r.get("special"):
        line += f"  {SPECIAL_TEXT[r['special']]}"
    if r.get("sacrificed"):
        names = ", ".join(f"{n} +{lv}" for n, lv in r["sacrificed"].items())
        line += f"\n🔥 제물 {names} → 성공률 x{r['mult']:.2f}"
    return line


def check_sacrifices(items, item_name, sacrifices):
    """제물 이름 목록이 쓸 수 있는지. 문제가 있으면 안내(str), 괜찮으면 None. items = {이름: 레벨}"""
    if len(set(sacrifices)) != len(sacrifices):
        return "❌ 같은 제물을 두 번 쓸 수 없어요."
    if item_name in sacrifices:
        return "❌ 강화할 아이템을 제물로 쓸 수 없어요."
    missing = [s for s in sacrifices if s not in items]
    if missing:
        return f"❌ 제물로 쓸 아이템이 없어요: {', '.join(missing)}"
    return None


def changed_text(level):
    return f"⚠️ 그사이 다른 곳에서 레벨이 바뀌어서 (지금 +{level}) 아무것도 하지 않았어요. 화면을 새로 고쳤어요."


async def try_enhance_many(user_id, item_name, sacrifices=(), expect_level=None, target=MAX_LEVEL, max_tries=1):
    """target 에 닿거나, 파괴되거나, 돈이 모자라거나, max_tries 번이 될 때까지 강화한다.
    한 트랜잭션 안에서 계산을 몰아서 하고 DB 에는 마지막에 한 번만 쓴다. (한 번씩 하면 시도마다 DB 왕복이 10번쯤 든다)
    - sacrifices: 제물로 바칠 아이템 이름들. 첫 번째 시도에만 쓰이고 사라진다.
    - expect_level: 패널에 보이는 레벨. DB 레벨과 다르면 (다른 패널 / 연타로 그사이 바뀌었으면) 강화하지 않는다.
      그래야 자동 강화가 목표를 넘기거나, 화면과 다른 레벨 · 비용으로 강화되는 일이 없다.
    - 능력 효과는 레벨이 바뀔 때마다 다시 계산한다 (레벨이 슬롯 레벨 밑으로 내려가면 그 슬롯은 꺼진다).
      처음 도달해서 슬롯이 열리면 그때 능력을 붙이고, 다음 시도부터 그 능력도 센다.
    첫 시도부터 못 하면 안내(str), 아니면 {"steps": [시도 결과...], "level", "balance", "stop": 멈춘 이유 또는 None}"""
    async with db.user_tx(user_id) as conn:
        items = await db.get_enhance_items(user_id, conn)
        level = items.get(item_name)
        if level is None:
            return "❌ 아이템이 없습니다."
        if expect_level is not None and level != expect_level:
            return changed_text(level)
        if level >= MAX_LEVEL:
            return f"🏆 이미 최고 레벨(+{MAX_LEVEL})입니다!"
        error = check_sacrifices(items, item_name, list(sacrifices))
        if error:
            return error
        money = await db.get_money(user_id, conn)
        if money < ATTEMPT_COST[level]:
            return f"💸 돈이 부족합니다. (필요: {num(ATTEMPT_COST[level])} byte / 보유: {num(money)} byte)"

        mult = sacrifice_mult(level, [items[s] for s in sacrifices])
        sacrificed = {s: items.pop(s) for s in sacrifices}
        for s in sacrifices:
            await db.delete_enhance_item(user_id, s, conn)   # 붙어 있던 능력도 같이 사라진다
        rows = await db.get_abilities(user_id, conn)       # 제물의 능력은 이미 빠졌다
        slots = sum(1 for r in rows if r["item_name"] == item_name)

        steps, logs, stop = [], [], None
        while len(steps) < max_tries and level is not None and level < min(target, MAX_LEVEL):
            cost = ATTEMPT_COST[level]
            if money < cost:
                stop = f"💸 돈이 부족합니다. (필요: {num(cost)} byte / 보유: {num(money)} byte)"
                break
            first = not steps
            result, new_level, special = roll(level, abilities.combine(items, rows), mult if first else 1.0)
            money -= cost
            memo = f"+{level} → {result}" + (f" (제물 {len(sacrifices)}개, x{mult:.2f})" if first and sacrifices else "")
            logs.append((user_id, "enhance_try", -cost, memo))
            opened = []
            if new_level is not None and abilities.open_slot_count(new_level) > slots:
                opened = await abilities.sync_slots(user_id, item_name, new_level, conn)  # +3/+5/... 처음 도달하면 슬롯 열림
                rows += [{"item_name": item_name, "locked": False, **o} for o in opened]
                slots += len(opened)
            steps.append({
                "result": result, "old": level, "new": new_level, "special": special, "opened": opened,
                "sacrificed": sacrificed if first else {}, "mult": mult if first else 1.0, "cost": cost,
            })
            level = new_level
            if level is None:
                items.pop(item_name)
            else:
                items[item_name] = level

        await db.update_user(user_id, conn, money=money)
        await db.log_money_many(logs, conn)
        if level is None:
            await db.delete_enhance_item(user_id, item_name, conn)
        else:
            await db.set_enhance_level(user_id, item_name, level, conn)

    return {"steps": steps, "level": level, "balance": money, "stop": stop}


async def try_enhance(user_id, item_name, sacrifices=(), expect_level=None):
    """한 번 강화한다. 실패하면 안내 메시지(str), 성공하면 그 한 번의 결과 dict (+ balance)."""
    r = await try_enhance_many(user_id, item_name, sacrifices, expect_level, max_tries=1)
    if isinstance(r, str):
        return r
    return {**r["steps"][0], "balance": r["balance"]}


async def craft(user_id, item_name):
    """아이템 제작. 실패하면 안내 메시지(str), 성공하면 None."""
    async with db.user_tx(user_id) as conn:
        items = await db.get_enhance_items(user_id, conn)
        if item_name in items:
            return "❌ 이미 같은 이름의 아이템이 있습니다."
        if len(items) >= MAX_ITEMS:
            return f"❌ 아이템은 최대 {MAX_ITEMS}개까지 가질 수 있어요. (`%강화판매`로 정리하세요)"
        money = await db.get_money(user_id, conn)
        if money < CRAFT_COST:
            return f"💸 제작비 {num(CRAFT_COST)} byte가 부족합니다."
        await db.update_user(user_id, conn, money=money - CRAFT_COST)
        await db.log_money(user_id, "enhance_craft", -CRAFT_COST, conn=conn)
        await db.set_enhance_level(user_id, item_name, 1, conn)
    return None


async def sell(user_id, item_name, expect_level=None):
    """판매. 아이템이 없으면 None, expect_level 과 레벨이 다르면 안내(str), 팔면 (레벨, 판매가, receive 결과)."""
    async with db.user_tx(user_id) as conn:
        if expect_level is not None:
            level = (await db.get_enhance_items(user_id, conn)).get(item_name)
            if level is not None and level != expect_level:
                return changed_text(level)
        level = await db.delete_enhance_item(user_id, item_name, conn)
        if level is None:
            return None
        price = SELL_PRICE[level]
        result = await db.receive(user_id, price, conn)
        await db.log_money(user_id, "enhance_sell", price, f"+{level}", conn)
    return level, price, result


async def announce(channel, user, item_name, result, old, new):
    """고강 성공 / 고강 아이템 파괴를 채널에 공지"""
    if result == "success" and new >= ANNOUNCE_LEVEL:
        embed = discord.Embed(
            title=f"🎉 +{new} 강화 성공!",
            description=(
                f"{user.mention}님의 **{item_name}**이(가) **+{new}**이 되었습니다!\n"
                f"판매가 **{num(SELL_PRICE[new])} byte**"
            ),
            color=discord.Color.gold()
        )
    elif result == "destroy" and old >= ANNOUNCE_LEVEL:
        embed = discord.Embed(
            title="💥 고강 아이템 파괴…",
            description=(
                f"{user.mention}님의 **+{old} {item_name}**이(가) 파괴되었습니다.\n"
                f"({num(SELL_PRICE[old])} byte짜리였습니다…)"
            ),
            color=discord.Color.dark_red()
        )
    else:
        return
    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        pass


# ───────────── 강화 패널 ─────────────

class EnhanceView(View):
    """%강화 로 열리는 패널. 누른 결과가 같은 메시지에 계속 갱신된다."""

    def __init__(self, ctx, item_name, target, sacrifices=None):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.user_id = ctx.author.id
        self.item_name = item_name
        self.target = target
        self.sacrifices = sacrifices or {}   # {제물 이름: 레벨} — 다음 한 번의 강화에 쓰이고 사라진다
        self.level = None          # None = 아직 없음(제작 전) 또는 파괴됨
        self.destroyed = False
        self.last = ""             # 마지막 결과 메시지
        self.sell_armed = False    # 판매 버튼 한 번 누르면 확인 상태
        self.message = None
        self.busy = False          # 버튼 하나를 처리하는 중 (그동안 다른 버튼은 막는다)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await respond.reply(interaction, "❌ 명령어를 실행한 사람만 사용할 수 있습니다.", ephemeral=True)
            return False
        return True

    async def load(self):
        self.level = (await db.get_enhance_items(self.user_id)).get(self.item_name)

    # ── 화면 ──

    async def make_embed(self):
        money = await db.get_money(self.user_id)

        if self.level is None:
            title = "💥 아이템 파괴" if self.destroyed else "🛠️ 새 아이템 제작"
            desc = self.last or (
                f"**{self.item_name}**이(가) 없습니다. 제작비 **{num(CRAFT_COST)} byte**로 +1 아이템을 만들 수 있어요."
            )
            embed = discord.Embed(title=title, description=desc, color=discord.Color.dark_grey())
            embed.add_field(name="보유 금액", value=f"{num(money)} byte", inline=True)
            return embed

        embed = discord.Embed(
            title=f"🔨 {self.item_name} +{self.level}",
            description=self.last or "버튼을 눌러 강화하세요.",
            color=discord.Color.gold() if self.level >= ANNOUNCE_LEVEL else discord.Color.blurple()
        )
        embed.add_field(name="판매가", value=f"{num(SELL_PRICE[self.level])} byte", inline=True)
        embed.add_field(name="보유 금액", value=f"{num(money)} byte", inline=True)

        if self.level < MAX_LEVEL:
            mult = sacrifice_mult(self.level, self.sacrifices.values())
            if self.sacrifices:
                embed.add_field(
                    name=f"🔥 제물 (다음 강화 한 번에 쓰이고 사라져요) → 성공률 x{mult:.2f}",
                    value=", ".join(f"{n} +{lv}" for n, lv in self.sacrifices.items()),
                    inline=False
                )
            success, keep, down, destroy = outcome_chances(self.level, mult)
            lines = [f"✅ 성공 **{num(success)}%** → +{self.level + 1} ({num(SELL_PRICE[self.level + 1])} byte)"]
            if keep:
                lines.append(f"⚪ 유지 {num(keep)}%")
            if down:
                lines.append(f"📉 하락 {num(down)}% → +{max(1, self.level - 1)}")
            if destroy:
                lines.append(f"💥 **파괴 {num(destroy)}%**")
            embed.add_field(
                name=f"다음 강화 (비용 {num(ATTEMPT_COST[self.level])} byte)",
                value="\n".join(lines),
                inline=False
            )
        else:
            embed.add_field(name="🏆 최고 레벨", value="더 이상 강화할 수 없어요. 팔거나 자랑하세요!", inline=False)

        if self.target:
            embed.set_footer(text=f"목표: +{self.target}")
        return embed

    def build_buttons(self):
        self.clear_items()

        def add(label, style, callback, emoji=None, disabled=False):
            button = Button(label=label, style=style, emoji=emoji, disabled=disabled)
            button.callback = self.one_at_a_time(callback)
            self.add_item(button)

        if self.level is None:
            if not self.destroyed:
                add(f"제작하기 ({num(CRAFT_COST)})", discord.ButtonStyle.success, self.on_craft, "🛠️")
            add("닫기", discord.ButtonStyle.secondary, self.on_close, "❌")
            return

        can_enhance = self.level < MAX_LEVEL
        add("강화하기", discord.ButtonStyle.primary, self.on_enhance, "🔨", disabled=not can_enhance)
        if self.target and self.level < self.target:
            add(f"+{self.target}까지 자동", discord.ButtonStyle.danger, self.on_auto, "🎯")
        if self.sell_armed:
            add(f"판매 확정 ({num(SELL_PRICE[self.level])})", discord.ButtonStyle.success, self.on_sell, "✅")
        else:
            add("판매", discord.ButtonStyle.secondary, self.on_sell, "💰")
        add("닫기", discord.ButtonStyle.secondary, self.on_close, "❌")

    async def refresh(self, interaction):
        await respond.defer(interaction)
        self.build_buttons()
        embed = await self.make_embed()
        await respond.edit(interaction, embed=embed, view=self)

    # ── 버튼 ──

    def one_at_a_time(self, callback):
        """앞에서 누른 버튼을 처리하는 동안 (자동 강화 중 포함) 누른 버튼은 막는다.
        연타하거나 화면이 바뀌기 전에 옛 버튼을 누르면 두 처리가 섞여서 엉뚱한 레벨로 강화될 수 있었다."""
        async def run(interaction):
            if self.busy:
                await respond.reply(interaction, "⏳ 앞에서 누른 것을 처리하는 중이에요. 끝나면 다시 눌러주세요.", ephemeral=True)
                return
            self.busy = True
            try:
                await callback(interaction)
            finally:
                self.busy = False
        return run

    async def on_craft(self, interaction):
        await respond.defer(interaction)
        error = await craft(self.user_id, self.item_name)
        if error:
            self.last = error
        else:
            self.level = 1
            self.last = f"🛠️ **{self.item_name} +1** 제작 완료! (-{num(CRAFT_COST)} byte)"
        await self.refresh(interaction)

    async def enhance_once(self):
        """제물이 있으면 이번 한 번에 쓰고 비운다. (제물이 그사이 없어졌으면 제물만 비우고 안내)"""
        r = await try_enhance(self.user_id, self.item_name, list(self.sacrifices), expect_level=self.level)
        if isinstance(r, str) and r.startswith("⚠️"):
            await self.load()         # 다른 곳에서 바뀐 레벨로 화면을 맞춘다
            return r
        if isinstance(r, str) and self.sacrifices and "제물" in r:
            self.sacrifices = {}
            return r + "\n제물을 비웠어요. 다시 누르면 제물 없이 강화해요."
        if not isinstance(r, str):
            self.sacrifices = {}
        return r

    async def on_enhance(self, interaction):
        await respond.defer(interaction)
        self.sell_armed = False
        r = await self.enhance_once()
        if isinstance(r, str):
            self.last = r
            await self.refresh(interaction)
            return

        self.apply(r)
        self.last = f"{result_line(r)}  (-{num(r['cost'])} byte)"
        if r["opened"]:
            self.last += "\n" + abilities.opened_text(r["opened"]) + f"\n`%강화능력설정 {self.item_name}`으로 확인 / 리롤"
        await self.refresh(interaction)
        await announce(interaction.channel, interaction.user, self.item_name, r["result"], r["old"], r["new"])

    async def enhance_chunk(self, max_tries):
        """자동 강화 한 몫. DB 연결이 중간에 끊기면 (네트워크) 그 몫은 통째로 취소되니까 한 번 더 해 본다.
        다시 할 때도 패널 레벨을 확인해서, 혹시 저장이 된 뒤에 끊긴 거라면 레벨이 달라서 멈춘다."""
        for attempt in range(2):
            try:
                return await try_enhance_many(
                    self.user_id, self.item_name, list(self.sacrifices), expect_level=self.level,
                    target=self.target, max_tries=max_tries,
                )
            except DB_DISCONNECTED as e:
                print(f"[강화] DB 연결 끊김 ({type(e).__name__}), {'다시 시도' if attempt == 0 else '포기'}")
        return "📡 DB 연결이 잠깐 끊겨서 멈췄어요. 마지막 몫은 취소됐으니 다시 눌러주세요."

    async def refresh_quietly(self, interaction):
        """자동 강화 진행 메시지 수정. 실패해도 강화는 계속한다."""
        try:
            await self.refresh(interaction)
        except (discord.HTTPException, *DB_DISCONNECTED) as e:
            print(f"[강화] 진행 메시지 수정 실패: {type(e).__name__}")

    async def on_auto(self, interaction):
        """목표까지 자동 강화. AUTO_CHUNK 번씩 몰아서 계산하고, 진행 상황을 AUTO_EDIT_EVERY 초마다 메시지에 보여준다."""
        await respond.defer(interaction)
        self.sell_armed = False
        logs, total_cost, tries, stop, opened = [], 0, 0, "", []
        last_edit = time.monotonic()
        editing = None      # 보내는 중인 진행 메시지 수정 (기다리지 않고 따로 보낸다)

        while tries < AUTO_MAX_TRIES and self.level is not None and self.level < self.target:
            r = await self.enhance_chunk(min(AUTO_CHUNK, AUTO_MAX_TRIES - tries))
            if isinstance(r, str):
                if r.startswith("⚠️"):
                    await self.load()
                stop = r
                break
            self.sacrifices = {}           # 제물은 첫 번째 시도에만
            for step in r["steps"]:
                tries += 1
                total_cost += step["cost"]
                opened += step["opened"]
                logs.append(result_line(step).replace("**", ""))
                await announce(interaction.channel, interaction.user, self.item_name, step["result"], step["old"], step["new"])
            self.level = r["level"]
            if self.level is None:
                self.destroyed = True
            if r["stop"]:
                stop = r["stop"]
                break
            # 진행 상황: 앞의 수정이 끝났고 AUTO_EDIT_EVERY 초가 지났을 때만. 수정이 끝나길 기다리지 않고 계속 계산한다
            # (기다리면 디스코드가 수정을 늦출 때 강화도 같이 멈춰서, 메시지가 멈췄다가 한꺼번에 바뀌어 보였다)
            if (time.monotonic() - last_edit >= AUTO_EDIT_EVERY and (editing is None or editing.done())
                    and self.level is not None and self.level < self.target):
                self.last = (
                    f"⏳ **자동 강화 중…** 지금 +{self.level} → 목표 +{self.target}\n"
                    f"시도 {tries}회, 비용 {num(total_cost)} byte\n```" + "\n".join(logs[-5:]) + "```"
                )
                editing = asyncio.create_task(self.refresh_quietly(interaction))
                last_edit = time.monotonic()

        if editing is not None:
            await editing      # 늦게 끝난 진행 메시지가 최종 결과를 덮어쓰지 않게

        if self.level is not None and self.level >= self.target:
            head = f"🎯 **+{self.target} 도달!**"
        elif self.level is None:
            head = "💥 자동 강화 중 아이템이 파괴되었습니다…"
        elif stop:
            head = f"⏹️ 자동 강화 중단: {stop}"
        else:
            head = f"⏹️ {AUTO_MAX_TRIES}회 시도 후 중단"

        self.last = (
            f"{head}\n시도 {tries}회, 총 비용 {num(total_cost)} byte\n"
            + ("```" + "\n".join(logs[-10:]) + "```" if logs else "")
            + (abilities.opened_text(opened) if opened and self.level is not None else "")
        )
        await self.refresh(interaction)

    async def on_sell(self, interaction):
        await respond.defer(interaction)
        if not self.sell_armed:
            self.sell_armed = True
            self.last = f"💰 정말 **+{self.level} {self.item_name}**을(를) {num(SELL_PRICE[self.level])} byte에 팔까요? 한 번 더 누르세요."
            await self.refresh(interaction)
            return

        sold = await sell(self.user_id, self.item_name, expect_level=self.level)
        self.sell_armed = False
        if isinstance(sold, str):
            await self.load()
            self.last = sold
            await self.refresh(interaction)
            return
        if sold is None:
            self.last = "❌ 이미 없는 아이템입니다."
            self.level = None
        else:
            level, price, result = sold
            self.level = None
            self.destroyed = True  # 다시 제작 버튼이 뜨지 않게
            self.last = f"💰 **+{level} {self.item_name}** 판매 완료! +{num(price)} byte" + debt_line(result["collected"])
        self.build_buttons()
        embed = await self.make_embed()
        embed.title = "💰 판매 완료" if sold else embed.title
        await respond.edit(interaction, embed=embed, view=None)
        self.stop()

    async def on_close(self, interaction):
        await respond.edit(interaction, view=None)
        self.stop()

    def apply(self, r):
        self.level = r["new"]
        if r["new"] is None:
            self.destroyed = True

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


@client.command(aliases=["강화"])
async def enhance(ctx, item_name: str = None, *args: str):
    """%강화 <이름> [목표] [제물 이름 ...]  — 목표는 숫자일 때만, 나머지는 전부 제물"""
    if item_name is None:
        await ctx.send(
            "아이템 이름을 입력해주세요!\n"
            "예: `%강화 칼` (없으면 제작, 있으면 강화)\n"
            "목표까지 자동: `%강화 칼 7`\n"
            "제물 바치기: `%강화 칼 방패 창` (제물마다 성공률 +(제물 판매가 ÷ 칼 판매가), 같은 레벨이면 2배)\n"
            "확률표: `%강화확률`"
        )
        return
    if len(item_name) > NAME_MAX_LEN:
        await ctx.send(f"❌ 아이템 이름은 {NAME_MAX_LEN}자까지예요.")
        return
    target = None
    if args and args[0].isdigit():
        target, args = int(args[0]), args[1:]
    if target is not None and not 2 <= target <= MAX_LEVEL:
        await ctx.send(f"❌ 목표 레벨은 +2 ~ +{MAX_LEVEL} 사이로 입력해주세요.")
        return

    sacrifices = {}
    if args:
        items = await db.get_enhance_items(ctx.author.id)
        if item_name not in items:
            await ctx.send(f"❌ 제물은 이미 있는 아이템을 강화할 때만 쓸 수 있어요. (`{item_name}` 없음)")
            return
        if items[item_name] >= MAX_LEVEL:
            await ctx.send(f"🏆 `{item_name}`은(는) 이미 최고 레벨이라 제물을 쓸 수 없어요.")
            return
        error = check_sacrifices(items, item_name, list(args))
        if error:
            await ctx.send(error)
            return
        sacrifices = {name: items[name] for name in args}

    view = EnhanceView(ctx, item_name, target, sacrifices)
    await view.load()
    view.build_buttons()
    view.message = await ctx.send(embed=await view.make_embed(), view=view)


@client.command(aliases=['강화목록'])
async def enhance_list(ctx, member: discord.Member = None):
    member = member or ctx.author
    user_items = await db.get_enhance_items(member.id)

    if not user_items:
        await ctx.send(f"😢 {member.display_name}님은 아직 강화 아이템이 없어요! (`%강화 <이름>`으로 제작)")
        return

    embed = discord.Embed(title=f"{member.display_name}님의 강화 아이템 ({len(user_items)}/{MAX_ITEMS})", color=0x2ecc71)
    for item_name, level in sorted(user_items.items(), key=lambda x: -x[1]):
        embed.add_field(
            name=f"{item_name} +{level}",
            value=f"판매가 {num(SELL_PRICE[level])} byte\n✨ 슬롯 {abilities.open_slot_count(level)}/{len(abilities.SLOT_LEVELS)}",
            inline=True
        )

    embed.set_footer(text="✨ 능력: %강화능력설정 <아이템> · 합친 효과: %내능력")
    await ctx.send(embed=embed)


@client.command(aliases=['강화판매'])
async def sell_enhance(ctx, item_name: str):
    respond.delete_soon(ctx.message)

    sold = await sell(ctx.author.id, item_name)
    if sold is None:
        await ctx.send(f"{ctx.author.mention} | ❌ `{item_name}` 아이템이 없습니다.")
        return

    level, price, result = sold
    embed = discord.Embed(
        title="💰 강화 아이템 판매",
        description=f"{ctx.author.mention}님이 `{item_name} +{level}`을 판매하였습니다!" + debt_line(result["collected"]),
        color=0x00ccff
    )
    embed.add_field(name="💵 획득 Byte", value=f"**{num(price)} byte**", inline=False)
    embed.add_field(name="💳 현재 보유 금액", value=f"**{num(result['balance'])} byte**", inline=False)
    await ctx.send(embed=embed)


# ───────────── 관리자: 아이템 만들기 / 레벨 바꾸기 (테스트용) ─────────────

async def admin_set_level(ctx, item_name, level, member, create):
    member = member or ctx.author
    if not 1 <= level <= MAX_LEVEL:
        await ctx.send(f"❌ 레벨은 +1 ~ +{MAX_LEVEL} 사이로 입력해주세요.")
        return
    if len(item_name) > NAME_MAX_LEN:
        await ctx.send(f"❌ 아이템 이름은 {NAME_MAX_LEN}자까지예요.")
        return
    async with db.user_tx(member.id) as conn:
        old = (await db.get_enhance_items(member.id, conn)).get(item_name)
        if create and old is not None:
            error = f"❌ `{item_name}` 아이템이 이미 있어요. 레벨을 바꾸려면 `%강화수정`을 쓰세요."
        elif not create and old is None:
            error = f"❌ `{item_name}` 아이템이 없어요. 만들려면 `%강화제작`을 쓰세요."
        else:
            error = None
            await db.set_enhance_level(member.id, item_name, level, conn)
            opened = await abilities.sync_slots(member.id, item_name, level, conn)
    if error:
        await ctx.send(error)
        return

    change = f"+{level} 제작" if create else f"+{old} → +{level}"
    lines = [f"🛠️ {member.mention}님의 **{item_name}** {change} (관리자)"]
    if opened:
        lines.append(abilities.opened_text(opened))
    if not create and level < old:
        lines.append("💤 레벨이 내려가서 그 위 슬롯은 꺼졌어요. (다시 올리면 켜져요)")
    await ctx.send("\n".join(lines))


@client.command(aliases=["강화제작"])
@commands.has_permissions(administrator=True)
async def admin_craft(ctx, item_name: str, level: int, member: discord.Member = None):
    """원하는 레벨의 아이템을 바로 만든다. 보유 개수 제한(5개)을 무시한다. 열리는 슬롯에는 능력이 붙는다."""
    await admin_set_level(ctx, item_name, level, member, create=True)


@client.command(aliases=["강화수정"])
@commands.has_permissions(administrator=True)
async def admin_set_enhance(ctx, item_name: str, level: int, member: discord.Member = None):
    """이미 있는 아이템의 레벨을 바꾼다. 처음 도달하는 슬롯은 열리고, 내려가면 위 슬롯은 꺼진다."""
    await admin_set_level(ctx, item_name, level, member, create=False)


@client.command(aliases=["강화랭킹"])
async def enhance_rank(ctx):
    respond.delete_soon(ctx.message)
    items = (await db.all_enhance_items())[:10]
    if not items:
        await ctx.send("❌ 아직 강화 아이템이 없습니다.")
        return

    embed = discord.Embed(title="🏆 강화 랭킹 TOP 10", description="서버 전체 최고 강화 아이템", color=discord.Color.gold())
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, item in enumerate(items, start=1):
        member = ctx.guild.get_member(item["user_id"]) if ctx.guild else None
        name = member.display_name if member else f"알 수 없음 ({item['user_id']})"
        embed.add_field(
            name=f"{medals.get(i, f'{i}위')} {item['item_name']} +{item['level']}",
            value=f"{name} · {num(SELL_PRICE[item['level']])} byte",
            inline=False
        )
    await ctx.send(embed=embed)


@client.command(aliases=["강화확률"])
async def enhance_odds(ctx):
    respond.delete_soon(ctx.message)
    lines = []
    for level in range(1, MAX_LEVEL):
        success, keep, down, destroy = outcome_chances(level)
        fail = []
        if keep:
            fail.append(f"유지 {num(keep)}%")
        if down:
            fail.append(f"하락 {num(down)}%")
        if destroy:
            fail.append(f"파괴 {num(destroy)}%")
        lines.append(
            f"+{level}→+{level + 1}  성공 {num(success)}%  | {' / '.join(fail)}  | 비용 {num(ATTEMPT_COST[level])}"
        )
    prices = "\n".join(f"+{lv}: {num(p)}" for lv, p in SELL_PRICE.items())
    embed = discord.Embed(title="🎲 강화 확률표", color=discord.Color.blurple())
    embed.add_field(name="강화 확률 / 비용 (byte)", value="```" + "\n".join(lines) + "```", inline=False)
    embed.add_field(name="판매가 (byte)", value="```" + prices + "```", inline=False)
    embed.set_footer(
        text=f"제작비 {num(CRAFT_COST)} byte · 1인 최대 {MAX_ITEMS}개 · +{ANNOUNCE_LEVEL} 이상은 공지됩니다\n"
             "🔥 제물: %강화 <이름> <제물...> → 제물마다 성공률 +(제물 판매가 ÷ 아이템 판매가), 같은 레벨이면 2배"
    )
    await ctx.send(embed=embed)
