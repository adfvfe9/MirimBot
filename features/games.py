"""롤 · 발로란트 연동: 친구 랭크 경기 알림 + 다음 판에 byte 걸기

    %롤등록 <닉네임#태그>          내 롤 계정 등록 (본인 것만)
    %발로등록 <닉네임#태그>        내 발로란트 계정 등록
    %게임등록해제 <롤 | 발로>
    %전적 [@유저 | 닉네임#태그] [롤 | 발로]   최근 10판 (일반 · 칼바람 등 전부, 등록 안 한 계정도)
    %베팅 @친구 [롤 | 발로] <승 | 패> <금액>   친구 다음 랭크 판에 걸기
    %베팅목록                     지금 걸려 있는 판돈

- 랭크 게임만 본다: 롤 솔로랭크(420) · 자유랭크(440), 발로란트 경쟁전.
- POLL_SECONDS 마다 등록한 사람의 최근 랭크 경기를 확인해서, 새로 끝난 판을 소식 채널(digest.py)에 알린다.
  등록할 때의 마지막 경기는 알리지 않는다. (등록 전 경기가 한꺼번에 뜨지 않게)
- 롤은 라이엇 공식 API (RIOT_API_KEY, 개인용 키), 발로란트는 공식 API 를 개인 키로 못 써서 비공식 HenrikDev API (HENRIK_API_KEY).
  챔피언 · 요원 · 맵 이름은 한국어 (Data Dragon / valorant-api.com) 로 바꿔 보여준다.
- %전적은 알림과 달리 모든 큐를 API 에서 바로 가져온다. (같은 사람은 RECORD_CACHE 초 동안 저장해 둔 걸 쓴다)
베팅 (판돈 나누기)
- 걸 때 돈이 빠진다. 건 뒤에 '시작한' 친구의 다음 랭크 판으로 정산한다. (이미 하고 있는 판에 결과를 보고 거는 것을 막는다)
- 자기 판에는 못 건다. (일부러 지는 것을 막는다) 한 친구 · 한 게임에 한 사람당 하나만.
- 정산: 그 판에 걸린 돈을 다 모아서 맞힌 사람들이 건 비율대로 나눠 갖는다. BET_FEE 는 사라진다.
  한쪽에만 걸렸거나, 다시하기(롤 조기 항복) · 무승부(발로)면 전부 돌려준다. BET_EXPIRE 안에 판이 없으면 돌려준다.
"""
import asyncio
import datetime
import os
import re
import time
from urllib.parse import quote

import discord
import requests

import database as db
from bot import client
from features import digest
from fmt import num

POLL_SECONDS = 180
TIMEOUT = 10
BET_MIN = 100
BET_MAX = 100_000
BET_FEE = 0.05
BET_EXPIRE = datetime.timedelta(hours=24)
RECORD_COUNT = 10           # %전적: 게임마다 최근 몇 판
RECORD_CACHE = 60           # %전적: 같은 계정을 다시 보면 이 초 동안은 저장해 둔 결과

GAMES = {"lol": "롤", "val": "발로"}
GAME_WORDS = {"롤": "lol", "lol": "lol", "리그오브레전드": "lol", "발로": "val", "발로란트": "val", "val": "val", "valorant": "val"}
SIDE_WORDS = {"승": "win", "이김": "win", "win": "win", "패": "lose", "짐": "lose", "lose": "lose"}
LOL_QUEUES = {420: "솔랭", 440: "자랭"}       # 알림 · 베팅은 이것만
LOL_QUEUE_NAMES = {
    **LOL_QUEUES, 400: "일반", 430: "일반", 480: "신속 대전", 490: "빠른 대전", 450: "칼바람", 720: "칼바람 격전",
    700: "격전", 900: "우르프", 1010: "우르프", 1900: "우르프", 1020: "단일 챔피언", 1300: "돌격 넥서스",
    1700: "아레나", 1710: "아레나", 1740: "아레나", 0: "사용자 설정",
    **dict.fromkeys((830, 840, 850, 870, 880, 890), "AI 대전"),
}
LOL_MODE_NAMES = {"CLASSIC": "일반", "ARAM": "칼바람", "CHERRY": "아레나", "URF": "우르프"}   # 위에 없는 큐
VAL_QUEUES = {
    "competitive": "경쟁전", "unrated": "일반", "swiftplay": "신속플레이", "spikerush": "스파이크 돌격",
    "deathmatch": "데스매치", "hurm": "팀 데스매치", "ggteam": "단계별 대결전", "premier": "프리미어",
    "newmap": "새 맵", "snowball": "눈싸움 대전", "": "사용자 설정",
}
RESULT_TEXT = {"win": "승리", "lose": "패배", "draw": "무승부", "remake": "다시하기"}

