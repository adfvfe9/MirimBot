"""칭호: 조건을 채우면 얻는 업적. 하나를 장착하면 %자산 / %자산 랭킹 이름 앞에 붙는다.

    %칭호 [@유저]          칭호 목록과 진행도 (분류 고르기 / 보유한 것만 보기 버튼)
    %칭호 장착 <칭호 이름>   가진 칭호 하나 장착
    %칭호 해제              장착 해제
    %칭호 랭킹              가진 칭호 수 순위

- 한 번 얻은 칭호는 돈이 줄거나 파산해도 남는다.
- 진행도는 돈 기록(money_log, v1.2.8 부터)과 지금 상태로 계산한다. 그래서 v1.2.8 이전 기록은 세지 않는다.
- %칭호 를 볼 때와 1시간마다(자산 기록 때) 새로 채운 칭호를 자동으로 준다.
"""
import asyncio

import discord
from discord.ext import commands
from discord.ui import Button, Select, View

import database as db
import respond
from fmt import num

CATEGORIES = {
    "wealth":  "💰 재산",
    "enhance": "🔨 강화",
    "play":    "🎲 놀이",
    "invest":  "📈 투자",
    "brain":   "🧠 두뇌",
    "misc":    "🌟 기타",
}


def T(key, cat, emoji, name, desc, stat, goal, unit=""):
    return dict(key=key, cat=cat, emoji=emoji, name=name, desc=desc, stat=stat, goal=goal, unit=unit)


# stat: compute_stats 결과의 키. 그 값이 goal 이상이면 달성.
TITLES = [
    T("ant",        "wealth",  "🐜", "개미",          "순자산 최고 10만",            "peak_worth", 100_000, "byte"),
    T("middle",     "wealth",  "🏠", "중산층",        "순자산 최고 100만",           "peak_worth", 1_000_000, "byte"),
    T("rich",       "wealth",  "💰", "부자",          "순자산 최고 1,000만",         "peak_worth", 10_000_000, "byte"),
    T("tycoon",     "wealth",  "🏦", "재벌",          "순자산 최고 1억",             "peak_worth", 100_000_000, "byte"),
    T("whale",      "wealth",  "🐋", "고래",          "순자산 최고 10억",            "peak_worth", 1_000_000_000, "byte"),

    T("hammer",     "enhance", "🔨", "망치질 입문",    "강화 100번 시도",             "enhance_tries", 100, "번"),
    T("smith",      "enhance", "⚒️", "강화 장인",      "강화 1,000번 시도",           "enhance_tries", 1000, "번"),
    T("plus10",     "enhance", "🔟", "+10의 벽",       "+10 아이템 만들기",           "max_level", 10, "강"),
    T("plus13",     "enhance", "⚡", "강화의 신",      "+13 아이템 만들기",           "max_level", 13, "강"),
    T("breaker",    "enhance", "💥", "파괴왕",         "아이템 파괴 10번",            "destroyed", 10, "번"),

    T("gambler",    "play",    "🎲", "도박꾼",         "도박 100판",                  "gamble_count", 100, "판"),
    T("tazza",      "play",    "🃏", "타짜",           "도박 누적 수익 +100만",       "gamble_net", 1_000_000, "byte"),
    T("jackpot",    "play",    "7️⃣", "잭팟",          "도박 7배 당첨",               "jackpots", 1, "번"),
    T("rps5",       "play",    "✊", "가위바위보 고수", "가위바위보 5연승 하고 받기",   "rps_streak", 5, "연승"),
    T("rps10",      "play",    "🖐️", "가위바위보 신",   "가위바위보 10연승",           "rps_streak", 10, "연승"),

    T("trader",     "invest",  "📈", "주린이",         "주식 거래 50번",              "stock_trades", 50, "번"),
    T("leverage",   "invest",  "🎢", "레버리지 중독",   "롱 / 숏 50번 진입",           "futures_opens", 50, "번"),
    T("dealer",     "invest",  "🕶️", "암시장 큰손",    "암시장 거래 10번",            "market_trades", 10, "번"),
    T("coin_whale", "invest",  "₿",  "코인 부자",      "비트코인 평가액 100토큰",     "coin_value", 100, "토큰"),
    T("miner",      "invest",  "⛏️", "광부",           "비트코인 1 BTC 채굴",         "mined", 1, "BTC"),

    T("quiz50",     "brain",   "🧠", "퀴즈 박사",      "퀴즈 1등 50번",               "quiz_wins", 50, "번"),
    T("quiz300",    "brain",   "👑", "퀴즈왕",         "퀴즈 1등 300번",              "quiz_wins", 300, "번"),
    T("word",       "brain",   "🔤", "끝말잇기 달인",   "끝말잇기로 누적 30만 byte",   "wordchain_earned", 300_000, "byte"),
    T("dictionary", "brain",   "📚", "걸어다니는 사전", "끝말잇기 한 판 1,000점",      "wordchain_best", 1000, "점"),

    T("regular",    "misc",    "📅", "개근상",         "기초수급 30일 연속",          "welfare_streak", 30, "일"),
    T("donor",      "misc",    "💝", "기부천사",       "송금 누적 100만",             "sent", 1_000_000, "byte"),
    T("collector",  "misc",    "🪙", "토큰 수집가",     "토큰 30개 보유",              "tokens", 30, "개"),
    T("bankrupt",   "misc",    "🪦", "인생 2회차",      "파산 한 번 하기",             "bankrupt", 1, "번"),
]
BY_KEY = {t["key"]: t for t in TITLES}


