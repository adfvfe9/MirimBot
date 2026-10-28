"""코인 채굴: byte 로 채굴기를 돌려서 비트코인을 캔다

    %채굴 [@유저]               내 채굴기, 해시, 내 몫, 시간당 예상 채굴량, 전기세, 다음 블록 / 반감기
    %채굴기구매                  채굴기 1대 사기 (Lv1, 1인 최대 3대)
    %채굴기업그레이드 [번호]      채굴기 레벨 올리기 (안 쓰면 레벨이 가장 낮은 것)
    %채굴켜기 / %채굴끄기
    %채굴랭킹                   지금까지 캔 코인 순위
    %채굴가속 [블록 수]          (관리자) 블록을 바로 [블록 수] 번 캔다 (전기세도 진짜로 빠진다)

- 1시간마다 블록 하나. 서버 전체 블록 보상(처음 0.1 BTC)을 그때 켜져 있는 채굴기 해시 비율로 나눠 갖는다.
  그래서 몇 명이 채굴하든 서버 전체에서 풀리는 코인은 하루 2.4 BTC 로 고정이다. (사람이 많으면 1인 몫이 준다)
  토큰은 리롤 재료라, 채굴이 토큰을 마구 찍어내지 않게 총량을 묶었다. (퀴즈 토큰과 비슷한 수준)
- 336블록(2주)마다 반감기: 블록 보상이 절반이 된다.
- 블록마다 켜진 채굴기의 전기세(byte)가 빠진다. 돈이 모자라면 그 블록은 못 받고 채굴이 꺼진다.
  업그레이드할수록 해시당 전기세가 싸진다. (Lv1 해시당 2,000 → Lv5 해시당 1,200)
- 코인 액면 조정이 일어나면 블록 보상도 같이 조정된다. (가치는 그대로)
"""
import datetime

import discord
from discord.ext import commands

import database as db
import respond
from bot import client
from features import crypto
from fmt import num

# ───────────── 밸런스 설정 ─────────────
BASE_REWARD = 0.1                 # 블록 하나 보상 (BTC, 처음 액면 기준)
BLOCK_MINUTES = 60
HALVING_BLOCKS = 336              # 2주
MAX_RIGS = 3
MAX_LEVEL = 5
RIG_PRICE = 50_000
UPGRADE_PRICE = {1: 100_000, 2: 200_000, 3: 400_000, 4: 800_000}   # Lv → Lv+1
ACCEL_MAX_BLOCKS = 168


def rig_hash(level):
    return level


def rig_power(level):
    """시간당 전기세 (byte): Lv1 2,000 → Lv5 6,000"""
    return 1000 + 1000 * level


def total_hash(rigs):
    return sum(rig_hash(level) for level in rigs)


def total_power(rigs):
    return sum(rig_power(level) for level in rigs)


# ───────────── 상태 ─────────────
blocks = 0          # 지금까지 지난 블록 수 (반감기 계산)
scale = 1.0         # 액면 조정 배율 (코인 보유량에 곱해진 값)
last_block = None   # 마지막 블록 시각


async def load():
    """봇 시작 때: 블록 수 / 액면 배율 / 마지막 블록 시각을 읽는다."""
    global blocks, scale, last_block
    blocks = int(await db.get_state("mining_blocks") or 0)
    scale = float(await db.get_state("mining_scale") or 1.0)
    saved = await db.get_state("mining_last_block")
    if saved:
        last_block = datetime.datetime.fromisoformat(saved)
    else:
        last_block = db.now()
        await db.set_state("mining_last_block", last_block.isoformat())


async def on_rescale(factor):
    """코인 액면 조정 (crypto.rescale): 가격 ×factor, 보유량 ÷factor 이므로 블록 보상도 ÷factor"""
    global scale
    scale /= factor
    await db.set_state("mining_scale", repr(scale))


def halvings():
    return blocks // HALVING_BLOCKS


def block_reward():
    return BASE_REWARD * scale * 0.5 ** halvings()