RIOT = "https://asia.api.riotgames.com"
HENRIK = "https://api.henrikdev.xyz"


class ApiError(Exception):
    pass


# ───────────── API (요청은 다른 스레드에서, 봇이 멈추지 않게) ─────────────

def _get(url, headers, params=None):
    r = requests.get(url, headers=headers, params=params, timeout=TIMEOUT)
    if r.status_code == 404:
        return None
    if r.status_code == 429:
        raise ApiError("요청이 너무 많아요. 잠시 뒤에 다시 해주세요.")
    if r.status_code in (401, 403):
        raise ApiError("API 키가 없거나 만료됐어요. (관리자: .env 확인)")
    r.raise_for_status()
    return r.json()


async def get(url, headers, params=None):
    try:
        return await asyncio.to_thread(_get, url, headers, params)
    except requests.RequestException as e:
        raise ApiError(f"서버에 연결하지 못했어요 ({type(e).__name__})") from e


def riot_headers():
    return {"X-Riot-Token": (os.getenv("RIOT_API_KEY") or "").strip()}


def henrik_headers():
    return {"Authorization": (os.getenv("HENRIK_API_KEY") or "").strip()}


def split_riot_id(text):
    """'Hide on bush#KR1' → ('Hide on bush', 'KR1'). 형식이 틀리면 None"""
    if not text or "#" not in text:
        return None
    name, _, tag = text.strip().rpartition("#")
    name, tag = name.strip(), tag.strip()
    return (name, tag) if name and tag else None


# 한국어 이름 (하루에 한 번 새로 받는다)
_names = {"at": 0, "champ": {}, "agent": {}, "map": {}}


async def load_names():
    if time.monotonic() - _names["at"] < 24 * 3600 and _names["champ"]:
        return
    try:
        version = (await get("https://ddragon.leagueoflegends.com/api/versions.json", {}))[0]
        data = await get(f"https://ddragon.leagueoflegends.com/cdn/{version}/data/ko_KR/champion.json", {})
        _names["champ"] = {k: v["name"] for k, v in data["data"].items()}
        agents = await get("https://valorant-api.com/v1/agents", {}, {"language": "ko-KR", "isPlayableCharacter": "true"})
        _names["agent"] = {a["uuid"]: a["displayName"] for a in agents["data"]}
        maps = await get("https://valorant-api.com/v1/maps", {}, {"language": "ko-KR"})
        _names["map"] = {m["uuid"]: m["displayName"] for m in maps["data"]}
        _names["at"] = time.monotonic()
    except (ApiError, KeyError, TypeError) as e:
        print(f"[게임] 한국어 이름 받기 실패: {e}")


# ── 롤 ──

async def lol_lookup(name, tag):
    acc = await get(f"{RIOT}/riot/account/v1/accounts/by-riot-id/{quote(name)}/{quote(tag)}", riot_headers())
    if acc is None:
        return None
    return {"puuid": acc["puuid"], "riot_id": f"{acc['gameName']}#{acc['tagLine']}", "region": None}


