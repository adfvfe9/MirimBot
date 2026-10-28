"""강화 아이템 능력 슬롯

    %강화 능력설정 <아이템>   슬롯과 능력 보기 / 슬롯 잠금 / 리롤 (버튼)
    %강화 리롤 <아이템>          잠그지 않은 슬롯을 전부 다시 뽑기 (토큰 1개 + 잠근 슬롯 하나당 1개)
    %강화 능력 [@유저]         모든 아이템의 능력을 합친 효과

- +3 / +5 / +7 / +9 / +11 / +13 에 처음 도달하면 슬롯이 하나씩 열리고 능력이 공짜로 하나 붙는다.
  (v1.3.2 에서 +5 부터 → +3 부터로 바꿨다. 예전 슬롯 번호는 그대로라 1번이 +3 슬롯이 되고,
   비어 있는 칸은 봇이 켜질 때 sync_all 이 채운다)
- 아이템 레벨이 높을수록 좋은 등급이 잘 나온다. 수치는 등급 범위 안에서 랜덤이다.
- 같은 능력은 모든 아이템에서 합쳐지고, 상한이 없다. (강화에 돈이 많이 들어서 전부 풀었다)
  더 커지면 말이 안 되는 것만 한계가 있다: 꽝 환급 / 청산 보험 100%, 단타 시간 단축 30분.
- 레벨이 떨어지면 그 위 슬롯은 꺼지기만 하고 남는다. 아이템을 팔거나 파괴되면 능력도 사라진다.
- 주의: 예전에는 대성공 10% / 하락 방지 15% 상한을 계산으로 정했었다. 이보다 높게 모으면
  "강화해서 팔기"의 기대값이 판매가보다 커질 수 있다. (대성공은 결과 +6 이하에서만 그대로)
"""
import random

import discord
from discord.ext import commands
from discord.ui import Button, View

import database as db
import respond
from bot import client
from fmt import num

# ───────────── 슬롯 / 등급 ─────────────
SLOT_LEVELS = (3, 5, 7, 9, 11, 13)       # n번 슬롯이 열리는 레벨 (v1.3.2: +5 부터 → +3 부터, 6칸)
TIERS = ("일반", "희귀", "영웅", "전설")
TIER_EMOJI = ("⚪", "🔵", "🟣", "🟡")

# 아이템 레벨별 등급 확률 (%): 일반 / 희귀 / 영웅 / 전설. 레벨이 이 값 이상이면 적용
TIER_ODDS = (
    (13, (10, 30, 35, 25)),
    (11, (25, 35, 28, 12)),
    (9,  (40, 35, 20, 5)),
    (7,  (55, 32, 11, 2)),
    (5,  (70, 25, 5, 0)),
    (3,  (80, 18, 2, 0)),
)

REROLL_BASE = 1          # 리롤 토큰: 기본 1개
REROLL_PER_LOCK = 1      # 잠근 슬롯 하나당 +1개

GREAT_SUCCESS_MAX_LEVEL = 6   # 대성공(+2)은 결과가 이 레벨 이하일 때만 (높은 레벨까지 열면 돈 복사가 된다)

