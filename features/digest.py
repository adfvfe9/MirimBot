"""오늘의 미림봇 · 자랑 알림: 봇이 먼저 채널에 소식을 올린다

    %관리 소식채널 [채널ID | 끄기]   (관리자) 소식을 올릴 채널. 안 정하면 주식 뉴스 채널 (%관리 뉴스채널)
    %관리 소식미리보기             (관리자) 오늘의 미림봇을 지금 미리 보기

- 매일 DIGEST_TIME 에 '오늘의 미림봇': 오늘 쓴 사람, 순자산이 많이 늘어난 / 줄어든 사람, 강화 · 잭팟 · 강제청산,
  주식 등락, 미션을 다 깬 사람, 기초수급 연속. 그날 아무도 안 썼으면 보내지 않는다.
  ('오늘 번 돈'은 1시간마다 기록하는 순자산으로 잰다. 주식을 사서 현금이 준 것을 잃은 것으로 세지 않으려고)
- 자랑 알림: 도박 잭팟, 레버리지로 크게 번 것, 강제청산, 가위바위보 연승, 칭호 획득을 바로 소식 채널에 띄운다.
  친구 이름이 보이면 "나도 해볼까"가 생긴다. 다 brag_log 에 남아서 하루 소식에도 쓰인다.
- 기준 금액(…_MIN)보다 작은 건 알림을 띄우지 않는다. (기록은 남는다)
"""
import asyncio
import datetime
import re

import discord
from discord.ext import commands

import database as db
from bot import client
from fmt import num

DIGEST_TIME = datetime.time(21, 0)
POST_GRACE = datetime.timedelta(hours=2)
KEEP_DAYS = 14

JACKPOT_MIN_BET = 10_000          # 잭팟 알림: 판돈이 이 이상일 때
BIG_WIN_MIN = 50_000             # 레버리지 알림: 번 돈 (받은 돈 - 증거금)
LIQUIDATION_MIN = 100_000         # 강제청산 알림: 잃은 증거금
RPS_STREAK_MIN = 5               # 가위바위보 알림: 이 연승 이상 받으면

STYLE = {   # kind: (이모지, 색)
    "jackpot": ("🎰", 0xf1c40f), "big_win": ("💸", 0x2ecc71), "liquidation": ("💥", 0xe74c3c),
    "rps": ("✊", 0x3498db), "title": ("🏅", 0x9b59b6),
}
WEEKDAYS = "월화수목금토일"
EXCLUDE_FROM_EARNINGS = ("admin_add", "admin_remove")   # 관리자가 넣고 뺀 돈은 '번 돈'에서 뺀다


# ───────────── 소식 채널 ─────────────

def channel_key(guild_id):
    return f"digest_channel:{int(guild_id)}"


async def channel_of(guild):
    """소식 채널 (없으면 None). 따로 안 정했으면 주식 뉴스 채널"""
    value = await db.get_state(channel_key(guild.id))
    if value == "off":
        return None
    if value is None:
        value = await db.get_state(f"news_channel:{guild.id}")
    return guild.get_channel(int(value)) if value else None


# ───────────── 자랑 알림 ─────────────

def brag(user_id, kind, text, amount=None, announce=True):
    """기록하고 (announce 면) 그 사람이 있는 서버의 소식 채널에 띄운다. 부른 쪽을 기다리게 하지 않는다."""
    async def run():
        try:
            await db.add_brag(user_id, kind, text, amount)
            if not announce:
                return
            emoji, color = STYLE.get(kind, ("📣", 0x95a5a6))
            for guild in client.guilds:
                member = guild.get_member(int(user_id))
                channel = member and await channel_of(guild)
                if channel is None:
                    continue
                embed = discord.Embed(description=f"{emoji} {member.mention}{text}", color=color)
                await channel.send(embed=embed)
        except Exception as e:
            print(f"[자랑 알림] 실패: {type(e).__name__} {e}")
    asyncio.create_task(run())


def jackpot(user_id, bet, payout):
    brag(user_id, "jackpot", f"님이 **도박 잭팟 7배**! {num(bet)} → **{num(payout)} byte** 🎉", payout - bet,
         announce=bet >= JACKPOT_MIN_BET)