async def lol_match_ids(puuid, count=5, ranked=True):
    params = {"count": count, **({"type": "ranked"} if ranked else {})}
    return await get(f"{RIOT}/lol/match/v5/matches/by-puuid/{puuid}/ids", riot_headers(), params) or []


_lol_matches = {}       # match_id → (랭크인지, 참가자별 결과). 끝난 경기는 안 바뀌니 기억해 둔다


async def lol_match(match_id, ranked_only=True):
    """참가자별 결과 {puuid: 결과 dict} (ranked_only 인데 랭크가 아니면 None)"""
    if match_id not in _lol_matches:
        m = await get(f"{RIOT}/lol/match/v5/matches/{match_id}", riot_headers())
        if m is None:
            return None
        info = m["info"]
        queue = LOL_QUEUE_NAMES.get(info["queueId"]) or LOL_MODE_NAMES.get(info["gameMode"], info["gameMode"])
        started = datetime.datetime.fromtimestamp(info["gameStartTimestamp"] / 1000, datetime.timezone.utc)
        result = {}
        for p in info["participants"]:
            detail = f"{info['gameDuration'] // 60}분"
            if p.get("placement"):          # 아레나: 4등까지 승리
                won, detail = p["placement"] <= 4, f"{p['placement']}등 · {detail}"
            else:
                won = p["win"]
            result[p["puuid"]] = {
                "game": "lol", "match_id": match_id, "started_at": started, "queue": queue,
                "result": "remake" if p.get("gameEndedInEarlySurrender") else ("win" if won else "lose"),
                "character": _names["champ"].get(p["championName"], p["championName"]),
                "kills": p["kills"], "deaths": p["deaths"], "assists": p["assists"], "detail": detail,
            }
        ranked = info["queueId"] in LOL_QUEUES
        if _names["champ"]:         # 한국어 이름을 못 받았을 땐 기억하지 않는다 (영어 이름이 남지 않게)
            if len(_lol_matches) >= 500:
                _lol_matches.pop(next(iter(_lol_matches)))
            _lol_matches[match_id] = (ranked, result)
    else:
        ranked, result = _lol_matches[match_id]
    return None if ranked_only and not ranked else result


# ── 발로란트 (HenrikDev) ──

async def val_lookup(name, tag):
    acc = await get(f"{HENRIK}/valorant/v2/account/{quote(name)}/{quote(tag)}", henrik_headers())
    if acc is None or "data" not in acc:
        return None
    d = acc["data"]
    return {"puuid": d["puuid"], "riot_id": f"{d['name']}#{d['tag']}", "region": d.get("region") or "kr"}


async def val_matches(region, puuid, size=1, mode="competitive"):
    """최근 경기 [{match_id, started_at, players: {puuid: 결과}}] (최근 것부터, mode=None 이면 모든 모드)"""
    data = await get(f"{HENRIK}/valorant/v4/by-puuid/matches/{region}/pc/{puuid}", henrik_headers(),
                     {"size": size, **({"mode": mode} if mode else {})})
    out = []
    for m in (data or {}).get("data") or []:
        meta = m["metadata"]
        if not meta.get("is_completed", True):
            continue
        won = {t["team_id"]: t["won"] for t in m["teams"]}
        rounds = {t["team_id"]: t["rounds"] for t in m["teams"]}
        started = datetime.datetime.fromisoformat(meta["started_at"].replace("Z", "+00:00"))
        map_name = _names["map"].get(meta["map"]["id"], meta["map"]["name"])
        q = meta.get("queue") or {}
        queue = VAL_QUEUES.get(q.get("id"), q.get("name") or "?")
        players = {}
        for p in m["players"]:
            team = p["team_id"]
            outcome = "draw" if not any(won.values()) else ("win" if won.get(team) else "lose")
            r = rounds.get(team) or {}
            score = "" if q.get("mode_type") == "Deathmatch" else f" {r.get('won', '?')}:{r.get('lost', '?')}"   # 데스매치는 라운드가 킬 수
            players[p["puuid"]] = {
                "game": "val", "match_id": meta["match_id"], "started_at": started, "queue": queue,
                "result": outcome, "character": _names["agent"].get(p["agent"]["id"], p["agent"]["name"]),
                "kills": p["stats"]["kills"], "deaths": p["stats"]["deaths"], "assists": p["stats"]["assists"],
                "detail": map_name + score,
            }
        out.append({"match_id": meta["match_id"], "started_at": started, "players": players})
    return out