# ───────────── 능력 ─────────────
# ranges: 등급별 (최소, 최대). decimals: 뽑힌 수치의 소수 자리
# limit: 합친 수치의 한계. 밸런스 상한은 없앴고(강화에 돈이 많이 들어서), 더 커지면 말이 안 되는 것만 남겼다.
#   (꽝 환급 / 청산 보험 100% = 잃은 만큼 다 돌려받기, 단타 시간 단축 30분 = 단타 수수료 없음)
ABILITIES = {
    # 🔨 강화
    "great_success": dict(emoji="💥", name="대성공", unit="%", decimals=1, limit=None,
                          ranges=((1, 2), (2, 3), (3, 5), (5, 7)),
                          desc=f"강화에 성공하면 확률로 +2 (결과가 +{GREAT_SUCCESS_MAX_LEVEL} 이하일 때만)"),
    "destroy_guard": dict(emoji="🛡️", name="파괴 방지", unit="%", decimals=1, limit=None,
                          ranges=((1, 3), (3, 6), (6, 10), (10, 15)),
                          desc="파괴될 때 확률로 파괴 대신 한 단계 하락"),
    "down_guard":    dict(emoji="🍀", name="하락 방지", unit="%", decimals=1, limit=None,
                          ranges=((1, 2), (2, 4), (4, 7), (7, 10)),
                          desc="레벨이 떨어질 때 확률로 레벨 유지"),
    # 📈 주식 / 레버리지
    "leverage_up":   dict(emoji="🚀", name="배율 한계 돌파", unit="배", decimals=0, limit=None,
                          ranges=((1, 1), (1, 2), (2, 3), (3, 5)),
                          desc="레버리지 최대 배율 증가"),
    "liq_insurance": dict(emoji="🧯", name="청산 보험", unit="%", decimals=1, limit=100,
                          ranges=((1, 2), (2, 4), (4, 7), (7, 10)),
                          desc="강제청산 때 증거금의 일부를 돌려받기"),
    "quick_sell_time": dict(emoji="⏱️", name="단타 시간 단축", unit="분", decimals=0, limit=30,
                            ranges=((2, 4), (4, 8), (8, 12), (12, 18)),
                            desc="주식 단타 수수료가 붙는 시간(30분) 단축"),
    "sell_fee":      dict(emoji="💸", name="주식 판매 수수료 할인", unit="%p", decimals=2, limit=None,
                          ranges=((0.1, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.9)),
                          desc="주식 판매 수수료(보통 2%, 단타 8%)를 낮춤"),
    "margin_limit":  dict(emoji="📊", name="증거금 한도 증가", unit="%", decimals=1, limit=None,
                          ranges=((5, 10), (10, 20), (20, 35), (35, 50)),
                          desc="레버리지 증거금 합계 한도(10만) 증가"),
    # 🎲 놀이
    "rps_revive":    dict(emoji="✊", name="가위바위보 부활", unit="%", decimals=1, limit=None,
                          ranges=((2, 4), (4, 8), (8, 13), (13, 20)),
                          desc="가위바위보에서 지면 확률로 무효"),
    "gamble_refund": dict(emoji="🎰", name="도박 꽝 환급", unit="%", decimals=1, limit=100,
                          ranges=((1, 2), (2, 3), (3, 5), (5, 7)),
                          desc="도박이 꽝이면 판돈의 일부를 돌려받기"),
    "gamble_max":    dict(emoji="🎲", name="도박 판돈 한도 증가", unit="%", decimals=1, limit=None,
                          ranges=((5, 10), (10, 20), (20, 35), (35, 50)),
                          desc="도박 1회 최대 판돈(10만) 증가 (%도박 걸기 올인 포함)"),
    "rps_games":     dict(emoji="✌️", name="가위바위보 판수 증가", unit="판", decimals=0, limit=None,
                          ranges=((1, 1), (1, 1), (1, 2), (2, 3)),
                          desc="가위바위보 하루 판수(5판) 증가"),
    "wordchain_limit": dict(emoji="📅", name="끝말잇기 하루 한도", unit="%", decimals=1, limit=None,
                            ranges=((3, 8), (8, 15), (15, 25), (25, 40)),
                            desc="끝말잇기로 하루에 벌 수 있는 최대 금액(1.5만) 증가"),
    "token_decay":   dict(emoji="🔻", name="토큰 가격 하락 가속", unit="%", decimals=1, limit=None,
                          ranges=((0, 20), (20, 40), (40, 70), (70, 100)),
                          desc="토큰 구매 가격이 하루에 떨어지는 배율(4배)에 ×(1 + N%) "),
    "quiz_token":    dict(emoji="🪙", name="퀴즈 토큰 확률", unit="%p", decimals=1, limit=None,
                          ranges=((2, 4), (4, 7), (7, 11), (11, 16)),
                          desc="퀴즈를 맞히면 토큰을 받을 확률 증가"),
    # 💰 돈
    "welfare_bonus": dict(emoji="🍚", name="기초수급 보상", unit="%", decimals=1, limit=None,
                          ranges=((3, 8), (8, 15), (15, 25), (25, 40)),
                          desc="기초수급 지급액 증가"),
    "wordchain_bonus": dict(emoji="🔤", name="끝말잇기 보상", unit="%", decimals=1, limit=None,
                            ranges=((3, 8), (8, 15), (15, 25), (25, 40)),
                            desc="끝말잇기 단어당 보상 증가 (하루 한도는 📅 능력)"),
    "loan_limit":    dict(emoji="🏦", name="대출 한도 증가", unit="%", decimals=1, limit=None,
                          ranges=((5, 10), (10, 20), (20, 35), (35, 50)),
                          desc="은행 대출 한도(5만) 증가"),
}