def badge_of(key):
    """장착 칭호 → 이름 앞에 붙일 글자. 없으면 빈 문자열"""
    t = BY_KEY.get(key)
    return f"[{t['emoji']} {t['name']}] " if t else ""


async def badge(user_id):
    owned = await db.get_titles(user_id)
    return badge_of(next((k for k, v in owned.items() if v["equipped"]), None))


# ───────────── 진행도 ─────────────

async def compute_stats(user_id, worth=None):
    from features import assets, crypto, mining   # 서로 import 하지 않게 여기서

    async def known(value):
        return value

    # 서로 상관없는 조회라 한꺼번에 보낸다 (차례로 보내면 DB 왕복 10번 넘게 기다린다)
    s, user, items, holding, miner, worth, peak, best = await asyncio.gather(
        db.title_stats(user_id), db.get_user(user_id), db.get_enhance_items(user_id),
        db.get_coin_holding(user_id), db.get_miner(user_id),
        assets.net_worth(user_id) if worth is None else known(worth),
        db.peak_worth(user_id), db.wordchain_best(user_id),
    )
    count, total = s["count"], s["sum"]
    return {
        "peak_worth": max(worth, peak),
        "enhance_tries": count.get("enhance_try", 0),
        # 성공 기록의 "+N → success" 는 N+1 이 된 것. 지금 가진 아이템 레벨도 같이 본다
        "max_level": max([s["max_success"] + 1 if s["max_success"] else 0, *items.values()]),
        "destroyed": s["destroyed"],
        "gamble_count": count.get("gamble", 0),
        "gamble_net": user["gamble_net"],
        "jackpots": s["jackpots"],
        "rps_streak": s["rps_streak"],
        "stock_trades": count.get("stock_buy", 0) + count.get("stock_sell", 0),
        "futures_opens": count.get("futures_open", 0),
        "market_trades": count.get("market_buy", 0) + count.get("market_sell", 0),
        "coin_value": holding["amount"] * crypto.price,
        "mined": miner["mined"] / mining.scale,   # 처음 액면 기준 (액면 조정이 있어도 같은 기준)
        "quiz_wins": count.get("quiz", 0),
        "wordchain_earned": total.get("wordchain", 0),
        "wordchain_best": best,
        "welfare_streak": s["welfare_streak"],
        "sent": -total.get("transfer_send", 0),
        "tokens": user["tokens"],
        "bankrupt": 1 if user.get("bankruptcy_date") else 0,
    }


async def check(user_id, worth=None):
    """조건을 채운 칭호를 준다. (stats, 가진 칭호 dict, 이번에 새로 얻은 key 목록)
    worth: 이미 계산한 순자산이 있으면 넘긴다 (1시간 기록 때)"""
    stats, owned = await asyncio.gather(compute_stats(user_id, worth), db.get_titles(user_id))
    new = [t["key"] for t in TITLES if t["key"] not in owned and stats[t["stat"]] >= t["goal"]]
    if new:
        await db.add_titles(user_id, new)
        owned = await db.get_titles(user_id)
        from features import digest
        digest.new_titles(user_id, [BY_KEY[k] for k in new])    # 🏅 소식 채널에 자랑
    return stats, owned, new


def fmt_value(value, unit):
    if unit == "BTC":
        return f"{value:.4f}"
    return num(value)


def bar(ratio, width=10):
    filled = int(ratio * width)
    return "▓" * filled + "░" * (width - filled)


def title_line(t, stats, owned):
    if t["key"] in owned:
        got = owned[t["key"]]
        mark = "🎖️" if got["equipped"] else "✅"
        return f"{mark} {t['emoji']} **{t['name']}** — {t['desc']} · <t:{int(got['achieved_at'].timestamp())}:d> 달성"
    value = max(0, stats[t["stat"]])
    ratio = min(1.0, value / t["goal"])
    return (
        f"⬜ {t['emoji']} {t['name']} — {t['desc']}\n"
        f"　`{bar(ratio)}` {int(ratio * 100)}% ({fmt_value(value, t['unit'])} / {fmt_value(t['goal'], t['unit'])} {t['unit']})"
    )