async def lookup(game, name, tag):
    return await (lol_lookup if game == "lol" else val_lookup)(name, tag)


async def latest_match_id(game, acc):
    if game == "lol":
        ids = await lol_match_ids(acc["puuid"], 1)
        return ids[0] if ids else None
    ms = await val_matches(acc["region"], acc["puuid"], 1)
    return ms[0]["match_id"] if ms else None


_recent = {}        # (game, puuid) → (시각, 결과 목록)


async def recent_matches(game, acc):
    """%전적: 모든 큐의 최근 RECORD_COUNT 판 (최근 것부터)"""
    key = (game, acc["puuid"])
    hit = _recent.get(key)
    if hit and time.monotonic() - hit[0] < RECORD_CACHE:
        return hit[1]
    if game == "lol":
        ids = await lol_match_ids(acc["puuid"], RECORD_COUNT, ranked=False)
        parts = await asyncio.gather(*(lol_match(i, ranked_only=False) for i in ids))
        out = [p[acc["puuid"]] for p in parts if p and acc["puuid"] in p]
    else:
        ms = await val_matches(acc["region"], acc["puuid"], RECORD_COUNT, mode=None)
        out = [m["players"][acc["puuid"]] for m in ms if acc["puuid"] in m["players"]]
    _recent[key] = (time.monotonic(), out)
    return out


# ───────────── 베팅 정산 ─────────────

async def settle(target_id, game, match):
    """이 친구의 이번 판으로 걸린 돈을 정산한다. 결과 줄 목록"""
    bets = [b for b in await db.open_bets(target_id, game) if b["created_at"] < match["started_at"]]
    if not bets:
        return []
    total = sum(b["amount"] for b in bets)
    winners = [b for b in bets if b["side"] == match["result"]]
    win_total = sum(b["amount"] for b in winners)
    refund = match["result"] in ("draw", "remake") or win_total == 0 or win_total == total
    lines = []
    for b in bets:
        if refund:
            payout, status, source = b["amount"], "refunded", "bet_refund"
        elif b["side"] == match["result"]:
            payout, status, source = b["amount"] / win_total * total * (1 - BET_FEE), "settled", "bet_win"
        else:
            payout, status, source = 0.0, "settled", None
        async with db.user_tx(b["bettor_id"]) as conn:
            if not await db.close_bet(b["id"], status, match["match_id"], payout, conn):
                continue        # 이미 정산됐다
            if payout > 0:
                await db.receive(b["bettor_id"], payout, conn)
                await db.log_money(b["bettor_id"], source, payout, f"{GAMES[game]} 베팅 #{b['id']}", conn)
        side = "승" if b["side"] == "win" else "패"
        if refund:
            lines.append(f"<@{b['bettor_id']}> ({side}) {num(b['amount'])} 돌려받음")
        elif payout > 0:
            lines.append(f"<@{b['bettor_id']}> ({side}) **+{num(round(payout - b['amount']))}**")
        else:
            lines.append(f"<@{b['bettor_id']}> ({side}) -{num(b['amount'])}")
    if refund and match["result"] not in ("draw", "remake"):
        lines.insert(0, "한쪽에만 걸려서 모두 돌려줬어요")
    return lines