def next_block_at():
    return last_block + datetime.timedelta(minutes=BLOCK_MINUTES)


async def maybe_block():
    """1분 루프에서 부른다. 블록 시간이 됐으면 블록을 캔다. (crypto.lock 안에서)"""
    global last_block
    now = db.now()
    if last_block is None or now < next_block_at():
        return
    await block()
    # 봇이 꺼져 있던 동안의 블록은 몰아서 캐지 않는다
    last_block = next_block_at() if now - next_block_at() < datetime.timedelta(minutes=BLOCK_MINUTES) else now
    await db.set_state("mining_last_block", last_block.isoformat())


async def block(live=True):
    """블록 하나: 켜진 채굴기 전기세를 받고, 블록 보상을 해시 비율로 나눈다.
    {"reward", "miners": [(user_id, 받은 코인)], "stopped": [user_id]}"""
    global blocks
    reward = block_reward()
    ids = [m["user_id"] for m in await db.all_miners() if m["running"]]
    paid, stopped, shares = [], [], []
    if ids:
        async with db.user_tx(*ids) as conn:
            # 잠근 뒤에 다시 읽는다 (그 사이에 업그레이드 / 끄기를 했을 수 있다)
            running = [m for m in await db.all_miners(conn) if m["running"] and m["user_id"] in ids]
            for m in running:
                uid, cost = m["user_id"], total_power(m["rigs"])
                money = await db.get_money(uid, conn)
                if money < cost:
                    await db.update_miner(uid, conn, running=False, last_reward=0,
                                          note=f"전기세 {num(cost)} byte가 없어서 꺼졌어요 ({db.now():%m/%d %H:%M})")
                    stopped.append(uid)
                    continue
                await db.update_user(uid, conn, money=money - cost)
                await db.log_money(uid, "mining_power", -cost, f"블록 {blocks + 1}", conn)
                paid.append((m, cost))
            network = sum(total_hash(m["rigs"]) for m, _ in paid)
            for m, cost in paid:
                uid = m["user_id"]
                got = reward * total_hash(m["rigs"]) / network
                holding = await db.get_coin_holding(uid, conn)
                await db.set_coin_holding(uid, holding["amount"] + got, holding["spent"], conn)
                await db.update_miner(uid, conn, mined=m["mined"] + got, power_paid=m["power_paid"] + cost,
                                      last_reward=got, note=None)
                shares.append((uid, got))
    before = halvings()
    blocks += 1
    await db.set_state("mining_blocks", str(blocks))
    if halvings() > before:
        await crypto.announce(
            "⛏️ 비트코인 반감기!",
            f"블록 보상이 절반이 됐어요: 이제 블록마다 **{block_reward():.6f} BTC** (다음 반감기는 {HALVING_BLOCKS}블록 뒤)",
            live,
        )
    return {"reward": reward, "miners": shares, "stopped": stopped}


async def network_hash():
    return sum(total_hash(m["rigs"]) for m in await db.all_miners() if m["running"])


# ───────────── 거래 ─────────────

async def buy_rig(user_id):
    """채굴기 1대 사기. 실패하면 안내(str), 성공하면 채굴기 레벨 목록"""
    async with db.user_tx(user_id) as conn:
        miner = await db.get_miner(user_id, conn)
        if len(miner["rigs"]) >= MAX_RIGS:
            return f"❌ 채굴기는 1인 최대 {MAX_RIGS}대예요. `%채굴기업그레이드`로 레벨을 올려보세요."
        money = await db.get_money(user_id, conn)
        if money < RIG_PRICE:
            return f"💸 돈이 부족해요. 채굴기는 {num(RIG_PRICE)} byte예요. (보유 {num(money)} byte)"
        await db.update_user(user_id, conn, money=money - RIG_PRICE)
        await db.log_money(user_id, "mining_rig", -RIG_PRICE, "채굴기 구매", conn)
        rigs = miner["rigs"] + [1]
        await db.update_miner(user_id, conn, rigs=rigs)
    return rigs