def build_embed(member, stats, owned, category, owned_only, new=()):
    shown = [t for t in TITLES if (category == "all" or t["cat"] == category) and (not owned_only or t["key"] in owned)]
    equipped = next((k for k, v in owned.items() if v["equipped"]), None)
    embed = discord.Embed(
        title=f"🏅 {member.display_name}님의 칭호 ({sum(1 for t in TITLES if t['key'] in owned)}/{len(TITLES)})",
        color=discord.Color.gold(),
    )
    head = f"장착: **{badge_of(equipped).strip() or '없음'}**"
    if new:
        head += "\n🎉 새로 얻은 칭호: " + ", ".join(f"{BY_KEY[k]['emoji']} **{BY_KEY[k]['name']}**" for k in new)
    blocks = [head]
    for cat, cat_name in CATEGORIES.items():
        lines = [title_line(t, stats, owned) for t in shown if t["cat"] == cat]
        if lines:
            blocks.append(f"**{cat_name}**\n" + "\n".join(lines))
    if len(blocks) == 1:
        blocks.append("아직 얻은 칭호가 없어요." if owned_only else "칭호가 없어요.")
    embed.description = "\n\n".join(blocks)[:4096]
    embed.set_footer(text="🎖️ 장착 중 · ✅ 보유 · ⬜ 진행 중 | %칭호 장착 <이름> · %칭호 해제 · 기록은 v1.2.8부터 셉니다")
    return embed


class TitleView(View):
    def __init__(self, viewer_id, member, stats, owned):
        super().__init__(timeout=180)
        self.viewer_id, self.member, self.stats, self.owned = viewer_id, member, stats, owned
        self.category, self.owned_only = "all", False

        self.select = Select(
            placeholder="분류 고르기",
            options=[discord.SelectOption(label="전체", value="all", emoji="📋")]
            + [discord.SelectOption(label=name[2:], value=key, emoji=name[0]) for key, name in CATEGORIES.items()],
        )
        self.select.callback = self.on_select
        self.add_item(self.select)
        self.toggle = Button(label="보유한 것만", style=discord.ButtonStyle.secondary, emoji="✅")
        self.toggle.callback = self.on_toggle
        self.add_item(self.toggle)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.viewer_id:
            await respond.reply(interaction, "이 버튼은 당신의 것이 아니에요! `%칭호`로 직접 열어보세요.", ephemeral=True)
            return False
        return True

    async def refresh(self, interaction):
        self.toggle.label = "전부 보기" if self.owned_only else "보유한 것만"
        await respond.edit(
            interaction,
            embed=build_embed(self.member, self.stats, self.owned, self.category, self.owned_only),
            view=self,
        )

    async def on_select(self, interaction):
        await respond.defer(interaction)
        self.category = self.select.values[0]
        await self.refresh(interaction)

    async def on_toggle(self, interaction):
        await respond.defer(interaction)
        self.owned_only = not self.owned_only
        await self.refresh(interaction)


# ───────────── 명령어 ─────────────

@commands.command(name="보기")
async def titles_command(ctx, member: discord.Member = None):
    member = member or ctx.author
    stats, owned, new = await check(member.id)
    await ctx.send(
        embed=build_embed(member, stats, owned, "all", False, new),
        view=TitleView(ctx.author.id, member, stats, owned),
    )


def find_title(name):
    name = name.replace(" ", "")
    for t in TITLES:
        if t["name"].replace(" ", "") == name or t["key"] == name:
            return t
    return None


@commands.command(name="장착", usage="<칭호>")
async def title_equip(ctx, *, name: str = None):
    if not name:
        await ctx.send("사용법: `%칭호 장착 <칭호 이름>` 예) `%칭호 장착 개미` (`%칭호`에서 가진 칭호 확인)")
        return
    t = find_title(name)
    if t is None:
        await ctx.send(f"❌ `{name}` 이라는 칭호는 없어요. `%칭호`에서 이름을 확인해주세요.")
        return
    _, owned, _ = await check(ctx.author.id)
    if t["key"] not in owned:
        await ctx.send(f"❌ 아직 {t['emoji']} **{t['name']}** 칭호가 없어요. ({t['desc']})")
        return
    await db.equip_title(ctx.author.id, t["key"])
    await ctx.send(f"🎖️ {t['emoji']} **{t['name']}** 칭호를 장착했어요! `%자산`, `%자산 랭킹`에 표시돼요.")


@commands.command(name="해제")
async def title_unequip(ctx):
    await db.equip_title(ctx.author.id, None)
    await ctx.send("칭호를 해제했어요.")


@commands.command(name="랭킹")
async def title_rank(ctx):
    counts = sorted((await db.title_counts()).items(), key=lambda kv: -kv[1])[:10]
    if not counts:
        await ctx.send("❌ 아직 칭호를 가진 사람이 없어요. `%칭호`로 확인해보세요!")
        return
    equipped = await db.equipped_titles()
    embed = discord.Embed(title="🏅 칭호 랭킹 TOP 10", description=f"가진 칭호 수 기준 (전체 {len(TITLES)}개)", color=discord.Color.gold())
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, (uid, n) in enumerate(counts, start=1):
        member = ctx.guild.get_member(uid) if ctx.guild else None
        name = member.display_name if member else f"알 수 없음 ({uid})"
        embed.add_field(name=f"{medals.get(i, f'{i}위')} {badge_of(equipped.get(uid))}{name}", value=f"{n}개", inline=False)
    await ctx.send(embed=embed)