async def expire_bets(now=None):
    """BET_EXPIRE 안에 판이 없었던 베팅을 돌려준다"""
    now = now or db.now()
    for b in await db.open_bets():
        if now - b["created_at"] < BET_EXPIRE:
            continue
        async with db.user_tx(b["bettor_id"]) as conn:
            if await db.close_bet(b["id"], "refunded", None, b["amount"], conn):
                await db.receive(b["bettor_id"], b["amount"], conn)
                await db.log_money(b["bettor_id"], "bet_refund", b["amount"], f"{GAMES[b['game']]} 베팅 #{b['id']} 만료", conn)


# ───────────── 알림 ─────────────

def match_embed(user_id, m, bet_lines):
    color = {"win": 0x2ecc71, "lose": 0xe74c3c}.get(m["result"], 0x95a5a6)
    kda = f"{m['kills']}/{m['deaths']}/{m['assists']}"
    embed = discord.Embed(
        description=f"🎮 <@{user_id}> **{GAMES[m['game']]} {m['queue']} {RESULT_TEXT[m['result']]}** · {m['character']} {kda} · {m['detail']}",
        color=color,
    )
    if bet_lines:
        embed.add_field(name="🎲 베팅 결과", value="\n".join(bet_lines)[:1024], inline=False)
    return embed


async def announce(user_id, m, bet_lines):
    for guild in client.guilds:
        if guild.get_member(int(user_id)) is None:
            continue
        channel = await digest.channel_of(guild)
        if channel is None:
            continue
        try:
            await channel.send(embed=match_embed(user_id, m, bet_lines))
        except discord.HTTPException as e:
            print(f"[게임] 알림 실패: {e}")


async def process(acc, m):
    """새로 끝난 랭크 판 하나: 기록 → 정산 → 알림"""
    m = {**m, "user_id": acc["user_id"]}
    if not await db.add_game_match(m):
        return
    lines = await settle(acc["user_id"], acc["game"], m)
    await announce(acc["user_id"], m, lines)


async def check_account(acc):
    """이 계정의 새 랭크 판을 처리한다"""
    last = acc["last_match_id"]
    if acc["game"] == "lol":
        ids = await lol_match_ids(acc["puuid"], 5)
        if not ids or ids[0] == last:
            return
        new = ids[:ids.index(last)] if last in ids else ids[:1]
        for match_id in reversed(new):          # 오래된 판부터
            parts = await lol_match(match_id)
            if parts and acc["puuid"] in parts:
                await process(acc, parts[acc["puuid"]])
        await db.set_last_match(acc["user_id"], "lol", ids[0])
    else:
        recent = await val_matches(acc["region"], acc["puuid"], 1)
        if not recent or recent[0]["match_id"] == last:
            return
        matches = await val_matches(acc["region"], acc["puuid"], 5)
        ids = [x["match_id"] for x in matches]
        new = matches[:ids.index(last)] if last in ids else matches[:1]
        for match in reversed(new):
            if acc["puuid"] in match["players"]:
                await process(acc, match["players"][acc["puuid"]])
        await db.set_last_match(acc["user_id"], "val", matches[0]["match_id"])


async def poll_once():
    await load_names()
    for acc in await db.game_accounts():
        try:
            await check_account(acc)
        except ApiError as e:
            print(f"[게임] {acc['riot_id']} 확인 실패: {e}")
            if "많아요" in str(e):
                break           # 요청 한도에 걸리면 이번 바퀴는 쉰다
        except Exception as e:
            print(f"[게임] {acc['riot_id']} 확인 실패: {type(e).__name__} {e}")
    await expire_bets()


async def loop():
    """setup_hook 에서 한 번 시작한다."""
    await client.wait_until_ready()
    while True:
        try:
            await poll_once()
        except Exception as e:
            print(f"[게임] 확인 실패: {type(e).__name__} {e}")
        await asyncio.sleep(POLL_SECONDS)


# ───────────── 명령어 ─────────────