def pick_rig(rigs, number):
    """업그레이드할 채굴기 위치 (0부터). number 가 None 이면 레벨이 가장 낮은 것"""
    if number is None:
        return min(range(len(rigs)), key=lambda i: rigs[i])
    return number - 1


async def upgrade_rig(user_id, number=None):
    """채굴기 레벨 올리기. 실패하면 안내(str), 성공하면 (번호, 새 레벨, 낸 돈)"""
    async with db.user_tx(user_id) as conn:
        miner = await db.get_miner(user_id, conn)
        rigs = miner["rigs"]
        if not rigs:
            return "❌ 채굴기가 없어요. `%채굴기구매`로 먼저 사주세요."
        if number is not None and not 1 <= number <= len(rigs):
            return f"❌ 채굴기 번호는 1~{len(rigs)} 이에요."
        i = pick_rig(rigs, number)
        level = rigs[i]
        if level >= MAX_LEVEL:
            return f"❌ {i + 1}번 채굴기는 이미 최고 레벨(Lv{MAX_LEVEL})이에요."
        cost = UPGRADE_PRICE[level]
        money = await db.get_money(user_id, conn)
        if money < cost:
            return f"💸 돈이 부족해요. Lv{level} → Lv{level + 1} 은 {num(cost)} byte예요. (보유 {num(money)} byte)"
        await db.update_user(user_id, conn, money=money - cost)
        await db.log_money(user_id, "mining_rig", -cost, f"채굴기 {i + 1}번 Lv{level + 1}", conn)
        rigs = rigs[:i] + [level + 1] + rigs[i + 1:]
        await db.update_miner(user_id, conn, rigs=rigs)
    return i + 1, level + 1, cost


async def set_running(user_id, on):
    """켜기 / 끄기. 실패하면 안내(str), 성공하면 None"""
    async with db.user_tx(user_id) as conn:
        miner = await db.get_miner(user_id, conn)
        if not miner["rigs"]:
            return "❌ 채굴기가 없어요. `%채굴기구매`로 먼저 사주세요."
        if miner["running"] == on:
            return "⛏️ 이미 켜져 있어요." if on else "⛏️ 이미 꺼져 있어요."
        await db.update_miner(user_id, conn, running=on, note=None)
    return None


# ───────────── 명령어 ─────────────

def rigs_text(rigs):
    return "\n".join(
        f"`{i}번` Lv{level} · 해시 {rig_hash(level)} · 전기세 {num(rig_power(level))}/시간"
        for i, level in enumerate(rigs, start=1)
    )


@client.command(aliases=["채굴"])
async def mining_status(ctx, member: discord.Member = None):
    member = member or ctx.author
    miner = await db.get_miner(member.id)
    network = await network_hash()
    reward = block_reward()
    next_halving = (halvings() + 1) * HALVING_BLOCKS - blocks

    embed = discord.Embed(title=f"⛏️ {member.display_name}님의 코인 채굴", color=discord.Color.dark_gold())
    if not miner["rigs"]:
        embed.description = f"채굴기가 없어요. `%채굴기구매`로 시작해보세요! (1대 {num(RIG_PRICE)} byte)"
    else:
        mine = total_hash(miner["rigs"])
        # 꺼져 있으면 "지금 켜면" 기준으로 보여준다
        share = mine / (network if miner["running"] else network + mine)
        per_hour = reward * share
        status = "🟢 켜짐" if miner["running"] else "🔴 꺼짐"
        if miner["note"]:
            status += f"\n⚠️ {miner['note']}"
        embed.add_field(name="상태", value=status, inline=False)
        embed.add_field(name=f"채굴기 ({len(miner['rigs'])}/{MAX_RIGS})", value=rigs_text(miner["rigs"]), inline=False)
        embed.add_field(name="내 해시", value=f"{mine} / 전체 {network if miner['running'] else network + mine}", inline=True)
        embed.add_field(name="내 몫", value=f"{num(share * 100)}%", inline=True)
        embed.add_field(name="전기세", value=f"{num(total_power(miner['rigs']))} byte/시간", inline=True)
        embed.add_field(
            name="시간당 예상" + ("" if miner["running"] else " (켜면)"),
            value=f"{per_hour:.6f} BTC ≈ {num(per_hour * crypto.price)} 토큰",
            inline=True,
        )
        embed.add_field(name="마지막 블록", value=f"{miner['last_reward']:.6f} BTC", inline=True)
        embed.add_field(
            name="누적",
            value=f"{miner['mined']:.6f} BTC 캠 · 전기세 {num(miner['power_paid'])} byte",
            inline=True,
        )
    embed.add_field(
        name="⛓️ 블록",
        value=(
            f"다음 블록 <t:{int(next_block_at().timestamp())}:R> · 블록 보상 **{reward:.6f} BTC** (≈ {num(reward * crypto.price)} 토큰)\n"
            f"반감기까지 {next_halving}블록 (약 {num(next_halving / 24)}일) · 지금 켜진 전체 해시 {network}"
        ),
        inline=False,
    )
    embed.set_footer(text="%채굴기구매 · %채굴기업그레이드 [번호] · %채굴켜기 · %채굴끄기 · %채굴랭킹")
    await ctx.send(embed=embed)