# 능력마다 뽑힐 확률 (가중치). 많이 모이면 돈 복사가 되는 능력은 드물게, 아닌 능력은 흔하게 나온다.
# 등급(일반~전설)은 이와 따로 아이템 레벨별 확률(TIER_ODDS)로 뽑는다.
#   드묾: 기대값을 직접 바꾸는 것 — 꽝 환급 10% 넘으면 도박이 이득, 부활이 높으면 가위바위보 10연승이 쉬워짐,
#         청산 보험이 높으면 레버리지가 공짜 복권, 대성공 / 하락 방지가 높으면 강화해서 팔기가 이득
#   보통: 효과가 크지만 돈을 직접 만들지는 않는 것
#   흔함: 한도 · 보상을 조금씩 늘리는 것
RARITY = {1: "드묾", 3: "보통", 5: "흔함"}
ABILITY_WEIGHT = {
    "gamble_refund": 1, "rps_revive": 1, "liq_insurance": 1, "great_success": 1, "down_guard": 1,
    "destroy_guard": 3, "sell_fee": 3, "quick_sell_time": 3, "leverage_up": 3, "gamble_max": 3, "rps_games": 3,
    "welfare_bonus": 5, "wordchain_bonus": 5, "wordchain_limit": 5, "quiz_token": 5, "token_decay": 5,
    "loan_limit": 5, "margin_limit": 5,
}
assert set(ABILITY_WEIGHT) == set(ABILITIES), "능력을 추가하면 ABILITY_WEIGHT 에도 넣어야 한다"


def pick_chance(key):
    """이 능력이 뽑힐 확률 (%)"""
    return ABILITY_WEIGHT[key] / sum(ABILITY_WEIGHT.values()) * 100


def slot_level(slot):
    """slot 번 슬롯이 열리는 레벨 (1번 = +3)"""
    return SLOT_LEVELS[slot - 1]


def open_slot_count(level):
    return sum(1 for need in SLOT_LEVELS if level >= need)


def tier_odds(level):
    for need, odds in TIER_ODDS:
        if level >= need:
            return odds
    return TIER_ODDS[-1][1]


def roll(level):
    """레벨에 맞는 확률로 능력 하나를 뽑는다. (능력 키, 등급, 수치)"""
    tier = random.choices(range(len(TIERS)), weights=tier_odds(level))[0]
    key = random.choices(list(ABILITY_WEIGHT), weights=list(ABILITY_WEIGHT.values()))[0]
    info = ABILITIES[key]
    low, high = info["ranges"][tier]
    if info["decimals"] == 0:
        value = random.randint(int(low), int(high))
    else:
        value = round(random.uniform(low, high), info["decimals"])
    return key, tier, value


def format_value(key, value, unit=True):
    """4.2% / 0.35%p / 3배 (소수 끝의 0 은 뗀다)"""
    info = ABILITIES[key]
    text = f"{value:.{info['decimals']}f}".rstrip("0").rstrip(".") if info["decimals"] else str(int(value))
    return text + (info["unit"] if unit else "")


def describe(row):
    """'🛡️ 파괴 방지 4.2% · 🔵 희귀 (3~6%)'"""
    info = ABILITIES.get(row["ability"])
    if info is None:
        return "❔ (없어진 능력)"
    key = row["ability"]
    low, high = info["ranges"][row["tier"]]
    return (
        f"{info['emoji']} **{info['name']} {format_value(key, row['value'])}** · "
        f"{TIER_EMOJI[row['tier']]} {TIERS[row['tier']]} ({format_value(key, low, unit=False)}~{format_value(key, high)})"
    )


def chance(percent):
    """percent% 확률로 True"""
    return percent > 0 and random.random() * 100 < percent


# ───────────── 합산 ─────────────

async def totals(user_id, conn=None):
    """{능력 키: 합친 수치 (limit 이 있으면 그 안으로)}. 켜진 슬롯(아이템 레벨 >= 슬롯 레벨)만 센다."""
    rows = await db.get_ability_levels(user_id, conn)
    return combine({r["item_name"]: r["level"] for r in rows}, rows)


def combine(levels, rows):
    """totals 의 계산 부분. levels = {아이템 이름: 레벨}, rows = 능력 슬롯 목록.
    자동 강화는 DB 를 다시 읽지 않고 레벨만 바꿔 가며 이걸로 다시 계산한다."""
    result = {}
    for row in rows:
        level = levels.get(row["item_name"])
        if level is None or level < slot_level(row["slot"]) or row["ability"] not in ABILITIES:
            continue
        result[row["ability"]] = result.get(row["ability"], 0) + row["value"]
    return {key: value if ABILITIES[key]["limit"] is None else min(value, ABILITIES[key]["limit"])
            for key, value in result.items()}


async def total(user_id, key, conn=None):
    return (await totals(user_id, conn)).get(key, 0)