async def register(ctx, game, riot_id):
    parsed = split_riot_id(riot_id)
    if parsed is None:
        await ctx.send(f"사용법: `%{GAMES[game]}등록 닉네임#태그` 예) `%{GAMES[game]}등록 Hide on bush#KR1`")
        return
    try:
        async with ctx.typing():
            acc = await lookup(game, *parsed)
            if acc is None:
                await ctx.send(f"❌ `{riot_id}` 계정을 찾지 못했어요. 닉네임과 태그(#뒤)를 확인해주세요.")
                return
            other = await db.game_account_by_puuid(game, acc["puuid"])
            if other and other["user_id"] != ctx.author.id:
                await ctx.send(f"❌ 이미 <@{other['user_id']}>님이 등록한 계정이에요. 본인 계정이 맞다면 관리자에게 알려주세요.")
                return
            last = await latest_match_id(game, acc)
    except ApiError as e:
        await ctx.send(f"🥲 {e}")
        return
    await db.set_game_account(ctx.author.id, game, acc["puuid"], acc["riot_id"], acc["region"], last)
    await ctx.send(
        f"🎮 **{GAMES[game]}** 계정 **{acc['riot_id']}** 등록 완료! 이제 랭크 게임이 끝나면 소식 채널에 결과가 떠요.\n"
        f"친구들이 내 다음 판에 `%베팅`할 수 있어요. 그만하려면 `%게임등록해제 {GAMES[game]}`"
    )


@client.command(aliases=["롤등록"])
async def lol_register(ctx, *, riot_id: str = None):
    await register(ctx, "lol", riot_id)


@client.command(aliases=["발로등록", "발로란트등록"])
async def val_register(ctx, *, riot_id: str = None):
    await register(ctx, "val", riot_id)


@client.command(aliases=["게임등록해제"])
async def game_unregister(ctx, game_word: str = None):
    game = GAME_WORDS.get((game_word or "").lower())
    if game is None:
        await ctx.send("사용법: `%게임등록해제 <롤 | 발로>`")
        return
    if await db.delete_game_account(ctx.author.id, game):
        await ctx.send(f"🗑️ {GAMES[game]} 계정 등록을 해제했어요.")
    else:
        await ctx.send(f"❌ {GAMES[game]} 계정이 등록돼 있지 않아요.")


def record_field(game, matches):
    """%전적 한 게임 칸: (제목, 내용)"""
    icon = {"win": "🟦", "lose": "🟥", "draw": "⬜", "remake": "⬜"}
    wins = sum(m["result"] == "win" for m in matches)
    losses = sum(m["result"] == "lose" for m in matches)
    k, d, a = (sum(m[s] for m in matches) for s in ("kills", "deaths", "assists"))
    title = f"{GAMES[game]} 최근 {len(matches)}판 · {wins}승 {losses}패 · KDA {(k + a) / max(d, 1):.2f}"
    counts = {}
    for m in matches:
        counts[m["character"]] = counts.get(m["character"], 0) + 1
    most = " · ".join(f"{c} {n}" for c, n in sorted(counts.items(), key=lambda x: -x[1])[:3])
    footer = f"-# 많이 한 {'챔피언' if game == 'lol' else '요원'}: {most}"
    lines = []
    for m in matches:
        line = (f"{icon[m['result']]} `{m['started_at'].astimezone(db.KST):%m/%d %H:%M}` {m['queue']} "
                f"**{RESULT_TEXT[m['result']]}** · {m['character']} {m['kills']}/{m['deaths']}/{m['assists']} · {m['detail']}")
        if sum(len(x) + 1 for x in lines) + len(line) + len(footer) + 1 > 1024:
            break
        lines.append(line)
    return title, "\n".join(lines + [footer])