def leverage_win(user_id, pos, profit):
    side = "롱" if pos["side"] == "long" else "숏"
    brag(user_id, "big_win", f"님이 `{pos['symbol']}` {side} {pos['leverage']}배로 **+{num(profit)} byte**를 벌었어요!", profit,
         announce=profit >= BIG_WIN_MIN)


def liquidation(user_id, pos, lost):
    side = "롱" if pos["side"] == "long" else "숏"
    brag(user_id, "liquidation", f"님의 `{pos['symbol']}` {side} {pos['leverage']}배 포지션이 **강제청산**됐어요… 증거금 {num(lost)} byte 증발",
         lost, announce=lost >= LIQUIDATION_MIN)


def rps_streak(user_id, streak, reward):
    brag(user_id, "rps", f"님이 가위바위보 **{streak}연승**! **+{num(reward)} byte** 받았어요", reward,
         announce=streak >= RPS_STREAK_MIN)


def new_titles(user_id, titles_):
    for t in titles_:
        brag(user_id, "title", f"님이 칭호 **{t['emoji']} {t['name']}**을(를) 얻었어요! ({t['desc']})")


# ───────────── 오늘의 미림봇 ─────────────

ENHANCE_RE = re.compile(r"\+(\d+) → (\w+)")


def day_start(day):
    return datetime.datetime.combine(day, datetime.time(0), db.KST)


