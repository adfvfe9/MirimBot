"""일일 미션: 하루 3개, 깨면 byte, 3개 다 깨면 🪙 토큰

    %미션     (%일일미션) 오늘의 미션 · 진행도 · 보상 받기 버튼

- 미션은 사람마다 날짜마다 다르다. (유저 ID + 날짜로 정해서 따로 저장하지 않는다. 자정(한국 시간)에 바뀐다)
- 진행도는 돈 기록(money_log)에서 오늘 그 활동을 몇 번 했는지 센다. 미션 때문에 따로 기록하는 건 없다.
  (그래서 오늘 미션을 보기 전에 한 것도 센다)
- 보상은 버튼으로 받는다. 받은 것은 mission_claims 에 남아서 두 번 받을 수 없다.
"""
import random

import discord
from discord.ui import Button, View

import database as db
import respond
from bot import client
from fmt import debt_line, num

DAILY_COUNT = 3
ALL_CLEAR_TOKENS = 1

# key: (돈 기록 source, 필요한 횟수, 설명, 보상 byte)
MISSIONS = {
    "welfare":  ("welfare", 1, "🍚 기초수급 받기", 3000),
    "quiz":     ("quiz", 1, "🧠 선착순 퀴즈 1개 맞히기", 8000),
    "enhance":  ("enhance_try", 5, "🔨 강화 5번 하기", 5000),
    "gamble":   ("gamble", 3, "🎲 도박 3번 하기", 5000),
    "rps":      ("rps", 1, "✊ 가위바위보로 보상 받기", 7000),
    "word":     ("wordchain", 1, "🔤 끝말잇기로 보상 받기", 5000),
    "buy":      ("stock_buy", 1, "📈 주식 사기", 4000),
    "sell":     ("stock_sell", 1, "📉 주식 팔기", 4000),
    "futures":  ("futures_open", 1, "⚖️ 레버리지 들어가기 (%주식 롱 / %주식 숏)", 6000),
}


def todays(user_id, day):
    """오늘 이 사람의 미션 key 3개 (항상 같은 결과)"""
    rng = random.Random(f"{user_id}:{day.isoformat()}")
    return rng.sample(sorted(MISSIONS), DAILY_COUNT)


async def status(user_id, day=None):
    """[{key, text, need, done, reward, claimed}], 보너스를 받았는지"""
    day = day or db.today()
    keys = todays(user_id, day)
    counts = await db.money_log_counts_today(user_id, [MISSIONS[k][0] for k in keys], day)
    claimed = await db.mission_claims(user_id, day)
    rows = []
    for k in keys:
        source, need, text, reward = MISSIONS[k]
        rows.append({"key": k, "text": text, "need": need, "done": min(counts.get(source, 0), need),
                     "reward": reward, "claimed": k in claimed})
    return rows, "all" in claimed


async def claim(user_id):
    """다 한 미션 보상을 받는다. {"byte", "tokens", "names", "collected"} (받을 게 없으면 byte 0)"""
    day = db.today()
    rows, _ = await status(user_id, day)
    got_byte, got_tokens, names, collected = 0, 0, [], 0
    async with db.user_tx(user_id) as conn:
        for r in rows:
            if r["done"] >= r["need"] and await db.add_mission_claim(user_id, day, r["key"], conn):
                got_byte += r["reward"]
                names.append(r["text"])
        if got_byte:
            result = await db.receive(user_id, got_byte, conn)
            collected = result["collected"]
            await db.log_money(user_id, "mission", got_byte, ", ".join(names), conn)
        claimed = await db.mission_claims(user_id, day, conn)
        if all(r["key"] in claimed for r in rows) and await db.add_mission_claim(user_id, day, "all", conn):
            await db.add_tokens(user_id, ALL_CLEAR_TOKENS, conn)
            got_tokens = ALL_CLEAR_TOKENS
    return {"byte": got_byte, "tokens": got_tokens, "names": names, "collected": collected}


def bar(done, need, width=8):
    filled = round(width * done / need)
    return "▰" * filled + "▱" * (width - filled)


def mission_embed(member, rows, bonus):
    lines = []
    for r in rows:
        if r["claimed"]:
            state = "✅ 받음"
        elif r["done"] >= r["need"]:
            state = "🎁 받을 수 있어요"
        else:
            state = f"{bar(r['done'], r['need'])} {r['done']}/{r['need']}"
        lines.append(f"**{r['text']}** · {num(r['reward'])} byte\n{state}")
    all_done = all(r["claimed"] for r in rows)
    lines.append(f"\n🌟 **3개 모두** · 🪙 토큰 {ALL_CLEAR_TOKENS}개 — " + ("✅ 받음" if bonus else ("🎁 받을 수 있어요" if all_done else "남은 미션을 깨세요")))
    embed = discord.Embed(title=f"📋 {member.display_name}님의 오늘의 미션", description="\n".join(lines), color=discord.Color.orange())
    embed.set_footer(text="자정(한국 시간)에 새 미션 · 오늘 미리 한 것도 세어져요")
    return embed


class MissionView(View):
    def __init__(self, member):
        super().__init__(timeout=300)
        self.member = member
        button = Button(label="보상 받기", emoji="🎁", style=discord.ButtonStyle.success)
        button.callback = self.on_claim
        self.add_item(button)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.member.id:
            await respond.reply(interaction, "❌ `%미션`으로 내 미션을 열어주세요.", ephemeral=True)
            return False
        return True

    async def on_claim(self, interaction):
        await respond.defer(interaction)
        got = await claim(self.member.id)
        rows, bonus = await status(self.member.id)
        await respond.edit(interaction, embed=mission_embed(self.member, rows, bonus), view=self)
        if not got["byte"] and not got["tokens"]:
            await respond.reply(interaction, "아직 받을 보상이 없어요. 미션을 먼저 깨주세요!", ephemeral=True)
            return
        parts = []
        if got["byte"]:
            parts.append(f"+{num(got['byte'])} byte")
        if got["tokens"]:
            parts.append(f"🪙 +{got['tokens']} (3개 모두 완료!)")
        await respond.reply(interaction, "🎁 미션 보상: " + " · ".join(parts) + debt_line(got["collected"]), ephemeral=True)


@client.command(aliases=["미션", "일일미션"])
async def daily_missions(ctx):
    rows, bonus = await status(ctx.author.id)
    await ctx.send(embed=mission_embed(ctx.author, rows, bonus), view=MissionView(ctx.author))