@client.command(aliases=["전적", "최근전적"])
async def game_record(ctx, *, query: str = None):
    usage = "사용법: `%전적 [@유저 | 닉네임#태그] [롤 | 발로]` 예) `%전적` `%전적 @철수 롤` `%전적 Hide on bush#KR1`"
    words = (query or "").split()
    game = None
    for i in (-1, 0):           # 게임은 앞이나 뒤에
        if words and words[i].lower() in GAME_WORDS:
            game = GAME_WORDS[words.pop(i).lower()]
            break
    rest = " ".join(words)
    mention = re.fullmatch(r"<@!?(\d+)>", rest)
    wanted = [game] if game else list(GAMES)
    accounts = []
    try:
        async with ctx.typing():
            await load_names()
            if not rest or mention:
                member = ctx.guild.get_member(int(mention[1])) if mention and ctx.guild else (None if mention else ctx.author)
                if member is None:
                    await ctx.send("❌ 그 사람을 이 서버에서 찾지 못했어요.")
                    return
                title = f"🎮 {member.display_name}님의 최근 전적"
                accounts = [a for a in await db.game_accounts() if a["user_id"] == member.id and a["game"] in wanted]
                if not accounts:
                    which = GAMES[game] if game else "롤 · 발로"
                    await ctx.send(f"❌ {member.display_name}님은 {which} 계정을 등록하지 않았어요. "
                                   f"`%전적 닉네임#태그`로 등록 없이도 볼 수 있어요.")
                    return
            elif (parsed := split_riot_id(rest)) is not None:
                for g in wanted:
                    acc = await lookup(g, *parsed)
                    if acc:
                        accounts.append({**acc, "game": g})
                if not accounts:
                    await ctx.send(f"❌ `{rest}` 계정을 찾지 못했어요. 닉네임과 태그(#뒤)를 확인해주세요.")
                    return
                title = f"🎮 {accounts[0]['riot_id']} 최근 전적"
            else:
                await ctx.send(usage)
                return
            results = []
            for acc in accounts:
                try:
                    results.append((acc, await recent_matches(acc["game"], acc), None))
                except ApiError as e:
                    results.append((acc, [], e))
    except ApiError as e:
        await ctx.send(f"🥲 {e}")
        return
    embed = discord.Embed(title=title, color=0x5865f2,
                          description=" · ".join(f"{GAMES[a['game']]} **{a['riot_id']}**" for a in accounts))
    for acc, matches, error in results:
        if error:
            embed.add_field(name=GAMES[acc["game"]], value=f"🥲 {error}", inline=False)
        elif matches:
            name, value = record_field(acc["game"], matches)
            embed.add_field(name=name, value=value, inline=False)
        elif game or not rest or mention:      # 고른 게임 / 등록한 게임인데 판이 없음 (닉네임으로 둘 다 볼 땐 안 한 게임은 숨김)
            embed.add_field(name=GAMES[acc["game"]], value="최근 경기가 없어요.", inline=False)
    if not embed.fields:
        embed.add_field(name="최근 경기", value="최근 경기가 없어요.", inline=False)
    embed.set_footer(text="알림 · 베팅은 랭크 게임만 · 일반 · 칼바람 등은 전적에만 나와요")
    await ctx.send(embed=embed)