async def build(guild, now=None):
    """오늘의 미림봇 embed. 그날 쓴 사람이 없으면 None"""
    from features import assets, stocks
    now = now or db.now()
    today = now.date()
    start = day_start(today)
    members = lambda ids: [uid for uid in ids if guild.get_member(int(uid))]

    active = members(await db.active_users_since(start))
    talk = [r for r in await db.money_log_since(start, ("voice", "chat")) if guild.get_member(int(r["user_id"]))]
    if not active and not talk:
        return None
    embed = discord.Embed(
        title=f"🌙 오늘의 미림봇 · {today.month}월 {today.day}일 ({WEEKDAYS[today.weekday()]})",
        description=f"오늘 미림봇을 쓴 사람 **{len(active)}명**",
        color=0x34495e,
    )

    # 💰 순자산 변화 (관리자가 넣고 뺀 돈은 뺀다)
    baseline = await db.worth_baseline(start)
    worths = await assets.all_net_worths()
    admin = {}
    for r in await db.money_log_since(start, EXCLUDE_FROM_EARNINGS):
        admin[r["user_id"]] = admin.get(r["user_id"], 0) + r["amount"]
    changes = sorted(
        ((uid, worths[uid] - baseline[uid] - admin.get(uid, 0)) for uid in members(worths) if uid in baseline),
        key=lambda x: x[1], reverse=True,
    )
    winners = [(u, c) for u, c in changes if c >= 1][:3]
    losers = [(u, c) for u, c in reversed(changes) if c <= -1][:3]
    if winners:
        embed.add_field(name="📈 오늘 순자산이 가장 많이 늘어난 사람",
                        value="\n".join(f"{i}. <@{u}> **+{num(round(c))}**" for i, (u, c) in enumerate(winners, 1)), inline=True)
    if losers:
        embed.add_field(name="📉 오늘 가장 많이 잃은 사람",
                        value="\n".join(f"{i}. <@{u}> **{num(round(c))}**" for i, (u, c) in enumerate(losers, 1)), inline=True)

    # 🔨 강화 · 🎰 잭팟 · 💥 강제청산 · ✊ 연승 · 🏅 칭호
    lines = []
    tries = await db.money_log_since(start, ("enhance_try",))
    tries = [r for r in tries if guild.get_member(int(r["user_id"]))]
    if tries:
        best, destroyed = None, []
        for r in tries:
            m = ENHANCE_RE.search(r["memo"] or "")
            if not m:
                continue
            level, result = int(m.group(1)), m.group(2)
            if result == "success" and (best is None or level + 1 > best[1]):
                best = (r["user_id"], level + 1)
            if result == "destroy":
                destroyed.append(level)
        line = f"🔨 강화 **{len(tries)}번**"
        if best:
            line += f" · 최고 <@{best[0]}> **+{best[1]}** 성공"
        if destroyed:
            line += f" · 💥 파괴 {len(destroyed)}번 (최고 +{max(destroyed)})"
        lines.append(line)
    brags = [b for b in await db.brags_since(start) if guild.get_member(int(b["user_id"]))]
    by_kind = {}
    for b in brags:
        by_kind.setdefault(b["kind"], []).append(b)
    if by_kind.get("jackpot"):
        lines.append(f"🎰 도박 잭팟 **{len(by_kind['jackpot'])}번**: " + ", ".join(f"<@{b['user_id']}>" for b in by_kind["jackpot"][:5]))
    if by_kind.get("big_win"):
        top = max(by_kind["big_win"], key=lambda b: b["amount"] or 0)
        lines.append(f"💸 레버리지 최고 수익: <@{top['user_id']}> **+{num(top['amount'])}**")
    if by_kind.get("liquidation"):
        lost = sum(b["amount"] or 0 for b in by_kind["liquidation"])
        lines.append(f"💥 강제청산 **{len(by_kind['liquidation'])}번**, 날아간 증거금 {num(lost)} byte")
    if by_kind.get("rps"):
        top = max(by_kind["rps"], key=lambda b: b["amount"] or 0)
        lines.append(f"✊ 가위바위보 최고: <@{top['user_id']}> **+{num(top['amount'])}**")
    if by_kind.get("title"):
        lines.append(f"🏅 새 칭호 **{len(by_kind['title'])}개**: " + ", ".join(sorted({f'<@{b["user_id"]}>' for b in by_kind['title']})))
    if lines:
        embed.add_field(name="🎲 오늘 있었던 일", value="\n".join(lines)[:1024], inline=False)

    # 🎧 통화방 · 💬 채팅 (activity.py 가 5분마다 'voice' "N분" / 'chat' "N개" 로 기록한다)
    minutes, messages, earned = {}, {}, {}
    for r in talk:
        n = int(re.sub(r"\D", "", r["memo"] or "") or 0)
        target = minutes if r["source"] == "voice" else messages
        target[r["user_id"]] = target.get(r["user_id"], 0) + n
        earned[r["user_id"]] = earned.get(r["user_id"], 0) + r["amount"]
    talk_lines = []
    if minutes:
        top = sorted(minutes.items(), key=lambda x: x[1], reverse=True)[:3]
        talk_lines.append("🎧 통화방: " + " · ".join(f"<@{u}> {m // 60}시간 {m % 60}분" if m >= 60 else f"<@{u}> {m}분" for u, m in top))
    if messages:
        top = sorted(messages.items(), key=lambda x: x[1], reverse=True)[:3]
        talk_lines.append("💬 수다왕: " + " · ".join(f"<@{u}> {n}개" for u, n in top))
    if talk_lines:
        talk_lines.append(f"(통화방 · 채팅으로 모두 {num(round(sum(earned.values())))} byte 받았어요)")
        embed.add_field(name="🎧 통화방 · 💬 채팅", value="\n".join(talk_lines)[:1024], inline=False)

    # 🎮 오늘의 랭크 (games.py 가 기록한 롤 · 발로란트 랭크 판)
    games_today = [g for g in await db.game_matches_since(start) if guild.get_member(int(g["user_id"]))]
    if games_today:
        names = {"lol": "롤", "val": "발로"}
        record = {}
        for g in games_today:
            r = record.setdefault((g["user_id"], g["game"]), {"win": 0, "lose": 0})
            if g["result"] in r:
                r[g["result"]] += 1
        rank_lines = [f"<@{u}> {names[gm]} {r['win']}승 {r['lose']}패" for (u, gm), r in record.items()]
        wins = [g for g in games_today if g["result"] == "win"]
        if wins:
            mvp = max(wins, key=lambda g: (g["kills"] + g["assists"]) / max(1, g["deaths"]))
            rank_lines.append(f"🏆 MVP: <@{mvp['user_id']}> {names[mvp['game']]} {mvp['character']} "
                              f"{mvp['kills']}/{mvp['deaths']}/{mvp['assists']}")
        worst = max(record.items(), key=lambda x: x[1]["lose"] - x[1]["win"])
        if worst[1]["lose"] - worst[1]["win"] >= 3:
            rank_lines.append(f"😭 오늘의 눈물: <@{worst[0][0]}> {names[worst[0][1]]} {worst[1]['win']}승 {worst[1]['lose']}패")
        embed.add_field(name="🎮 오늘의 랭크", value="\n".join(rank_lines)[:1024], inline=False)

    # 📊 주식 (오늘 0시 이후 첫 가격 → 지금)
    first = await db.first_prices_since(start)
    moves = sorted(
        ((s, (stocks.stock_prices[s]["current"] / p - 1) * 100) for s, p in first.items() if s in stocks.stock_prices and p > 0),
        key=lambda x: x[1],
    )
    if moves:
        up, down = moves[-1], moves[0]
        embed.add_field(name="📊 오늘의 주식",
                        value=f"🚀 {up[0]} **{up[1]:+.1f}%** · 🧊 {down[0]} **{down[1]:+.1f}%**", inline=False)

    # ✅ 미션 · 🍚 기초수급
    habit = []
    cleared = members(await db.mission_clears(today))
    if cleared:
        habit.append("✅ 미션 다 깬 사람: " + ", ".join(f"<@{u}>" for u in cleared))
    streaks = [s for s in await db.welfare_streaks(today - datetime.timedelta(days=1)) if guild.get_member(int(s["user_id"]))][:3]
    if streaks:
        habit.append("🍚 기초수급 연속: " + " · ".join(f"<@{s['user_id']}> {s['welfare_streak']}일" for s in streaks))
    if habit:
        embed.add_field(name="🌱 꾸준한 사람", value="\n".join(habit)[:1024], inline=False)

    embed.set_footer(text="내일도 %머니 기초수급 · %미션 잊지 마세요! · 매일 밤 9시")
    return embed