async def sync_slots(user_id, item_name, level, conn=None):
    """level 에서 열려야 하는데 아직 비어 있는 슬롯에 능력을 하나씩 붙인다. 새로 붙은 슬롯 [{slot, ability, tier, value}]"""
    existing = {row["slot"] for row in await db.get_abilities(user_id, conn) if row["item_name"] == item_name}
    opened = []
    for slot in range(1, open_slot_count(level) + 1):
        if slot in existing:
            continue
        key, tier, value = roll(level)
        await db.set_ability(user_id, item_name, slot, key, tier, value, conn)
        opened.append({"slot": slot, "ability": key, "tier": tier, "value": value})
    return opened


async def sync_all():
    """모든 강화 아이템의 빈 슬롯을 채운다. (봇 시작 때 한 번, 슬롯 레벨이 바뀌었을 때를 위해)"""
    filled = 0
    for item in await db.all_enhance_items():
        async with db.user_tx(item["user_id"]) as conn:
            filled += len(await sync_slots(item["user_id"], item["item_name"], item["level"], conn))
    if filled:
        print(f"[능력 슬롯] 빈 슬롯 {filled}개를 채웠습니다.")


def opened_text(opened):
    """강화 결과에 붙일 '새 슬롯' 안내"""
    return "\n".join(f"🔓 **{o['slot']}번 슬롯 열림!** {describe(o)}" for o in opened)


def reroll_cost(rows, level):
    """켜진 슬롯 중 잠근 개수만큼 비싸진다."""
    locked = sum(1 for r in rows if r["locked"] and level >= slot_level(r["slot"]))
    return REROLL_BASE + REROLL_PER_LOCK * locked


async def item_state(user_id, item_name, conn=None):
    """(레벨 또는 None, 이 아이템의 슬롯 목록)"""
    level = (await db.get_enhance_items(user_id, conn)).get(item_name)
    rows = [r for r in await db.get_abilities(user_id, conn) if r["item_name"] == item_name]
    return level, rows


async def reroll(user_id, item_name):
    """잠그지 않은 켜진 슬롯을 전부 다시 뽑는다. 실패하면 안내(str), 성공하면 {"cost", "rows"}"""
    async with db.user_tx(user_id) as conn:
        level, rows = await item_state(user_id, item_name, conn)
        if level is None:
            return "❌ 아이템이 없습니다."
        targets = [r for r in rows if not r["locked"] and level >= slot_level(r["slot"])]
        if not targets:
            return "❌ 다시 뽑을 슬롯이 없어요. (열린 슬롯이 없거나 전부 잠겨 있어요)"
        cost = reroll_cost(rows, level)
        if await db.add_tokens(user_id, -cost, conn) is None:
            return f"🪙 토큰이 부족합니다. (필요: {cost}개, `%토큰 구매` 또는 퀴즈로 얻을 수 있어요)"
        for r in targets:
            key, tier, value = roll(level)
            await db.set_ability(user_id, item_name, r["slot"], key, tier, value, conn)
        _, rows = await item_state(user_id, item_name, conn)
    return {"cost": cost, "rows": rows}


# ───────────── 화면 ─────────────

def item_embed(item_name, level, rows, tokens, last=""):
    embed = discord.Embed(
        title=f"✨ {item_name} +{level} 능력",
        description=last or "🔒 버튼으로 슬롯을 잠그면 리롤해도 안 바뀌어요. (대신 리롤이 토큰 1개씩 비싸져요)",
        color=discord.Color.purple(),
    )
    by_slot = {r["slot"]: r for r in rows}
    lines = []
    for slot, need in enumerate(SLOT_LEVELS, start=1):
        row = by_slot.get(slot)
        if row is None:
            lines.append(f"`{slot}` ⬛ +{need}에서 열려요")
        elif level < need:
            lines.append(f"`{slot}` 💤 {describe(row)} — 지금 꺼짐 (+{need} 필요)")
        else:
            lines.append(f"`{slot}` {'🔐 ' if row['locked'] else ''}{describe(row)}")
    embed.add_field(name="슬롯", value="\n".join(lines), inline=False)
    odds = tier_odds(level)
    embed.add_field(
        name=f"리롤 등급 확률 (+{level})",
        value=" / ".join(f"{TIER_EMOJI[i]} {TIERS[i]} {p}%" for i, p in enumerate(odds) if p),
        inline=False,
    )
    embed.set_footer(text=f"🪙 보유 토큰 {tokens}개 · 리롤 비용 {reroll_cost(rows, level)}개")
    return embed