@client.command(aliases=["베팅"])
async def game_bet(ctx, member: discord.Member = None, *args: str):
    usage = "사용법: `%베팅 @친구 [롤 | 발로] <승 | 패> <금액>` 예) `%베팅 @철수 롤 패 5000`"
    if ctx.guild is None or member is None:
        await ctx.send(usage)
        return
    game = side = amount = None
    for a in args:
        if a.lower() in GAME_WORDS:
            game = GAME_WORDS[a.lower()]
        elif a in SIDE_WORDS:
            side = SIDE_WORDS[a]
        elif a.replace(",", "").isdigit():
            amount = int(a.replace(",", ""))
    accounts = [a for a in await db.game_accounts() if a["user_id"] == member.id]
    if game is None and len(accounts) == 1:
        game = accounts[0]["game"]
    if side is None or amount is None or game is None:
        await ctx.send(usage + ("\n(친구가 롤 · 발로 둘 다 등록해서 게임을 골라주세요)" if len(accounts) > 1 else ""))
        return
    if member.id == ctx.author.id:
        await ctx.send("❌ 자기 판에는 걸 수 없어요.")
        return
    if not any(a["game"] == game for a in accounts):
        await ctx.send(f"❌ {member.display_name}님은 {GAMES[game]} 계정을 등록하지 않았어요.")
        return
    if not BET_MIN <= amount <= BET_MAX:
        await ctx.send(f"❌ {num(BET_MIN)} ~ {num(BET_MAX)} byte 까지 걸 수 있어요.")
        return
    error = bet = None
    async with db.user_tx(ctx.author.id) as conn:
        money = await db.get_money(ctx.author.id, conn)
        if any(b["target_id"] == member.id and b["game"] == game for b in await db.open_bets(bettor_id=ctx.author.id, conn=conn)):
            error = "❌ 이 친구 다음 판에 이미 걸었어요. 판이 끝나면 다시 걸 수 있어요."
        elif money < amount:
            error = f"💸 돈이 부족해요. (보유: {num(money)} byte)"
        else:
            await db.update_user(ctx.author.id, conn, money=money - amount)
            await db.log_money(ctx.author.id, "bet", -amount, f"{GAMES[game]} {member.id} {'승' if side == 'win' else '패'}", conn)
            bet = await db.add_bet(ctx.guild.id, ctx.author.id, member.id, game, side, amount, conn)
    if error:
        await ctx.send(error)
        return
    pool = await db.open_bets(member.id, game)
    win_pool = sum(b["amount"] for b in pool if b["side"] == "win")
    lose_pool = sum(b["amount"] for b in pool if b["side"] == "lose")
    await ctx.send(
        f"🎲 {member.mention}님의 다음 {GAMES[game]} 랭크 판에 **{'승' if side == 'win' else '패'}** {num(amount)} byte 걸었어요! (`#{bet['id']}`)\n"
        f"지금 판돈: 승 {num(win_pool)} · 패 {num(lose_pool)} · 맞힌 사람끼리 나눠 가져요 (수수료 {int(BET_FEE * 100)}%)\n"
        f"-# 지금부터 시작하는 판에 적용돼요 · {int(BET_EXPIRE.total_seconds() // 3600)}시간 안에 판이 없으면 돌려받아요"
    )


@client.command(aliases=["베팅목록"])
async def game_bet_list(ctx):
    bets = await db.open_bets()
    if ctx.guild is not None:
        bets = [b for b in bets if ctx.guild.get_member(int(b["target_id"]))]
    embed = discord.Embed(title="🎲 지금 걸려 있는 판", color=0xf39c12)
    if not bets:
        embed.description = "걸린 판이 없어요. `%베팅 @친구 롤 승 1000`"
        await ctx.send(embed=embed)
        return
    groups = {}
    for b in bets:
        groups.setdefault((b["target_id"], b["game"]), []).append(b)
    for (target, game), group in groups.items():
        win = [b for b in group if b["side"] == "win"]
        lose = [b for b in group if b["side"] == "lose"]
        line = lambda bs: ", ".join(f"<@{b['bettor_id']}> {num(b['amount'])}" for b in bs) or "-"
        member = ctx.guild.get_member(int(target)) if ctx.guild else None
        name = member.display_name if member else str(target)
        embed.add_field(
            name=f"{name} · {GAMES[game]} 다음 판 (승 {num(sum(b['amount'] for b in win))} : 패 {num(sum(b['amount'] for b in lose))})",
            value=f"🟦 승: {line(win)}\n🟥 패: {line(lose)}", inline=False,
        )
    embed.set_footer(text="맞힌 사람끼리 건 비율대로 나눠 가져요 · 한쪽에만 걸리면 돌려줘요")
    await ctx.send(embed=embed)
