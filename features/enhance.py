"""아이템 강화 (피파 인생강화 스타일)

    %강화 <이름> [목표]   아이템 제작(1만) / 강화 패널 열기. 목표를 쓰면 [목표까지 자동] 버튼이 생긴다.
    %강화판매 <이름>      판매가에 팔기
    %강화목록 [@유저]     보유 아이템
    %강화랭킹             서버 전체 최고 강화 아이템
    %강화확률             확률표

- 아이템은 +1 로 시작해서 최대 +10.
- 성공률은 피파와 같다. 낮은 레벨은 실패해도 유지, +6 부터는 떨어질 수 있고, +8 부터는 파괴될 수 있다.
- 한 번 더 누를 때마다 평균적으로 가진 가치의 3~7% 를 잃는다. 고강일수록 확률은 낮고 대박은 크다. (로또 구조)
"""
import random

import discord
from discord.ui import Button, View

import database as db
import respond
from bot import client
from fmt import debt_line, num

# ───────────── 밸런스 설정 ─────────────
CRAFT_COST = 10000        # 아이템 제작비 (+1 로 시작)
MAX_ITEMS = 5             # 1인 최대 보유 개수
MAX_LEVEL = 10
NAME_MAX_LEN = 20
ANNOUNCE_LEVEL = 8        # 이 레벨 이상 성공 / 이 레벨 이상 아이템 파괴 시 채널에 공지
AUTO_MAX_TRIES = 100      # [목표까지 자동] 한 번에 최대 시도 횟수

# 목표 레벨: (성공률 %, 실패했을 때 [유지, 한 단계 하락, 파괴] 비율 %)
ENHANCE_TABLE = {
    2:  (100, (100, 0, 0)),
    3:  (81,  (100, 0, 0)),
    4:  (64,  (100, 0, 0)),
    5:  (50,  (100, 0, 0)),
    6:  (26,  (70, 30, 0)),
    7:  (15,  (70, 30, 0)),
    8:  (7,   (60, 30, 10)),
    9:  (4,   (60, 30, 10)),
    10: (2,   (60, 30, 10)),
}

# 지금 레벨에서 한 번 시도할 때 드는 비용
ATTEMPT_COST = {1: 1000, 2: 1500, 3: 2000, 4: 3000, 5: 5000, 6: 7000, 7: 10000, 8: 15000, 9: 20000}

# 레벨별 판매가
SELL_PRICE = {
    1: 10000, 2: 10500, 3: 12000, 4: 15000, 5: 20000,
    6: 40000, 7: 110000, 8: 560000, 9: 4800000, 10: 76000000,
}


# ───────────── 계산 ─────────────

def outcome_chances(level):
    """지금 레벨에서 누를 때 결과별 확률(%): (성공, 유지, 하락, 파괴)"""
    success, (keep, down, destroy) = ENHANCE_TABLE[level + 1]
    fail = 100 - success
    return success, fail * keep / 100, fail * down / 100, fail * destroy / 100


def roll(level):
    """한 번 굴린다. ('success' | 'keep' | 'down' | 'destroy', 새 레벨 또는 None)"""
    success, keep, down, destroy = outcome_chances(level)
    result = random.choices(
        ["success", "keep", "down", "destroy"], weights=[success, keep, down, destroy]
    )[0]
    new_level = {
        "success": level + 1,
        "keep": level,
        "down": max(1, level - 1),
        "destroy": None,
    }[result]
    return result, new_level


RESULT_TEXT = {
    "success": "✅ 강화 성공",
    "keep": "⚪ 강화 실패 (레벨 유지)",
    "down": "📉 강화 실패 (레벨 하락)",
    "destroy": "💥 강화 실패 (아이템 파괴)",
}


async def try_enhance(user_id, item_name):
    """한 번 강화한다. 실패하면 안내 메시지(str), 성공하면 결과 dict."""
    async with db.user_tx(user_id) as conn:
        level = (await db.get_enhance_items(user_id, conn)).get(item_name)
        if level is None:
            return "❌ 아이템이 없습니다."
        if level >= MAX_LEVEL:
            return f"🏆 이미 최고 레벨(+{MAX_LEVEL})입니다!"

        cost = ATTEMPT_COST[level]
        money = await db.get_money(user_id, conn)
        if money < cost:
            return f"💸 돈이 부족합니다. (필요: {num(cost)} byte / 보유: {num(money)} byte)"

        result, new_level = roll(level)
        await db.update_user(user_id, conn, money=money - cost)
        if new_level is None:
            await db.delete_enhance_item(user_id, item_name, conn)
        else:
            await db.set_enhance_level(user_id, item_name, new_level, conn)

    return {
        "result": result,
        "old": level,
        "new": new_level,
        "cost": cost,
        "balance": money - cost,
    }


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
        await db.set_enhance_level(user_id, item_name, 1, conn)
    return None