@client.command(aliases=["채굴기구매"])
async def mining_buy(ctx):
    miner = await db.get_miner(ctx.author.id)
    if len(miner["rigs"]) >= MAX_RIGS:
        await ctx.send(f"❌ 채굴기는 1인 최대 {MAX_RIGS}대예요. `%채굴기업그레이드`로 레벨을 올려보세요.")
        return
    embed = discord.Embed(
        title="⛏️ 채굴기 구매 확인",
        description=(
            f"**{num(RIG_PRICE)} byte**로 채굴기(Lv1, 해시 1)를 사요. "
            f"켜 두면 1시간마다 전기세 {num(rig_power(1))} byte가 빠져요.\n"
            f"지금 {len(miner['rigs'])}/{MAX_RIGS}대"
        ),
        color=discord.Color.dark_gold(),
    )

    async def on_confirm(interaction):
        r = await buy_rig(ctx.author.id)
        if isinstance(r, str):
            await respond.edit(interaction, embed=discord.Embed(description=r, color=discord.Color.red()), view=None)
            return
        tip = "" if miner["running"] else "\n`%채굴켜기`로 채굴을 시작하세요!"
        await respond.edit(interaction, embed=discord.Embed(
            title="✅ 채굴기 구매 완료",
            description=f"이제 채굴기 {len(r)}대, 해시 {total_hash(r)} · 전기세 {num(total_power(r))} byte/시간{tip}",
            color=discord.Color.green(),
        ), view=None)

    await ctx.send(embed=embed, view=crypto.confirm_view(ctx.author.id, on_confirm))


@client.command(aliases=["채굴기업그레이드", "채굴기강화"])
async def mining_upgrade(ctx, number: int = None):
    rigs = (await db.get_miner(ctx.author.id))["rigs"]
    if not rigs:
        await ctx.send("❌ 채굴기가 없어요. `%채굴기구매`로 먼저 사주세요.")
        return
    if number is not None and not 1 <= number <= len(rigs):
        await ctx.send(f"❌ 채굴기 번호는 1~{len(rigs)} 이에요.")
        return
    i = pick_rig(rigs, number)
    level = rigs[i]
    if level >= MAX_LEVEL:
        await ctx.send(f"❌ {i + 1}번 채굴기는 이미 최고 레벨(Lv{MAX_LEVEL})이에요.")
        return
    embed = discord.Embed(
        title="⛏️ 채굴기 업그레이드 확인",
        description=(
            f"`{i + 1}번` 채굴기 **Lv{level} → Lv{level + 1}**: **{num(UPGRADE_PRICE[level])} byte**\n"
            f"해시 {rig_hash(level)} → {rig_hash(level + 1)} · 전기세 {num(rig_power(level))} → {num(rig_power(level + 1))} byte/시간"
        ),
        color=discord.Color.dark_gold(),
    )

    async def on_confirm(interaction):
        r = await upgrade_rig(ctx.author.id, i + 1)
        if isinstance(r, str):
            await respond.edit(interaction, embed=discord.Embed(description=r, color=discord.Color.red()), view=None)
            return
        n, new_level, cost = r
        await respond.edit(interaction, embed=discord.Embed(
            title="✅ 채굴기 업그레이드 완료",
            description=f"`{n}번` 채굴기가 **Lv{new_level}**이 됐어요! (해시 {rig_hash(new_level)})",
            color=discord.Color.green(),
        ), view=None)

    await ctx.send(embed=embed, view=crypto.confirm_view(ctx.author.id, on_confirm))