class AbilityView(View):
    """%강화 능력설정 패널: 켜진 슬롯마다 잠금 버튼 + 리롤 버튼"""

    def __init__(self, user_id, item_name):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.item_name = item_name
        self.last = ""
        self.message = None

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await respond.reply(interaction, "❌ 명령어를 실행한 사람만 사용할 수 있습니다.", ephemeral=True)
            return False
        return True

    async def render(self):
        """(embed, 아이템이 남아 있는지)"""
        level, rows = await item_state(self.user_id, self.item_name)
        if level is None:
            return discord.Embed(description="❌ 아이템이 없어졌어요.", color=discord.Color.red()), False
        tokens = (await db.get_user(self.user_id))["tokens"]
        self.clear_items()
        for row in rows:
            if level >= slot_level(row["slot"]):
                button = Button(
                    label=f"{row['slot']}번 {'잠금 해제' if row['locked'] else '잠금'}",
                    emoji="🔓" if row["locked"] else "🔒",
                    style=discord.ButtonStyle.secondary,
                    row=0 if row["slot"] <= 5 else 1,   # 한 줄에 버튼 5개까지
                )
                button.callback = self.make_lock(row["slot"], not row["locked"])
                self.add_item(button)
        reroll_button = Button(label=f"리롤 (토큰 {reroll_cost(rows, level)}개)", emoji="🔄",
                               style=discord.ButtonStyle.primary, row=2)
        reroll_button.callback = self.on_reroll
        self.add_item(reroll_button)
        close = Button(label="닫기", emoji="❌", style=discord.ButtonStyle.secondary, row=2)
        close.callback = self.on_close
        self.add_item(close)
        return item_embed(self.item_name, level, rows, tokens, self.last), True

    async def refresh(self, interaction):
        embed, alive = await self.render()
        await respond.edit(interaction, embed=embed, view=self if alive else None)

    def make_lock(self, slot, locked):
        async def callback(interaction):
            await respond.defer(interaction)
            await db.set_ability_lock(self.user_id, self.item_name, slot, locked)
            self.last = f"{'🔐' if locked else '🔓'} {slot}번 슬롯을 {'잠갔어요' if locked else '풀었어요'}."
            await self.refresh(interaction)
        return callback

    async def on_reroll(self, interaction):
        await respond.defer(interaction)
        result = await reroll(self.user_id, self.item_name)
        self.last = result if isinstance(result, str) else f"🔄 리롤 완료! (토큰 -{result['cost']})"
        await self.refresh(interaction)

    async def on_close(self, interaction):
        await respond.edit(interaction, view=None)
        self.stop()

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


# ───────────── 명령어 ─────────────

@commands.command(name="능력설정")
async def ability_panel(ctx, item_name: str = None):
    if item_name is None:
        await ctx.send("아이템 이름을 입력해주세요! 예: `%강화 능력설정 칼`")
        return
    level, _ = await item_state(ctx.author.id, item_name)
    if level is None:
        await ctx.send(f"❌ `{item_name}` 아이템이 없습니다.")
        return
    view = AbilityView(ctx.author.id, item_name)
    embed, _ = await view.render()
    view.message = await ctx.send(embed=embed, view=view)


@commands.command(name="리롤")
async def reroll_command(ctx, item_name: str = None):
    if item_name is None:
        await ctx.send("아이템 이름을 입력해주세요! 예: `%강화 리롤 칼` (잠금은 `%강화 능력설정 칼`에서)")
        return
    result = await reroll(ctx.author.id, item_name)
    if isinstance(result, str):
        await ctx.send(f"{ctx.author.mention} {result}")
        return
    level, rows = await item_state(ctx.author.id, item_name)
    tokens = (await db.get_user(ctx.author.id))["tokens"]
    await ctx.send(embed=item_embed(item_name, level, rows, tokens, f"🔄 리롤 완료! (토큰 -{result['cost']})"))


@commands.command(name="능력")
async def my_abilities(ctx, member: discord.Member = None):
    member = member or ctx.author
    summed = await totals(member.id)
    embed = discord.Embed(title=f"✨ {member.display_name}님의 능력", color=discord.Color.purple())
    if not summed:
        embed.description = "아직 켜진 능력이 없어요. 강화 아이템을 +3까지 올리면 첫 슬롯이 열려요!"
    else:
        lines = []
        for key, info in ABILITIES.items():
            if key not in summed:
                continue
            limit = info["limit"]
            maxed = f" **(최대 {format_value(key, limit)})**" if limit is not None and summed[key] >= limit else ""
            lines.append(f"{info['emoji']} {info['name']} **{format_value(key, summed[key])}**{maxed} — {info['desc']}")
        embed.description = "\n".join(lines)
    embed.set_footer(text="같은 능력은 모든 아이템에서 합쳐져요 · 꺼진 슬롯(레벨 부족)은 빠져요")
    await ctx.send(embed=embed)