async def sell(user_id, item_name):
    """판매. 아이템이 없으면 None, 있으면 (레벨, 판매가, receive 결과)."""
    async with db.user_tx(user_id) as conn:
        level = await db.delete_enhance_item(user_id, item_name, conn)
        if level is None:
            return None
        price = SELL_PRICE[level]
        result = await db.receive(user_id, price, conn)
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

    def __init__(self, ctx, item_name, target):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.user_id = ctx.author.id
        self.item_name = item_name
        self.target = target
        self.level = None          # None = 아직 없음(제작 전) 또는 파괴됨
        self.destroyed = False
        self.last = ""             # 마지막 결과 메시지
        self.sell_armed = False    # 판매 버튼 한 번 누르면 확인 상태
        self.message = None

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
            success, keep, down, destroy = outcome_chances(self.level)
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
            button.callback = callback
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
        await interaction.edit_original_response(embed=embed, view=self)

    # ── 버튼 ──

    async def on_craft(self, interaction):
        await respond.defer(interaction)
        await interaction.response.defer()
        error = await craft(self.user_id, self.item_name)
        if error:
            self.last = error
        else:
            self.level = 1
            self.last = f"🛠️ **{self.item_name} +1** 제작 완료! (-{num(CRAFT_COST)} byte)"
        await self.refresh(interaction)

    async def on_enhance(self, interaction):
        await respond.defer(interaction)
        await interaction.response.defer()
        self.sell_armed = False
        r = await try_enhance(self.user_id, self.item_name)
        if isinstance(r, str):
            self.last = r
            await self.refresh(interaction)
            return

        self.apply(r)
        new_text = "파괴" if r["new"] is None else f"+{r['new']}"
        self.last = f"{RESULT_TEXT[r['result']]}: +{r['old']} → {new_text}  (-{num(r['cost'])} byte)"
        await self.refresh(interaction)
        await announce(interaction.channel, interaction.user, self.item_name, r["result"], r["old"], r["new"])

    async def on_auto(self, interaction):
        await respond.defer(interaction)
        await interaction.response.defer()
        self.sell_armed = False
        logs, total_cost, tries, stop = [], 0, 0, ""

        while tries < AUTO_MAX_TRIES:
            if self.level is None or self.level >= self.target:
                break
            r = await try_enhance(self.user_id, self.item_name)
            if isinstance(r, str):
                stop = r
                break
            tries += 1
            total_cost += r["cost"]
            self.apply(r)
            new_text = "파괴" if r["new"] is None else f"+{r['new']}"
            logs.append(f"{RESULT_TEXT[r['result']]}: +{r['old']} → {new_text}")
            await announce(interaction.channel, interaction.user, self.item_name, r["result"], r["old"], r["new"])

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
        )
        await self.refresh(interaction)

    async def on_sell(self, interaction):
        await respond.defer(interaction)
        await interaction.response.defer()
        if not self.sell_armed:
            self.sell_armed = True
            self.last = f"💰 정말 **+{self.level} {self.item_name}**을(를) {num(SELL_PRICE[self.level])} byte에 팔까요? 한 번 더 누르세요."
            await self.refresh(interaction)
            return

        sold = await sell(self.user_id, self.item_name)
        self.sell_armed = False
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
        await interaction.edit_original_response(embed=embed, view=None)
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
async def enhance(ctx, item_name: str = None, target: int = None):
    if item_name is None:
        await ctx.send(
            "아이템 이름을 입력해주세요!\n"
            "예: `%강화 칼` (없으면 제작, 있으면 강화)\n"
            "목표까지 자동: `%강화 칼 7`\n"
            "확률표: `%강화확률`"
        )
        return
    if len(item_name) > NAME_MAX_LEN:
        await ctx.send(f"❌ 아이템 이름은 {NAME_MAX_LEN}자까지예요.")
        return
    if target is not None and not 2 <= target <= MAX_LEVEL:
        await ctx.send(f"❌ 목표 레벨은 +2 ~ +{MAX_LEVEL} 사이로 입력해주세요.")
        return

    view = EnhanceView(ctx, item_name, target)
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
        embed.add_field(name=f"{item_name} +{level}", value=f"판매가 {num(SELL_PRICE[level])} byte", inline=True)

    await ctx.send(embed=embed)


@client.command(aliases=['강화판매'])
async def sell_enhance(ctx, item_name: str):
    await ctx.message.delete()

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


@client.command(aliases=["강화랭킹"])
async def enhance_rank(ctx):
    await ctx.message.delete()
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
    await ctx.message.delete()
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
    embed.set_footer(text=f"제작비 {num(CRAFT_COST)} byte · 1인 최대 {MAX_ITEMS}개 · +{ANNOUNCE_LEVEL} 이상은 공지됩니다")
    await ctx.send(embed=embed)