async def post_due(now=None):
    """보낼 때가 된 서버에 오늘의 미림봇을 보낸다. 보낸 서버 수"""
    now = now or db.now()
    due = datetime.datetime.combine(now.date(), DIGEST_TIME, db.KST)
    if not (due <= now < due + POST_GRACE):
        return 0
    sent = 0
    for guild in client.guilds:
        key = f"digest_last:{guild.id}"
        if await db.get_state(key) == now.date().isoformat():
            continue
        await db.set_state(key, now.date().isoformat())       # 실패해도 오늘은 다시 안 보낸다
        channel = await channel_of(guild)
        if channel is None:
            continue
        try:
            embed = await build(guild, now)
            if embed is not None:
                await channel.send(embed=embed)
                sent += 1
        except Exception as e:
            print(f"[오늘의 미림봇] {guild.id} 실패: {type(e).__name__} {e}")
    await db.prune_brags(now - datetime.timedelta(days=KEEP_DAYS))
    return sent


async def post_loop():
    """setup_hook 에서 한 번 시작한다. 30초마다 보낼 때가 됐는지 본다."""
    await client.wait_until_ready()
    while True:
        try:
            await post_due()
        except Exception as e:
            print(f"[오늘의 미림봇] 확인 실패: {type(e).__name__} {e}")
        await asyncio.sleep(30)


# ───────────── 관리자 명령어 ─────────────

@commands.command(name="소식채널")
@commands.has_permissions(administrator=True)
async def digest_channel(ctx, channel_id: str = None):
    if channel_id is None:
        channel = await channel_of(ctx.guild)
        now = channel.mention if channel else "꺼짐"
        await ctx.send(f"📢 지금 소식 채널: {now}\n사용법: `%관리 소식채널 <채널ID>` · `%관리 소식채널 끄기` (안 정하면 주식 뉴스 채널)")
        return
    if channel_id == "끄기":
        await db.set_state(channel_key(ctx.guild.id), "off")
        await ctx.send("🔕 오늘의 미림봇 · 자랑 알림을 껐어요.")
        return
    cleaned = channel_id.strip("<#>")
    channel = ctx.guild.get_channel(int(cleaned)) if cleaned.isdigit() else None
    if channel is None:
        await ctx.send("❌ 채널을 찾지 못했어요. 채널 ID나 #채널을 써주세요.")
        return
    await db.set_state(channel_key(ctx.guild.id), str(channel.id))
    await ctx.send(f"📢 이제 {channel.mention}에 오늘의 미림봇(매일 밤 9시)과 자랑 알림을 올려요.")


@commands.command(name="소식미리보기")
@commands.has_permissions(administrator=True)
async def digest_preview(ctx):
    embed = await build(ctx.guild)
    if embed is None:
        await ctx.send("📭 오늘은 아직 미림봇을 쓴 사람이 없어요.")
        return
    await ctx.send("👀 미리보기 (밤 9시에 소식 채널로 이렇게 가요)", embed=embed)