@client.command(aliases=["채굴켜기"])
async def mining_on(ctx):
    r = await set_running(ctx.author.id, True)
    if r:
        await ctx.send(r)
        return
    rigs = (await db.get_miner(ctx.author.id))["rigs"]
    await ctx.send(
        f"🟢 채굴을 켰어요! 다음 블록 <t:{int(next_block_at().timestamp())}:R>부터 "
        f"블록마다 전기세 {num(total_power(rigs))} byte가 빠져요."
    )


@client.command(aliases=["채굴끄기"])
async def mining_off(ctx):
    r = await set_running(ctx.author.id, False)
    await ctx.send(r or "🔴 채굴을 껐어요. 전기세도 더 안 빠져요.")


@client.command(aliases=["채굴랭킹"])
async def mining_rank(ctx):
    rows = sorted(await db.all_miners(), key=lambda m: -m["mined"])[:10]
    if not rows:
        await ctx.send("❌ 아직 채굴기를 가진 사람이 없어요.")
        return
    embed = discord.Embed(title="⛏️ 채굴 랭킹 TOP 10", description="지금까지 캔 코인 기준", color=discord.Color.dark_gold())
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, m in enumerate(rows, start=1):
        member = ctx.guild.get_member(m["user_id"]) if ctx.guild else None
        name = member.display_name if member else f"알 수 없음 ({m['user_id']})"
        embed.add_field(
            name=f"{medals.get(i, f'{i}위')} {name} {'🟢' if m['running'] else '🔴'}",
            value=f"{m['mined']:.6f} BTC · 해시 {total_hash(m['rigs'])} · 전기세 누적 {num(m['power_paid'])} byte",
            inline=False,
        )
    await ctx.send(embed=embed)


@client.command(aliases=["채굴가속"])
@commands.has_permissions(administrator=True)
async def mining_accelerate(ctx, count: int = 1):
    """블록을 바로 count 번 캔다. 전기세도 진짜로 빠지고, 다음 블록 시각은 그대로다."""
    respond.delete_soon(ctx.message)
    if not 1 <= count <= ACCEL_MAX_BLOCKS:
        await ctx.send(f"❌ 1~{ACCEL_MAX_BLOCKS}블록 사이로 입력해주세요.")
        return
    total, stopped = {}, set()
    async with crypto.lock:
        for _ in range(count):
            r = await block(live=False)
            for uid, got in r["miners"]:
                total[uid] = total.get(uid, 0) + got
            stopped.update(r["stopped"])
    lines = []
    for uid, got in sorted(total.items(), key=lambda kv: -kv[1])[:10]:
        member = ctx.guild.get_member(uid) if ctx.guild else None
        lines.append(f"{member.display_name if member else uid}: {got:.6f} BTC")
    embed = discord.Embed(
        title=f"⏩ 채굴 {count}블록 가속 완료",
        description=f"지금까지 {blocks}블록 · 블록 보상 {block_reward():.6f} BTC (반감기 {halvings()}번)",
        color=discord.Color.dark_gold(),
    )
    embed.add_field(name="받은 코인", value="\n".join(lines) or "켜진 채굴기가 없었어요", inline=False)
    if stopped:
        embed.add_field(name="전기세 부족으로 꺼짐", value=", ".join(str(u) for u in stopped), inline=False)
    await ctx.send(embed=embed)
