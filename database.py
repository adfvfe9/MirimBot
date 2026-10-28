"""미림봇 DB 접근 모듈 (PostgreSQL + asyncpg).

main.py 는 SQL 을 직접 쓰지 않고 이 파일의 함수만 호출한다.
테이블 구조는 schema.sql 에 있다.

사용 규칙
1. 모든 함수는 async 라서 `await db.함수()` 로 호출한다.
2. user_id / guild_id 는 int 든 str 이든 넘겨도 된다.
3. 돈은 float 로 주고받는다. (DB 안에서는 NUMERIC 으로 정확하게 저장된다)
4. "잔액 확인 → 차감"처럼 여러 단계로 돈을 바꿀 때는 user_tx 로 감싼다.

       async with db.user_tx(user_id) as conn:
           user = await db.get_user(user_id, conn)
           if user["money"] < cost:
               return
           await db.update_user(user_id, conn, money=user["money"] - cost)

   user_tx 안에서는 그 유저의 행이 잠기기 때문에, 버튼을 연타하거나 같은 명령을
   동시에 보내도 앞의 처리가 끝날 때까지 기다린다. (돈 복사 / 이중 지출 방지)
   또 중간에 에러가 나면 그 안에서 바꾼 내용이 전부 취소된다.
   잠근 상태로 디스코드 메시지를 보내면 그동안 다른 명령이 기다리게 되므로,
   메시지 전송은 user_tx 블록이 끝난 뒤에 한다.
"""
from __future__ import annotations

import contextvars
import datetime
import json
import os
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path

import asyncpg

KST = datetime.timezone(datetime.timedelta(hours=9))
SCHEMA_PATH = Path(__file__).with_name("schema.sql")

_pool: asyncpg.Pool | None = None


# ───────────── 연결 ─────────────

async def connect(dsn: str | None = None) -> None:
    """봇 시작 시 한 번 호출. 연결 풀을 만들고, 테이블이 없으면 만든다."""
    global _pool
    if _pool is not None:
        return
    # Neon 의 -pooler 주소(pgbouncer)가 들어 있어도 직접 연결 주소로 바꿔 쓴다.
    #   풀러에서는 쿼리 저장(statement cache)을 꺼야 해서 쿼리마다 DB 왕복이 2번(준비 + 실행)이 된다.
    #   봇 하나가 연결 몇 개만 쓰니 풀러가 필요 없다.
    # min_size: 연결을 미리 열어 둔다. 새 연결은 맺는 데 (TLS 등) 시간이 걸려서,
    #           여러 명이 동시에 명령어를 쓸 때 그때그때 맺으면 그만큼 느려진다.
    # max_inactive_connection_lifetime=0: 한동안 안 쓴 연결도 닫지 않는다. (다시 맺느라 느려지지 않게)
    _pool = await asyncpg.create_pool(
        (dsn or os.environ["DATABASE_URL"]).replace("-pooler.", ".", 1),
        min_size=3,
        max_size=10,
        max_inactive_connection_lifetime=0,
    )
    async with _pool.acquire() as conn:
        await conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("db.connect() 가 먼저 호출되어야 합니다.")
    return _pool


@asynccontextmanager
async def transaction():
    """여러 쿼리를 한 번에 처리 (중간에 실패하면 전부 취소)."""
    async with pool().acquire() as conn:
        async with conn.transaction():
            yield conn


@asynccontextmanager
async def user_tx(*user_ids):
    """트랜잭션을 열고 해당 유저 행들을 잠근다. (모듈 설명 참고)
    송금처럼 두 명을 다룰 때는 user_tx(보내는사람, 받는사람) 으로 둘 다 잠근다."""
    ids = sorted({int(u) for u in user_ids})
    # 항상 같은 순서(user_id 오름차순)로 잠가야 서로 기다리다 멈추는(deadlock) 일이 없다.
    lock = "SELECT 1 FROM users WHERE user_id = ANY($1::bigint[]) ORDER BY user_id FOR UPDATE"
    async with transaction() as conn:
        # 보통은 행이 이미 있어서 잠그기 한 번으로 끝난다. 처음 보는 유저만 행을 만들고 다시 잠근다.
        if len(await conn.fetch(lock, ids)) < len(ids):
            await conn.execute("INSERT INTO users (user_id) SELECT unnest($1::bigint[]) ON CONFLICT DO NOTHING", ids)
            await conn.execute(lock, ids)
        token = _locked.set((conn, frozenset(ids)))
        try:
            yield conn
        finally:
            _locked.reset(token)


# user_tx 안에서 (그 conn, 행이 있는 유저들). _ensure_user 가 이미 있는 행을 또 만들려고 하지 않게
_locked = contextvars.ContextVar("locked_users", default=(None, frozenset()))


# ───────────── 시간 / 숫자 헬퍼 ─────────────

def now() -> datetime.datetime:
    """현재 한국 시간 (타임존 포함). DB 에 저장하는 시각은 전부 이걸 쓴다."""
    return datetime.datetime.now(KST)


def today() -> datetime.date:
    """오늘 날짜 (한국 기준). 봇을 UTC 서버에서 돌려도 출석/수급 날짜가 어긋나지 않는다."""
    return now().date()


def _num(value) -> Decimal:
    """파이썬 숫자 → DB NUMERIC. 계산한 값을 반올림하지 않고 그대로 저장한다.
    (화면에 보여줄 때만 fmt.num 으로 소수 2자리까지 내림해서 보여준다)"""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(repr(float(value)))


def _float(value) -> float:
    return float(value) if value is not None else 0.0


# ───────────── 유저 ─────────────

# 행이 없는 유저의 기본값 (schema.sql 의 DEFAULT 와 같아야 한다)
USER_DEFAULTS = {
    "money": 0.0,
    "gamble_net": 0.0,
    "gamble_last_at": None,
    "welfare_last_date": None,
    "welfare_streak": 0,
    "consolation_date": None,
    "bankruptcy_date": None,
    "tokens": 0,
    "token_price": 100,
    "token_price_at": None,
    "deposit_amount": 0.0,
    "deposit_start": None,
    "unpaid_amount": 0.0,
    "suggestion_last_at": None,
    "rps_date": None,
    "rps_count": 0,
    "send_date": None,
    "send_total": 0.0,
    "wordchain_date": None,
    "wordchain_earned": 0.0,
}
_MONEY_FIELDS = {"money", "gamble_net", "deposit_amount", "unpaid_amount", "send_total", "wordchain_earned"}
_INT_NUMERIC_FIELDS = {"token_price"}


def _user_from_row(row) -> dict:
    user = dict(row)
    for key in _MONEY_FIELDS:
        user[key] = _float(user[key])
    for key in _INT_NUMERIC_FIELDS:
        user[key] = int(user[key])
    return user


async def get_user(user_id, conn=None) -> dict:
    """유저 데이터 전체를 dict 로. 처음 보는 유저면 기본값을 돌려준다 (행은 만들지 않음)."""
    uid = int(user_id)
    row = await (conn or pool()).fetchrow("SELECT * FROM users WHERE user_id = $1", uid)
    if row is None:
        return {"user_id": uid, **USER_DEFAULTS}
    return _user_from_row(row)


async def _ensure_user(c, user_id) -> None:
    """유저 행이 없으면 기본값으로 만든다.
    돈을 바꿀 때는 항상 "행 만들기 → UPDATE" 순서로 한다. (INSERT ... ON CONFLICT DO UPDATE 를 쓰면
    schema.sql 의 미납금 트리거와 엇갈려서 돈을 빼는 값이 사라질 수 있다)"""
    conn, ids = _locked.get()
    if c is conn and int(user_id) in ids:
        return      # user_tx 가 이미 만들고 잠근 행
    await c.execute("INSERT INTO users (user_id) VALUES ($1) ON CONFLICT DO NOTHING", int(user_id))


async def update_user(user_id, conn=None, **fields) -> None:
    """유저 필드 일부를 바꾼다. 행이 없으면 만든다.
        await db.update_user(uid, conn, money=1000, tokens=3)
    """
    if not fields:
        return
    unknown = set(fields) - set(USER_DEFAULTS)
    if unknown:
        raise ValueError(f"users 테이블에 없는 필드: {sorted(unknown)}")

    columns = list(fields)
    values = [
        _num(value) if column in _MONEY_FIELDS | _INT_NUMERIC_FIELDS else value
        for column, value in fields.items()
    ]
    sets = ", ".join(f"{c} = ${i}" for i, c in enumerate(columns, start=2))
    c = conn or pool()
    await _ensure_user(c, user_id)
    await c.execute(f"UPDATE users SET {sets} WHERE user_id = $1", int(user_id), *values)


async def get_money(user_id, conn=None) -> float:
    value = await (conn or pool()).fetchval(
        "SELECT money FROM users WHERE user_id = $1", int(user_id)
    )
    return _float(value)


async def add_money(user_id, delta, conn=None) -> float:
    """돈을 더한다 (음수면 뺀다). 한 문장이라 user_tx 없이 써도 안전하다. 바뀐 잔액을 돌려준다."""
    c = conn or pool()
    await _ensure_user(c, user_id)
    value = await c.fetchval(
        "UPDATE users SET money = money + $2 WHERE user_id = $1 RETURNING money",
        int(user_id), _num(delta),
    )
    return _float(value)


async def receive(user_id, amount, conn=None) -> dict:
    """돈을 받는다. 미납금이 있으면 그중 일부/전부가 바로 징수된다. (schema.sql 의 트리거)
    {"balance": 받은 뒤 잔액, "collected": 미납금으로 징수된 금액, "unpaid": 남은 미납금}"""
    c = conn or pool()
    await _ensure_user(c, user_id)
    row = await c.fetchrow(
        """
        WITH old AS (SELECT unpaid_amount FROM users WHERE user_id = $1)
        UPDATE users SET money = money + $2 WHERE user_id = $1
        RETURNING money, unpaid_amount, (SELECT unpaid_amount FROM old) AS old_unpaid
        """,
        int(user_id), _num(amount),
    )
    return {
        "balance": float(row["money"]),
        "collected": max(0.0, float(row["old_unpaid"] - row["unpaid_amount"])),
        "unpaid": float(row["unpaid_amount"]),
    }


# 돈 기록 source 목록 (밸런스 분석용, schema.sql 의 money_log)
#   admin_add / admin_remove      관리자 머니추가 / 머니제거
#   transfer_send / transfer_recv 송금 (보낸 쪽은 수수료 포함)
#   welfare / consolation         기초수급 / 위로금
#   bankrupt                      파산으로 사라진 잔액
#   loan / loan_repay             대출 / 상환
#   deposit_in / deposit_out      적금 넣기 / 빼기
#   enhance_craft / enhance_try / enhance_sell
#   futures_open / futures_fee (진입 수수료) / futures_close / futures_settle (상장폐지 정산) / futures_insurance (청산 보험)
#   stock_buy / stock_sell / chart
#   gamble / rps / quiz / wordchain / token_buy
#   market_buy / market_sell (암시장, 판매 쪽은 수수료 뺀 금액) / market_fee
#   mining_rig (채굴기 구매 / 업그레이드) / mining_power (채굴 전기세)
async def log_money(user_id, source: str, amount, memo: str | None = None, conn=None) -> None:
    """돈이 바뀐 기록을 남긴다. 돈을 바꾼 것과 같은 conn 으로 부르면 함께 취소/저장된다."""
    if not amount:
        return
    await (conn or pool()).execute(
        "INSERT INTO money_log (user_id, source, amount, memo) VALUES ($1, $2, $3, $4)",
        int(user_id), source, _num(amount), memo,
    )


async def log_money_many(rows, conn=None) -> None:
    """log_money 여러 개를 한 번에. rows = [(user_id, source, amount, memo), ...] (자동 강화)"""
    rows = [(int(u), s, _num(a), m) for u, s, a, m in rows if a]
    if rows:
        await (conn or pool()).executemany(
            "INSERT INTO money_log (user_id, source, amount, memo) VALUES ($1, $2, $3, $4)", rows
        )


async def bankrupt(user_id, day: datetime.date, conn=None) -> None:
    """파산: 돈, 미납금, 대출, 적금, 주식, 레버리지 포지션, 강화 아이템을 전부 정리한다."""
    uid = int(user_id)

    async def run(c):
        await log_money(uid, "bankrupt", -await get_money(uid, c), conn=c)
        await c.execute("DELETE FROM loans WHERE user_id = $1", uid)
        await c.execute("DELETE FROM portfolio WHERE user_id = $1", uid)
        await c.execute("DELETE FROM stock_positions WHERE user_id = $1", uid)
        await c.execute("DELETE FROM enhance_items WHERE user_id = $1", uid)
        await c.execute("DELETE FROM enhance_abilities WHERE user_id = $1", uid)
        await c.execute("DELETE FROM market_listings WHERE seller_id = $1", uid)  # 암시장에 맡긴 아이템도
        await c.execute("DELETE FROM miners WHERE user_id = $1", uid)             # 채굴기도
        await update_user(
            uid, c, money=0, unpaid_amount=0, deposit_amount=0, deposit_start=None,
            bankruptcy_date=day,
        )

    if conn is not None:
        await run(conn)
    else:
        async with transaction() as c:
            await run(c)


async def add_tokens(user_id, delta: int, conn=None) -> int | None:
    """토큰을 더한다 (음수면 뺀다). 0 개 미만이 되면 바꾸지 않고 None, 성공하면 바뀐 개수."""
    if delta < 0:
        return await (conn or pool()).fetchval(
            "UPDATE users SET tokens = tokens + $2 WHERE user_id = $1 AND tokens + $2 >= 0 "
            "RETURNING tokens",
            int(user_id), delta,
        )
    c = conn or pool()
    await _ensure_user(c, user_id)
    return await c.fetchval(
        "UPDATE users SET tokens = tokens + $2 WHERE user_id = $1 RETURNING tokens",
        int(user_id), delta,
    )


async def top_users(column: str, limit: int = 10, where: str = "TRUE") -> list[tuple[int, float]]:
    """랭킹용: column 기준 내림차순 상위 limit 명. [(user_id, 값), ...]"""
    if column not in _MONEY_FIELDS:
        raise ValueError(column)
    rows = await pool().fetch(
        f"SELECT user_id, {column} AS value FROM users WHERE {where} "
        f"ORDER BY {column} DESC LIMIT $1",
        limit,
    )
    return [(r["user_id"], _float(r["value"])) for r in rows]


async def top_money(limit: int = 10) -> list[tuple[int, float]]:
    return await top_users("money", limit)


async def top_gamble(limit: int = 10) -> list[tuple[int, float]]:
    """도박을 한 번이라도 한 유저만."""
    return await top_users(
        "gamble_net", limit, where="gamble_last_at IS NOT NULL OR gamble_net <> 0"
    )


async def average_positive_money() -> float:
    """잔액이 양수인 유저들의 평균 잔액 (은행 대출 한도)."""
    value = await pool().fetchval("SELECT avg(money) FROM users WHERE money > 0")
    return _float(value)


# ───────────── 강화 아이템 ─────────────

async def get_enhance_items(user_id, conn=None) -> dict[str, int]:
    """{아이템 이름: 레벨}"""
    rows = await (conn or pool()).fetch(
        "SELECT item_name, level FROM enhance_items WHERE user_id = $1 ORDER BY item_name",
        int(user_id),
    )
    return {r["item_name"]: r["level"] for r in rows}


async def set_enhance_level(user_id, item_name: str, level: int, conn=None) -> None:
    await (conn or pool()).execute(
        """
        INSERT INTO enhance_items (user_id, item_name, level) VALUES ($1, $2, $3)
        ON CONFLICT (user_id, item_name) DO UPDATE SET level = EXCLUDED.level
        """,
        int(user_id), item_name, level,
    )


async def all_enhance_items() -> list[dict]:
    """강화 랭킹 / 순자산용: [{user_id, item_name, level}, ...] 레벨 높은 순"""
    rows = await pool().fetch(
        "SELECT user_id, item_name, level FROM enhance_items ORDER BY level DESC, item_name"
    )
    return [dict(r) for r in rows]


async def delete_enhance_item(user_id, item_name: str, conn=None) -> int | None:
    """아이템을 지우고 지워진 아이템의 레벨을 돌려준다. 없으면 None. 붙어 있던 능력도 같이 지운다."""
    c = conn or pool()
    await c.execute(
        "DELETE FROM enhance_abilities WHERE user_id = $1 AND item_name = $2", int(user_id), item_name
    )
    return await c.fetchval(
        "DELETE FROM enhance_items WHERE user_id = $1 AND item_name = $2 RETURNING level",
        int(user_id), item_name,
    )


# ───────────── 강화 능력 슬롯 (features/abilities.py) ─────────────

async def get_abilities(user_id, conn=None) -> list[dict]:
    """[{item_name, slot, ability, tier, value, locked}, ...] 아이템 이름, 슬롯 순"""
    rows = await (conn or pool()).fetch(
        "SELECT item_name, slot, ability, tier, value, locked FROM enhance_abilities "
        "WHERE user_id = $1 ORDER BY item_name, slot",
        int(user_id),
    )
    return [{**dict(r), "value": float(r["value"])} for r in rows]


async def get_ability_levels(user_id, conn=None) -> list[dict]:
    """능력 합계용: 능력 슬롯마다 그 아이템의 지금 레벨까지 한 번에 [{item_name, slot, ability, value, level}]
    (아이템 / 능력을 따로 읽으면 DB 왕복이 2번이라 합쳤다. 암시장에 올린 아이템은 enhance_items 에 없어서 빠진다)"""
    rows = await (conn or pool()).fetch(
        """
        SELECT a.item_name, a.slot, a.ability, a.value, i.level
        FROM enhance_abilities a JOIN enhance_items i ON i.user_id = a.user_id AND i.item_name = a.item_name
        WHERE a.user_id = $1
        """,
        int(user_id),
    )
    return [{**dict(r), "value": float(r["value"])} for r in rows]


async def set_ability(user_id, item_name: str, slot: int, ability: str, tier: int, value: float, conn=None) -> None:
    """슬롯에 능력을 넣는다. 잠금 상태는 그대로 둔다."""
    await (conn or pool()).execute(
        """
        INSERT INTO enhance_abilities (user_id, item_name, slot, ability, tier, value) VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (user_id, item_name, slot) DO UPDATE
            SET ability = EXCLUDED.ability, tier = EXCLUDED.tier, value = EXCLUDED.value
        """,
        int(user_id), item_name, slot, ability, tier, _num(value),
    )


async def set_ability_lock(user_id, item_name: str, slot: int, locked: bool, conn=None) -> None:
    await (conn or pool()).execute(
        "UPDATE enhance_abilities SET locked = $4 WHERE user_id = $1 AND item_name = $2 AND slot = $3",
        int(user_id), item_name, slot, locked,
    )


# ───────────── 암시장 (features/market.py) ─────────────

def _listing_from_row(row) -> dict:
    listing = dict(row)
    listing["price"] = float(listing["price"])
    if isinstance(listing["abilities"], str):
        listing["abilities"] = json.loads(listing["abilities"])
    return listing


async def add_listing(seller_id, item_name: str, level: int, abilities: list, price: float,
                      expires_at: datetime.datetime, conn=None, tokens: int = 0) -> int:
    """등록. tokens > 0 이면 토큰 묶음 등록 (price 는 묶음 전체 가격)"""
    return await (conn or pool()).fetchval(
        """
        INSERT INTO market_listings (seller_id, item_name, level, abilities, price, expires_at, tokens)
        VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7) RETURNING id
        """,
        int(seller_id), item_name, level, json.dumps(abilities), _num(price), expires_at, tokens,
    )


async def active_listings(at: datetime.datetime) -> list[dict]:
    """만료되지 않은 등록 전부 (최근 등록 순)"""
    rows = await pool().fetch("SELECT * FROM market_listings WHERE expires_at > $1 ORDER BY id DESC", at)
    return [_listing_from_row(r) for r in rows]


async def seller_listings(seller_id, conn=None) -> list[dict]:
    rows = await (conn or pool()).fetch(
        "SELECT * FROM market_listings WHERE seller_id = $1 ORDER BY id", int(seller_id)
    )
    return [_listing_from_row(r) for r in rows]


async def get_listing(listing_id: int, conn=None, lock: bool = False) -> dict | None:
    row = await (conn or pool()).fetchrow(
        "SELECT * FROM market_listings WHERE id = $1" + (" FOR UPDATE" if lock else ""), listing_id
    )
    return _listing_from_row(row) if row else None


async def delete_listing(listing_id: int, conn=None) -> dict | None:
    """등록을 지우고 지운 등록을 돌려준다. 이미 없으면 None. (두 번 팔리기 방지)"""
    row = await (conn or pool()).fetchrow("DELETE FROM market_listings WHERE id = $1 RETURNING *", listing_id)
    return _listing_from_row(row) if row else None


async def expired_listing_ids(at: datetime.datetime) -> list[int]:
    rows = await pool().fetch("SELECT id FROM market_listings WHERE expires_at <= $1", at)
    return [r["id"] for r in rows]


async def add_trade(seller_id, buyer_id, item_name: str, level: int, slots: int, price: float,
                    conn=None, tokens: int = 0) -> None:
    await (conn or pool()).execute(
        "INSERT INTO market_trades (seller_id, buyer_id, item_name, level, slots, price, tokens) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        int(seller_id), int(buyer_id), item_name, level, slots, _num(price), tokens,
    )


async def recent_trade_prices(level: int, limit: int = 10) -> list[float]:
    """같은 레벨 강화 아이템 최근 거래가 (최근 것부터)"""
    rows = await pool().fetch(
        "SELECT price FROM market_trades WHERE level = $1 AND tokens = 0 ORDER BY id DESC LIMIT $2", level, limit
    )
    return [float(r["price"]) for r in rows]


async def recent_token_prices(limit: int = 10) -> list[float]:
    """토큰 최근 거래의 개당 가격 (최근 것부터)"""
    rows = await pool().fetch(
        "SELECT price / tokens AS unit FROM market_trades WHERE tokens > 0 ORDER BY id DESC LIMIT $1", limit
    )
    return [float(r["unit"]) for r in rows]


# ───────────── 주식 ─────────────

async def load_stock_prices() -> dict[str, dict]:
    """{종목: {"current": 현재가, "previous": 직전가}}"""
    rows = await pool().fetch("SELECT symbol, current_price, previous_price FROM stocks")
    return {
        r["symbol"]: {"current": _float(r["current_price"]), "previous": _float(r["previous_price"])}
        for r in rows
    }


async def save_stock_prices(stock_prices: dict, conn=None) -> None:
    await (conn or pool()).executemany(
        """
        INSERT INTO stocks (symbol, current_price, previous_price) VALUES ($1, $2, $3)
        ON CONFLICT (symbol) DO UPDATE
            SET current_price = EXCLUDED.current_price, previous_price = EXCLUDED.previous_price
        """,
        [(s, _num(p["current"]), _num(p["previous"])) for s, p in stock_prices.items()],
    )


async def save_stock_tick(stock_prices: dict, keep: int = 1440, history=None) -> None:
    """1분 갱신 결과 저장: 현재가 저장 + 가격 기록 추가 + 종목당 최근 keep 개만 남기기.
    history 에 [(종목, 가격), ...] 를 주면 현재가 대신 그 기록들을 순서대로 한 번에 넣는다. (%주식가속)"""
    if history is None:
        history = [(s, p["current"]) for s, p in stock_prices.items()]
    async with transaction() as conn:
        await save_stock_prices(stock_prices, conn)
        # 한 쿼리로 넣는다. (기록이 수천 줄이어도 DB 를 한 번만 다녀온다)
        await conn.execute(
            """
            INSERT INTO price_history (symbol, price)
            SELECT symbol, price FROM unnest($1::text[], $2::numeric[]) WITH ORDINALITY AS t(symbol, price, n)
            ORDER BY n
            """,
            [s for s, _ in history], [_num(p) for _, p in history],
        )
        await conn.execute(
            """
            DELETE FROM price_history WHERE id IN (
                SELECT id FROM (
                    SELECT id, row_number() OVER (PARTITION BY symbol ORDER BY id DESC) AS rn
                    FROM price_history
                ) t WHERE rn > $1
            )
            """,
            keep,
        )


async def load_recent_prices(minutes: int, symbol: str | None = None) -> dict[str, list[float]]:
    """{종목: [오래된 가격, ..., 최신 가격]} 최근 minutes 개만 (symbol 을 주면 그 종목만). 그래프용.
    전체 기록(24시간 × 종목 수)을 다 받으면 그만큼 느려서, 필요한 만큼만 받는다."""
    rows = await pool().fetch(
        """
        SELECT symbol, price FROM (
            SELECT id, symbol, price, row_number() OVER (PARTITION BY symbol ORDER BY id DESC) AS rn
            FROM price_history WHERE $2::text IS NULL OR symbol = $2
        ) t WHERE rn <= $1 ORDER BY id
        """,
        minutes, symbol,
    )
    history: dict[str, list[float]] = {}
    for r in rows:
        history.setdefault(r["symbol"], []).append(_float(r["price"]))
    return history


async def clear_price_history() -> None:
    await pool().execute("DELETE FROM price_history")


async def get_portfolio(user_id, conn=None) -> dict[str, dict]:
    """{종목: {"quantity": 수량, "avg_price": 평균단가, "last_bought_at": 마지막으로 산 시각 또는 None}}"""
    rows = await (conn or pool()).fetch(
        "SELECT symbol, quantity, avg_price, last_bought_at FROM portfolio WHERE user_id = $1 ORDER BY symbol",
        int(user_id),
    )
    return {
        r["symbol"]: {
            "quantity": r["quantity"],
            "avg_price": float(r["avg_price"]),
            "last_bought_at": r["last_bought_at"],
        }
        for r in rows
    }


async def all_portfolios() -> dict[int, dict[str, dict]]:
    """주식 랭킹용: {user_id: {종목: {...}}}"""
    rows = await pool().fetch("SELECT user_id, symbol, quantity, avg_price FROM portfolio")
    result: dict[int, dict[str, dict]] = {}
    for r in rows:
        result.setdefault(r["user_id"], {})[r["symbol"]] = {
            "quantity": r["quantity"],
            "avg_price": float(r["avg_price"]),
        }
    return result


async def set_holding(user_id, symbol: str, quantity: int, avg_price: float, conn=None,
                      bought_at: datetime.datetime | None = None) -> None:
    """보유 주식 저장. 수량이 0 이하면 삭제한다.
    bought_at 을 주면 마지막으로 산 시각을 그걸로 바꾸고, 안 주면 (판매) 그대로 둔다."""
    if quantity <= 0:
        await delete_holdings(user_id, [symbol], conn)
        return
    await (conn or pool()).execute(
        """
        INSERT INTO portfolio (user_id, symbol, quantity, avg_price, last_bought_at) VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (user_id, symbol) DO UPDATE
            SET quantity = EXCLUDED.quantity, avg_price = EXCLUDED.avg_price,
                last_bought_at = COALESCE(EXCLUDED.last_bought_at, portfolio.last_bought_at)
        """,
        int(user_id), symbol, quantity, Decimal(repr(float(avg_price))), bought_at,
    )


async def delete_holdings(user_id, symbols: list[str], conn=None) -> None:
    await (conn or pool()).execute(
        "DELETE FROM portfolio WHERE user_id = $1 AND symbol = ANY($2::text[])",
        int(user_id), list(symbols),
    )


async def delist_stock(symbol: str) -> list[int]:
    """상장폐지: 모든 유저의 해당 주식을 지우고 알림을 남긴다. 주식을 잃은 유저 ID 목록을 돌려준다."""
    async with transaction() as conn:
        rows = await conn.fetch("DELETE FROM portfolio WHERE symbol = $1 RETURNING user_id", symbol)
        user_ids = [r["user_id"] for r in rows]
        for uid in user_ids:
            await add_notice(uid, f"⚠️ `{symbol}` 주식은 상장폐지되어 자동 제거되었습니다.", conn)
    return user_ids


async def add_notice(user_id, message: str, conn=None) -> None:
    """유저가 없을 때 생긴 일(상장폐지, 강제청산 등)을 다음에 보여주려고 남겨둔다."""
    await (conn or pool()).execute(
        "INSERT INTO stock_notices (user_id, message) VALUES ($1, $2)", int(user_id), message
    )


async def pop_notices(user_id) -> list[str]:
    """아직 안 보여준 알림을 꺼내고 지운다."""
    rows = await pool().fetch(
        "DELETE FROM stock_notices WHERE user_id = $1 RETURNING id, message", int(user_id)
    )
    return [r["message"] for r in sorted(rows, key=lambda r: r["id"])]


# ───────────── 레버리지 포지션 ─────────────

def _position_from_row(row) -> dict:
    pos = dict(row)
    pos["margin"] = float(pos["margin"])
    pos["entry_price"] = float(pos["entry_price"])
    return pos


async def get_positions(user_id, conn=None) -> list[dict]:
    """[{id, symbol, side, margin, leverage, entry_price, opened_at}, ...] 오래된 순"""
    rows = await (conn or pool()).fetch(
        "SELECT * FROM stock_positions WHERE user_id = $1 ORDER BY id", int(user_id)
    )
    return [_position_from_row(r) for r in rows]


async def all_positions() -> list[dict]:
    rows = await pool().fetch("SELECT * FROM stock_positions ORDER BY id")
    return [_position_from_row(r) for r in rows]


async def add_position(user_id, symbol: str, side: str, margin: float, leverage: int,
                       entry_price: float, conn=None) -> int:
    return await (conn or pool()).fetchval(
        """
        INSERT INTO stock_positions (user_id, symbol, side, margin, leverage, entry_price)
        VALUES ($1, $2, $3, $4, $5, $6) RETURNING id
        """,
        int(user_id), symbol, side, _num(margin), leverage, _num(entry_price),
    )


async def shift_position_times(minutes: int) -> None:
    """%주식가속: 모든 포지션의 진입 시각을 minutes 분 앞으로 당긴다. (그만큼 보유 비용이 쌓인 것처럼)"""
    if minutes > 0:
        await pool().execute(
            "UPDATE stock_positions SET opened_at = opened_at - ($1 * interval '1 minute')", minutes
        )


async def delete_position(position_id: int, conn=None) -> dict | None:
    """포지션을 지우고 지워진 포지션을 돌려준다. 이미 없으면 None. (두 번 청산 방지)"""
    row = await (conn or pool()).fetchrow(
        "DELETE FROM stock_positions WHERE id = $1 RETURNING *", position_id
    )
    return _position_from_row(row) if row else None


async def delete_all_positions(user_id, conn=None) -> None:
    await (conn or pool()).execute("DELETE FROM stock_positions WHERE user_id = $1", int(user_id))


# ───────────── 자산 랭킹용 전체 조회 ─────────────

async def all_users() -> list[dict]:
    rows = await pool().fetch("SELECT * FROM users")
    return [_user_from_row(r) for r in rows]


async def all_open_loans() -> list[dict]:
    """아직 연체 처리되지 않은 대출 전부"""
    rows = await pool().fetch("SELECT * FROM loans WHERE NOT collected ORDER BY id")
    return [_loan_from_row(r) for r in rows]


async def load_market_state() -> dict | None:
    """{"state", "state_ends_at", "override_state", "override_end"} 또는 저장된 적 없으면 None"""
    row = await pool().fetchrow("SELECT * FROM market_state WHERE id = 1")
    return dict(row) if row else None


async def save_market_state(state: str, state_ends_at, override_state, override_end) -> None:
    await pool().execute(
        """
        INSERT INTO market_state (id, state, state_ends_at, override_state, override_end)
        VALUES (1, $1, $2, $3, $4)
        ON CONFLICT (id) DO UPDATE SET
            state = EXCLUDED.state,
            state_ends_at = EXCLUDED.state_ends_at,
            override_state = EXCLUDED.override_state,
            override_end = EXCLUDED.override_end
        """,
        state, state_ends_at, override_state, override_end,
    )


# ───────────── 은행 대출 ─────────────

def _loan_from_row(row) -> dict:
    loan = dict(row)
    for key in ("amount", "collection_amount", "collected_amount", "unpaid_from_loan"):
        if loan[key] is not None:
            loan[key] = float(loan[key])
    return loan


async def get_loans(user_id, conn=None) -> list[dict]:
    """대출 목록 (오래된 순). 각 항목: id, amount, taken_at, collected, ..."""
    rows = await (conn or pool()).fetch(
        "SELECT * FROM loans WHERE user_id = $1 ORDER BY id", int(user_id)
    )
    return [_loan_from_row(r) for r in rows]


async def add_loan(user_id, amount: float, taken_at, conn=None) -> None:
    await (conn or pool()).execute(
        "INSERT INTO loans (user_id, amount, taken_at) VALUES ($1, $2, $3)",
        int(user_id), _num(amount), taken_at,
    )


_LOAN_FIELDS = {"amount", "collected", "collection_amount", "collected_amount",
                "unpaid_from_loan", "collected_at"}


async def update_loan(loan_id: int, conn=None, **fields) -> None:
    unknown = set(fields) - _LOAN_FIELDS
    if unknown:
        raise ValueError(f"loans 테이블에 없는 필드: {sorted(unknown)}")
    columns = list(fields)
    values = [
        _num(v) if c in {"amount", "collection_amount", "collected_amount", "unpaid_from_loan"} else v
        for c, v in fields.items()
    ]
    sets = ", ".join(f"{c} = ${i}" for i, c in enumerate(columns, start=2))
    await (conn or pool()).execute(f"UPDATE loans SET {sets} WHERE id = $1", loan_id, *values)


async def delete_loan(loan_id: int, conn=None) -> None:
    await (conn or pool()).execute("DELETE FROM loans WHERE id = $1", loan_id)


async def users_with_overdue_loans(deadline: datetime.datetime) -> list[int]:
    """deadline 이전에 받은, 아직 강제징수 안 된 대출이 있는 유저 목록."""
    rows = await pool().fetch(
        "SELECT DISTINCT user_id FROM loans WHERE NOT collected AND taken_at <= $1", deadline
    )
    return [r["user_id"] for r in rows]


# ───────────── 경고 ─────────────

async def get_warning(guild_id, user_id) -> dict | None:
    """{"count", "restriction_until", "reasons": [기록 문자열, ...]} 또는 기록이 없으면 None"""
    gid, uid = int(guild_id), int(user_id)
    row = await pool().fetchrow(
        "SELECT count, restriction_until FROM warnings WHERE guild_id = $1 AND user_id = $2",
        gid, uid,
    )
    if row is None:
        return None
    logs = await pool().fetch(
        "SELECT entry FROM warning_logs WHERE guild_id = $1 AND user_id = $2 ORDER BY id",
        gid, uid,
    )
    return {
        "count": row["count"],
        "restriction_until": row["restriction_until"],
        "reasons": [r["entry"] for r in logs],
    }


async def add_warning_count(guild_id, user_id, amount: int) -> int:
    """경고 수를 amount 만큼 바꾸고 (0 미만으로는 안 내려감) 바뀐 경고 수를 돌려준다."""
    return await pool().fetchval(
        """
        INSERT INTO warnings (guild_id, user_id, count) VALUES ($1, $2, GREATEST(0, $3::int))
        ON CONFLICT (guild_id, user_id) DO UPDATE
            SET count = GREATEST(0, warnings.count + $3::int)
        RETURNING count
        """,
        int(guild_id), int(user_id), amount,
    )


async def add_warning_log(guild_id, user_id, entry: str) -> None:
    await pool().execute(
        "INSERT INTO warning_logs (guild_id, user_id, entry) VALUES ($1, $2, $3)",
        int(guild_id), int(user_id), entry,
    )


async def set_restriction(guild_id, user_id, until) -> None:
    """이용제한 해제 시각을 저장한다. None 이면 이용제한 기록을 지운다."""
    await pool().execute(
        "UPDATE warnings SET restriction_until = $3 WHERE guild_id = $1 AND user_id = $2",
        int(guild_id), int(user_id), until,
    )


async def expired_restrictions(at: datetime.datetime) -> list[tuple[int, int]]:
    """이용제한 시간이 끝난 [(guild_id, user_id), ...]"""
    rows = await pool().fetch(
        "SELECT guild_id, user_id FROM warnings WHERE restriction_until <= $1", at
    )
    return [(r["guild_id"], r["user_id"]) for r in rows]


# ───────────── 건의 ─────────────

async def add_suggestion(user_id, content: str, at: datetime.datetime) -> None:
    async with transaction() as conn:
        await conn.execute(
            "INSERT INTO suggestions (user_id, content, created_at) VALUES ($1, $2, $3)",
            int(user_id), content, at,
        )
        await update_user(user_id, conn, suggestion_last_at=at)


async def list_suggestions() -> list[dict]:
    """[{"id", "user_id", "content", "created_at"}, ...] 오래된 순"""
    rows = await pool().fetch("SELECT * FROM suggestions ORDER BY id")
    return [dict(r) for r in rows]


async def delete_suggestion(suggestion_id: int) -> dict | None:
    row = await pool().fetchrow("DELETE FROM suggestions WHERE id = $1 RETURNING *", suggestion_id)
    return dict(row) if row else None


async def is_suggestion_admin(user_id) -> bool:
    return await pool().fetchval(
        "SELECT EXISTS (SELECT 1 FROM suggestion_admins WHERE user_id = $1)", int(user_id)
    )


# ───────────── TTS 줄임말 (features/tts.py, %줄임말설정) ─────────────

async def tts_abbrevs(guild_id) -> list:
    """서버의 줄임말 [{word, reading, set_by}] (글자 순)"""
    rows = await pool().fetch(
        "SELECT word, reading, set_by FROM tts_abbrevs WHERE guild_id = $1 ORDER BY word", int(guild_id)
    )
    return [dict(r) for r in rows]


async def set_tts_abbrev(guild_id, word: str, reading: str, user_id) -> None:
    await pool().execute(
        """
        INSERT INTO tts_abbrevs (guild_id, word, reading, set_by) VALUES ($1, $2, $3, $4)
        ON CONFLICT (guild_id, word) DO UPDATE SET reading = EXCLUDED.reading, set_by = EXCLUDED.set_by
        """,
        int(guild_id), word, reading, int(user_id),
    )


async def delete_tts_abbrev(guild_id, word: str) -> bool:
    result = await pool().execute(
        "DELETE FROM tts_abbrevs WHERE guild_id = $1 AND word = $2", int(guild_id), word
    )
    return result != "DELETE 0"


# ───────────── 일일 미션 (features/missions.py) ─────────────

async def money_log_counts_today(user_id, sources, day: datetime.date) -> dict:
    """{source: 오늘(한국 날짜) 기록 수}"""
    start = datetime.datetime.combine(day, datetime.time(0), KST)
    rows = await pool().fetch(
        """
        SELECT source, count(*) AS n FROM money_log
        WHERE user_id = $1 AND source = ANY($2::text[]) AND created_at >= $3 AND created_at < $4
        GROUP BY source
        """,
        int(user_id), list(sources), start, start + datetime.timedelta(days=1),
    )
    return {r["source"]: r["n"] for r in rows}


async def mission_claims(user_id, day: datetime.date, conn=None) -> set:
    rows = await (conn or pool()).fetch(
        "SELECT mission FROM mission_claims WHERE user_id = $1 AND day = $2", int(user_id), day
    )
    return {r["mission"] for r in rows}


async def add_mission_claim(user_id, day: datetime.date, mission: str, conn=None) -> bool:
    """처음 받는 거면 True (이미 받았으면 False)"""
    return await (conn or pool()).fetchval(
        "INSERT INTO mission_claims (user_id, day, mission) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING RETURNING true",
        int(user_id), day, mission,
    ) is not None


# ───────────── 주식 예약 매매 (features/orders.py) ─────────────

def _order(row):
    return {**dict(row), "price": _float(row["price"])}


async def add_order(user_id, symbol, side, quantity, price, direction, expires_at, conn=None) -> dict:
    row = await (conn or pool()).fetchrow(
        """
        INSERT INTO stock_orders (user_id, symbol, side, quantity, price, direction, expires_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *
        """,
        int(user_id), symbol, side, quantity, _num(price), direction, expires_at,
    )
    return _order(row)


async def user_orders(user_id, conn=None) -> list[dict]:
    rows = await (conn or pool()).fetch("SELECT * FROM stock_orders WHERE user_id = $1 ORDER BY id", int(user_id))
    return [_order(r) for r in rows]


async def all_orders() -> list[dict]:
    return [_order(r) for r in await pool().fetch("SELECT * FROM stock_orders ORDER BY id")]


async def delete_order(order_id, user_id=None) -> bool:
    """지웠으면 True. 이미 없으면 (그사이 처리 / 취소) False. user_id 를 주면 그 사람 예약만"""
    result = await pool().execute(
        "DELETE FROM stock_orders WHERE id = $1 AND ($2::bigint IS NULL OR user_id = $2)",
        int(order_id), user_id and int(user_id),
    )
    return result != "DELETE 0"


# ───────────── 역할 상점 (features/roleshop.py) ─────────────

async def shop_roles(guild_id) -> list[dict]:
    rows = await pool().fetch(
        "SELECT * FROM shop_roles WHERE guild_id = $1 ORDER BY price, added_at", int(guild_id)
    )
    return [{**dict(r), "price": _float(r["price"])} for r in rows]


async def get_shop_role(guild_id, role_id) -> dict | None:
    row = await pool().fetchrow(
        "SELECT * FROM shop_roles WHERE guild_id = $1 AND role_id = $2", int(guild_id), int(role_id)
    )
    return {**dict(row), "price": _float(row["price"])} if row else None


async def upsert_shop_role(guild_id, role_id, price, days: int, description: str | None) -> None:
    await pool().execute(
        """
        INSERT INTO shop_roles (guild_id, role_id, price, days, description) VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (guild_id, role_id) DO UPDATE
        SET price = EXCLUDED.price, days = EXCLUDED.days, description = EXCLUDED.description
        """,
        int(guild_id), int(role_id), _num(price), days, description,
    )


async def set_shop_role_active(guild_id, role_id, active: bool) -> None:
    await pool().execute(
        "UPDATE shop_roles SET active = $3 WHERE guild_id = $1 AND role_id = $2", int(guild_id), int(role_id), active
    )


async def delete_shop_role(guild_id, role_id) -> None:
    await pool().execute("DELETE FROM shop_roles WHERE guild_id = $1 AND role_id = $2", int(guild_id), int(role_id))


async def get_role_purchase(guild_id, user_id, role_id, conn=None) -> dict | None:
    row = await (conn or pool()).fetchrow(
        "SELECT * FROM role_purchases WHERE guild_id = $1 AND user_id = $2 AND role_id = $3",
        int(guild_id), int(user_id), int(role_id),
    )
    return dict(row) if row else None


async def set_role_purchase(guild_id, user_id, role_id, expires_at, conn=None) -> None:
    await (conn or pool()).execute(
        """
        INSERT INTO role_purchases (guild_id, user_id, role_id, expires_at) VALUES ($1, $2, $3, $4)
        ON CONFLICT (guild_id, user_id, role_id) DO UPDATE SET expires_at = EXCLUDED.expires_at
        """,
        int(guild_id), int(user_id), int(role_id), expires_at,
    )


async def delete_role_purchase(guild_id, user_id, role_id, conn=None) -> None:
    await (conn or pool()).execute(
        "DELETE FROM role_purchases WHERE guild_id = $1 AND user_id = $2 AND role_id = $3",
        int(guild_id), int(user_id), int(role_id),
    )


async def role_purchases_of(guild_id, user_id) -> list[dict]:
    rows = await pool().fetch(
        "SELECT * FROM role_purchases WHERE guild_id = $1 AND user_id = $2 ORDER BY bought_at", int(guild_id), int(user_id)
    )
    return [dict(r) for r in rows]


async def expired_role_purchases(now) -> list[dict]:
    rows = await pool().fetch("SELECT * FROM role_purchases WHERE expires_at IS NOT NULL AND expires_at <= $1", now)
    return [dict(r) for r in rows]


# ───────────── 학사정보 (features/school.py) ─────────────

SCHOOL_COLUMNS = (
    "edu_code", "school_code", "school_name", "school_kind", "channel_id", "post_time",
    "post_meal", "post_schedule", "post_timetable", "grade", "class_nm", "last_posted",
)


async def get_school_settings(guild_id) -> dict | None:
    row = await pool().fetchrow("SELECT * FROM school_settings WHERE guild_id = $1", int(guild_id))
    return dict(row) if row else None


async def update_school_settings(guild_id, current: dict, **changes) -> None:
    """current(지금 설정, 기본값 포함)에 changes 를 덮어써서 저장한다. 행이 없으면 만든다."""
    row = {k: changes.get(k, current[k]) for k in SCHOOL_COLUMNS}
    cols = ", ".join(SCHOOL_COLUMNS)
    marks = ", ".join(f"${i}" for i in range(2, len(SCHOOL_COLUMNS) + 2))
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in SCHOOL_COLUMNS)
    await pool().execute(
        f"INSERT INTO school_settings (guild_id, {cols}) VALUES ($1, {marks}) "
        f"ON CONFLICT (guild_id) DO UPDATE SET {sets}",
        int(guild_id), *row.values(),
    )


async def school_channels() -> list[dict]:
    """알림 채널이 정해진 서버들의 설정"""
    rows = await pool().fetch("SELECT * FROM school_settings WHERE channel_id IS NOT NULL")
    return [dict(r) for r in rows]


async def get_user_class(guild_id, user_id) -> dict | None:
    row = await pool().fetchrow(
        "SELECT grade, class_nm FROM user_classes WHERE guild_id = $1 AND user_id = $2", int(guild_id), int(user_id)
    )
    return dict(row) if row else None


async def set_user_class(guild_id, user_id, grade: int, class_nm: str) -> None:
    await pool().execute(
        """
        INSERT INTO user_classes (guild_id, user_id, grade, class_nm) VALUES ($1, $2, $3, $4)
        ON CONFLICT (guild_id, user_id) DO UPDATE SET grade = EXCLUDED.grade, class_nm = EXCLUDED.class_nm
        """,
        int(guild_id), int(user_id), grade, class_nm,
    )


# ───────────── 명령어 / 버튼 기록 (features/audit.py, %로그) ─────────────

async def add_command_log(user_id, guild_id, channel_id, kind: str, name: str, content: str | None,
                          result: str | None = None, ms: int | None = None) -> None:
    await pool().execute(
        """
        INSERT INTO command_log (user_id, guild_id, channel_id, kind, name, content, result, ms)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        int(user_id), guild_id and int(guild_id), channel_id and int(channel_id), kind, name, content, result, ms,
    )


async def command_logs(guild_id=None, user_id=None, text: str | None = None, names=None, limit: int = 20) -> list[dict]:
    """최근 기록부터. text 는 이름이나 내용에 들어간 글자, names 는 이 이름들 중 하나 (관리자 명령어 보기)"""
    rows = await pool().fetch(
        """
        SELECT * FROM command_log
        WHERE ($1::bigint IS NULL OR guild_id = $1)
          AND ($2::bigint IS NULL OR user_id = $2)
          AND ($3::text IS NULL OR name ILIKE '%' || $3 || '%' OR content ILIKE '%' || $3 || '%')
          AND ($4::text[] IS NULL OR name = ANY($4))
        ORDER BY created_at DESC, id DESC LIMIT $5
        """,
        guild_id and int(guild_id), user_id and int(user_id), text, names, limit,
    )
    return [dict(r) for r in rows]


async def prune_command_log(before: datetime.datetime) -> int:
    result = await pool().execute("DELETE FROM command_log WHERE created_at < $1", before)
    return int(result.split()[-1])


# ───────────── 봇 운영 상태 (key-value) ─────────────

async def get_state(key: str) -> str | None:
    return await pool().fetchval("SELECT value FROM bot_state WHERE key = $1", key)


async def set_state(key: str, value: str) -> None:
    await pool().execute(
        """
        INSERT INTO bot_state (key, value) VALUES ($1, $2)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        key, value,
    )


# ───────────── 주식 뉴스 ─────────────

async def add_news(kind: str, symbol, headline: str, body: str) -> None:
    await pool().execute(
        "INSERT INTO news (kind, symbol, headline, body) VALUES ($1, $2, $3, $4)",
        kind, symbol, headline, body,
    )


async def recent_news(limit: int = 5) -> list[dict]:
    rows = await pool().fetch("SELECT * FROM news ORDER BY id DESC LIMIT $1", limit)
    return [dict(r) for r in rows]


# ───────────── 롤 · 발로란트 연동 (features/games.py) ─────────────

async def get_game_account(user_id, game) -> dict | None:
    row = await pool().fetchrow("SELECT * FROM game_accounts WHERE user_id = $1 AND game = $2", int(user_id), game)
    return dict(row) if row else None


async def game_accounts(game=None) -> list[dict]:
    rows = await pool().fetch(
        "SELECT * FROM game_accounts WHERE ($1::text IS NULL OR game = $1) ORDER BY registered_at", game
    )
    return [dict(r) for r in rows]


async def game_account_by_puuid(game, puuid) -> dict | None:
    row = await pool().fetchrow("SELECT * FROM game_accounts WHERE game = $1 AND puuid = $2", game, puuid)
    return dict(row) if row else None


async def set_game_account(user_id, game, puuid, riot_id, region, last_match_id) -> None:
    await pool().execute(
        """
        INSERT INTO game_accounts (user_id, game, puuid, riot_id, region, last_match_id) VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (user_id, game) DO UPDATE
        SET puuid = EXCLUDED.puuid, riot_id = EXCLUDED.riot_id, region = EXCLUDED.region,
            last_match_id = EXCLUDED.last_match_id, registered_at = now()
        """,
        int(user_id), game, puuid, riot_id, region, last_match_id,
    )


async def delete_game_account(user_id, game) -> bool:
    result = await pool().execute("DELETE FROM game_accounts WHERE user_id = $1 AND game = $2", int(user_id), game)
    return result != "DELETE 0"


async def set_last_match(user_id, game, match_id) -> None:
    await pool().execute(
        "UPDATE game_accounts SET last_match_id = $3 WHERE user_id = $1 AND game = $2", int(user_id), game, match_id
    )


async def add_game_match(m: dict) -> bool:
    """처음 넣으면 True (이미 있으면 False)"""
    return await pool().fetchval(
        """
        INSERT INTO game_matches (game, match_id, user_id, started_at, queue, result, character, kills, deaths, assists, detail)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11) ON CONFLICT DO NOTHING RETURNING true
        """,
        m["game"], m["match_id"], int(m["user_id"]), m["started_at"], m["queue"], m["result"],
        m.get("character"), m.get("kills"), m.get("deaths"), m.get("assists"), m.get("detail"),
    ) is not None


async def game_matches_since(start) -> list[dict]:
    rows = await pool().fetch("SELECT * FROM game_matches WHERE started_at >= $1 ORDER BY started_at", start)
    return [dict(r) for r in rows]


def _bet(row):
    d = dict(row)
    d["amount"] = _float(d["amount"])
    d["payout"] = None if d["payout"] is None else _float(d["payout"])
    return d


async def add_bet(guild_id, bettor_id, target_id, game, side, amount, conn=None) -> dict:
    row = await (conn or pool()).fetchrow(
        """
        INSERT INTO game_bets (guild_id, bettor_id, target_id, game, side, amount)
        VALUES ($1, $2, $3, $4, $5, $6) RETURNING *
        """,
        guild_id and int(guild_id), int(bettor_id), int(target_id), game, side, _num(amount),
    )
    return _bet(row)


async def open_bets(target_id=None, game=None, bettor_id=None, conn=None) -> list[dict]:
    rows = await (conn or pool()).fetch(
        """
        SELECT * FROM game_bets WHERE status = 'open'
          AND ($1::bigint IS NULL OR target_id = $1) AND ($2::text IS NULL OR game = $2)
          AND ($3::bigint IS NULL OR bettor_id = $3)
        ORDER BY id
        """,
        target_id and int(target_id), game, bettor_id and int(bettor_id),
    )
    return [_bet(r) for r in rows]


async def close_bet(bet_id, status, match_id, payout, conn) -> bool:
    """아직 open 이면 닫고 True (이미 정산됐으면 False — 두 번 정산 방지)"""
    return await conn.fetchval(
        """
        UPDATE game_bets SET status = $2, match_id = $3, payout = $4
        WHERE id = $1 AND status = 'open' RETURNING true
        """,
        int(bet_id), status, match_id, _num(payout),
    ) is not None


# ───────────── 오늘의 미림봇 (features/digest.py) ─────────────

async def add_brag(user_id, kind: str, text: str, amount=None) -> None:
    await pool().execute(
        "INSERT INTO brag_log (user_id, kind, amount, text) VALUES ($1, $2, $3, $4)",
        int(user_id), kind, None if amount is None else _num(amount), text,
    )


async def brags_since(start) -> list[dict]:
    rows = await pool().fetch("SELECT * FROM brag_log WHERE created_at >= $1 ORDER BY id", start)
    return [{**dict(r), "amount": None if r["amount"] is None else _float(r["amount"])} for r in rows]


async def prune_brags(before) -> None:
    await pool().execute("DELETE FROM brag_log WHERE created_at < $1", before)


async def active_users_since(start) -> set:
    """이 시각 이후 명령어(% 또는 /)를 쓴 사람들"""
    rows = await pool().fetch(
        "SELECT DISTINCT user_id FROM command_log WHERE created_at >= $1 AND kind IN ('command', 'slash')", start
    )
    return {r["user_id"] for r in rows}


async def worth_baseline(start) -> dict:
    """{user_id: start 직전(없으면 직후) 1시간 기록의 순자산}"""
    rows = await pool().fetch(
        """
        SELECT DISTINCT ON (user_id) user_id, worth FROM asset_history
        WHERE recorded_at <= $1 ORDER BY user_id, recorded_at DESC
        """,
        start,
    )
    result = {r["user_id"]: _float(r["worth"]) for r in rows}
    later = await pool().fetch(
        """
        SELECT DISTINCT ON (user_id) user_id, worth FROM asset_history
        WHERE recorded_at > $1 ORDER BY user_id, recorded_at
        """,
        start,
    )
    for r in later:
        result.setdefault(r["user_id"], _float(r["worth"]))
    return result


async def money_log_since(start, sources) -> list[dict]:
    rows = await pool().fetch(
        "SELECT user_id, source, amount, memo FROM money_log WHERE created_at >= $1 AND source = ANY($2::text[])",
        start, list(sources),
    )
    return [{**dict(r), "amount": _float(r["amount"])} for r in rows]


async def first_prices_since(start) -> dict:
    """{종목: start 이후 첫 가격}"""
    rows = await pool().fetch(
        "SELECT DISTINCT ON (symbol) symbol, price FROM price_history WHERE recorded_at >= $1 ORDER BY symbol, id", start
    )
    return {r["symbol"]: _float(r["price"]) for r in rows}


async def mission_clears(day) -> list[int]:
    rows = await pool().fetch("SELECT user_id FROM mission_claims WHERE day = $1 AND mission = 'all'", day)
    return [r["user_id"] for r in rows]


async def welfare_streaks(since_day) -> list[dict]:
    """since_day 이후에 기초수급을 받은 사람들의 연속 일수 (큰 순)"""
    rows = await pool().fetch(
        "SELECT user_id, welfare_streak FROM users WHERE welfare_last_date >= $1 AND welfare_streak > 0 "
        "ORDER BY welfare_streak DESC",
        since_day,
    )
    return [dict(r) for r in rows]


async def get_news_channels() -> list[int]:
    rows = await pool().fetch("SELECT value FROM bot_state WHERE key LIKE 'news_channel:%'")
    return [int(r["value"]) for r in rows]


async def set_news_channel(guild_id, channel_id) -> None:
    await set_state(f"news_channel:{int(guild_id)}", str(int(channel_id)))


# ───────────── 비트코인 (features/crypto.py) ─────────────

async def load_coin() -> tuple[float, float, list[float]] | None:
    """(현재가, 직전가, 최근 기록 [오래된 것 ... 최신]) 또는 처음이면 None"""
    row = await pool().fetchrow("SELECT price, previous FROM coin_price WHERE symbol = 'BTC'")
    if row is None:
        return None
    rows = await pool().fetch("SELECT price FROM coin_history ORDER BY id")
    return float(row["price"]), float(row["previous"]), [float(r["price"]) for r in rows]


async def save_coin(price: float, previous: float, history: list[float], keep: int = 1440) -> None:
    """현재가 저장 + 새 기록들을 한 번에 넣고 최근 keep 개만 남긴다."""
    async with transaction() as conn:
        await conn.execute(
            """
            INSERT INTO coin_price (symbol, price, previous) VALUES ('BTC', $1, $2)
            ON CONFLICT (symbol) DO UPDATE SET price = EXCLUDED.price, previous = EXCLUDED.previous
            """,
            _num(price), _num(previous),
        )
        if history:
            await conn.execute(
                "INSERT INTO coin_history (price) SELECT p FROM unnest($1::numeric[]) WITH ORDINALITY AS t(p, n) ORDER BY n",
                [_num(p) for p in history],
            )
        await conn.execute(
            "DELETE FROM coin_history WHERE id IN (SELECT id FROM coin_history ORDER BY id DESC OFFSET $1)", keep
        )


async def rescale_coin(factor: float) -> None:
    """액면 조정: 가격 기록은 factor 배, 모든 보유량은 1/factor 배 (가치는 그대로)"""
    async with transaction() as conn:
        await conn.execute("UPDATE coin_history SET price = price * $1", _num(factor))
        await conn.execute("UPDATE coin_holdings SET amount = amount / $1", _num(factor))
        await conn.execute("UPDATE miners SET mined = mined / $1, last_reward = last_reward / $1", _num(factor))


async def get_coin_holding(user_id, conn=None) -> dict:
    row = await (conn or pool()).fetchrow("SELECT amount, spent FROM coin_holdings WHERE user_id = $1", int(user_id))
    if row is None:
        return {"amount": 0.0, "spent": 0.0}
    return {"amount": float(row["amount"]), "spent": float(row["spent"])}


async def set_coin_holding(user_id, amount: float, spent: float, conn=None) -> None:
    c = conn or pool()
    if amount <= 0:
        await c.execute("DELETE FROM coin_holdings WHERE user_id = $1", int(user_id))
        return
    await c.execute(
        """
        INSERT INTO coin_holdings (user_id, amount, spent) VALUES ($1, $2, $3)
        ON CONFLICT (user_id) DO UPDATE SET amount = EXCLUDED.amount, spent = EXCLUDED.spent
        """,
        int(user_id), _num(amount), _num(spent),
    )


async def all_coin_holdings() -> list[dict]:
    rows = await pool().fetch("SELECT user_id, amount, spent FROM coin_holdings")
    return [{"user_id": r["user_id"], "amount": float(r["amount"]), "spent": float(r["spent"])} for r in rows]


# ───────────── 코인 채굴 (features/mining.py) ─────────────

def _miner(row) -> dict:
    return {
        "user_id": row["user_id"], "rigs": list(row["rigs"]), "running": row["running"],
        "mined": float(row["mined"]), "power_paid": float(row["power_paid"]),
        "last_reward": float(row["last_reward"]), "note": row["note"],
    }


MINER_DEFAULT = {"rigs": [], "running": False, "mined": 0.0, "power_paid": 0.0, "last_reward": 0.0, "note": None}


async def get_miner(user_id, conn=None) -> dict:
    row = await (conn or pool()).fetchrow("SELECT * FROM miners WHERE user_id = $1", int(user_id))
    return _miner(row) if row else {"user_id": int(user_id), **MINER_DEFAULT, "rigs": []}


async def all_miners(conn=None) -> list[dict]:
    rows = await (conn or pool()).fetch("SELECT * FROM miners WHERE cardinality(rigs) > 0")
    return [_miner(r) for r in rows]


async def update_miner(user_id, conn=None, **fields) -> None:
    """miners 행 일부를 바꾼다. 행이 없으면 만든다. (mined / power_paid / last_reward 는 숫자)"""
    columns = list(fields)
    values = [_num(v) if c in ("mined", "power_paid", "last_reward") else v for c, v in fields.items()]
    sets = ", ".join(f"{c} = ${i}" for i, c in enumerate(columns, start=2))
    c = conn or pool()
    await c.execute("INSERT INTO miners (user_id) VALUES ($1) ON CONFLICT DO NOTHING", int(user_id))
    await c.execute(f"UPDATE miners SET {sets} WHERE user_id = $1", int(user_id), *values)


# ───────────── 칭호 (features/titles.py) ─────────────

async def title_stats(user_id) -> dict:
    """칭호 진행도에 쓰는 돈 기록 집계. (money_log 는 v1.2.8 부터 쌓였다)
    {"count": {source: 횟수}, "sum": {source: 합계}, "destroyed", "max_success", "rps_streak", "welfare_streak", "jackpots"}"""
    uid = int(user_id)
    rows = await pool().fetch(
        "SELECT source, count(*) AS n, sum(amount) AS total FROM money_log WHERE user_id = $1 GROUP BY source", uid
    )
    extra = await pool().fetchrow(
        r"""
        SELECT
            count(*) FILTER (WHERE source = 'enhance_try' AND memo LIKE '%→ destroy%') AS destroyed,
            max((regexp_match(memo, '^\+(\d+) → success'))[1]::int) FILTER (WHERE source = 'enhance_try') AS max_success,
            max((regexp_match(memo, 'streak (\d+)'))[1]::int) FILTER (WHERE source = 'rps') AS rps_streak,
            max((regexp_match(memo, 'streak (\d+)'))[1]::int) FILTER (WHERE source = 'welfare') AS welfare_streak,
            count(*) FILTER (WHERE source = 'gamble' AND memo LIKE '%x7.0') AS jackpots
        FROM money_log WHERE user_id = $1
        """,
        uid,
    )
    return {
        "count": {r["source"]: r["n"] for r in rows},
        "sum": {r["source"]: float(r["total"]) for r in rows},
        "destroyed": extra["destroyed"] or 0,
        "max_success": extra["max_success"] or 0,
        "rps_streak": extra["rps_streak"] or 0,
        "welfare_streak": extra["welfare_streak"] or 0,
        "jackpots": extra["jackpots"] or 0,
    }


async def wordchain_best(user_id) -> int:
    return await pool().fetchval(
        "SELECT coalesce(max(best_score), 0) FROM wordchain_records WHERE user_id = $1", int(user_id)
    )


async def get_titles(user_id, conn=None) -> dict:
    """{칭호 key: {"achieved_at", "equipped"}}"""
    rows = await (conn or pool()).fetch(
        "SELECT title, achieved_at, equipped FROM user_titles WHERE user_id = $1", int(user_id)
    )
    return {r["title"]: {"achieved_at": r["achieved_at"], "equipped": r["equipped"]} for r in rows}


async def add_titles(user_id, keys: list[str], conn=None) -> None:
    if keys:
        await (conn or pool()).execute(
            "INSERT INTO user_titles (user_id, title) SELECT $1, unnest($2::text[]) ON CONFLICT DO NOTHING",
            int(user_id), list(keys),
        )


async def equip_title(user_id, key: str | None) -> None:
    """key 칭호를 장착한다. None 이면 해제."""
    async with transaction() as conn:
        await conn.execute("UPDATE user_titles SET equipped = FALSE WHERE user_id = $1 AND equipped", int(user_id))
        if key:
            await conn.execute(
                "UPDATE user_titles SET equipped = TRUE WHERE user_id = $1 AND title = $2", int(user_id), key
            )


async def equipped_titles() -> dict:
    """{user_id: 장착한 칭호 key}"""
    rows = await pool().fetch("SELECT user_id, title FROM user_titles WHERE equipped")
    return {r["user_id"]: r["title"] for r in rows}


async def title_counts() -> dict:
    """{user_id: 가진 칭호 수}"""
    rows = await pool().fetch("SELECT user_id, count(*) AS n FROM user_titles GROUP BY user_id")
    return {r["user_id"]: r["n"] for r in rows}


# ───────────── 자산 기록 (features/assets.py, %자산그래프) ─────────────

async def save_asset_snapshot(worths: dict, at: datetime.datetime, keep_days: int = 30) -> None:
    """{user_id: 순자산} 을 at 시각으로 저장하고 keep_days 보다 오래된 기록은 지운다."""
    async with transaction() as conn:
        if worths:
            await conn.execute(
                """
                INSERT INTO asset_history (user_id, recorded_at, worth)
                SELECT u, $3, w FROM unnest($1::bigint[], $2::numeric[]) AS t(u, w)
                ON CONFLICT DO NOTHING
                """,
                [int(u) for u in worths], [_num(w) for w in worths.values()], at,
            )
        await conn.execute(
            "DELETE FROM asset_history WHERE recorded_at < $1", at - datetime.timedelta(days=keep_days)
        )


async def asset_history(user_id, since: datetime.datetime) -> list[tuple]:
    """[(시각, 순자산), ...] 오래된 것부터"""
    rows = await pool().fetch(
        "SELECT recorded_at, worth FROM asset_history WHERE user_id = $1 AND recorded_at >= $2 ORDER BY recorded_at",
        int(user_id), since,
    )
    return [(r["recorded_at"], float(r["worth"])) for r in rows]


async def peak_worth(user_id) -> float:
    """기록된 순자산 최고값 (기록이 없으면 0)"""
    value = await pool().fetchval("SELECT max(worth) FROM asset_history WHERE user_id = $1", int(user_id))
    return _float(value)


# ───────────── 끝말잇기 랭킹 ─────────────

async def record_wordchain(user_id, difficulty: str, score: int, words: int) -> dict:
    """한 판 점수를 기록한다. {"best": 최고 점수, "new_best": 이번에 갱신했는지, "rank": 최고 점수 기준 순위}"""
    uid = int(user_id)
    async with transaction() as conn:
        prev = await conn.fetchval(
            "SELECT best_score FROM wordchain_records WHERE user_id = $1 AND difficulty = $2 FOR UPDATE",
            uid, difficulty,
        )
        new_best = prev is None or score > prev
        if prev is None:
            await conn.execute(
                "INSERT INTO wordchain_records (user_id, difficulty, best_score, best_words) VALUES ($1, $2, $3, $4)",
                uid, difficulty, score, words,
            )
        elif new_best:
            await conn.execute(
                """
                UPDATE wordchain_records SET best_score = $3, best_words = $4, achieved_at = now(), games = games + 1
                WHERE user_id = $1 AND difficulty = $2
                """,
                uid, difficulty, score, words,
            )
        else:
            await conn.execute(
                "UPDATE wordchain_records SET games = games + 1 WHERE user_id = $1 AND difficulty = $2",
                uid, difficulty,
            )
        best = score if new_best else prev
        rank = await conn.fetchval(
            "SELECT count(*) + 1 FROM wordchain_records WHERE difficulty = $1 AND best_score > $2",
            difficulty, best,
        )
    return {"best": best, "new_best": new_best, "rank": rank}


async def top_wordchain(difficulty: str, limit: int = 10) -> list[dict]:
    """[{user_id, best_score, best_words, games, achieved_at}, ...] 점수 높은 순 (같으면 먼저 낸 사람)"""
    rows = await pool().fetch(
        """
        SELECT user_id, best_score, best_words, games, achieved_at FROM wordchain_records
        WHERE difficulty = $1 ORDER BY best_score DESC, achieved_at LIMIT $2
        """,
        difficulty, limit,
    )
    return [dict(r) for r in rows]


# ───────────── 선착순 퀴즈 ─────────────

async def get_quiz_channels() -> list[int]:
    rows = await pool().fetch("SELECT value FROM bot_state WHERE key LIKE 'quiz_channel:%'")
    return [int(r["value"]) for r in rows]


async def set_quiz_channel(guild_id, channel_id) -> None:
    await set_state(f"quiz_channel:{int(guild_id)}", str(int(channel_id)))


# ───────────── 전체 초기화 ─────────────

# %초기화 로 비우는 테이블.
# suggestion_admins(건의 관리자 목록)는 게임 데이터가 아니라 권한 설정이라 남긴다.
RESET_TABLES = [
    "users", "loans", "enhance_items", "enhance_abilities",
    "stocks", "price_history", "portfolio", "stock_positions", "stock_notices", "market_state",
    "warnings", "warning_logs", "suggestions", "news", "wordchain_records", "money_log",
    "market_listings", "market_trades", "coin_price", "coin_history", "coin_holdings", "miners",
    "user_titles", "asset_history", "mission_claims", "stock_orders", "brag_log", "game_bets",
]


async def reset_all() -> None:
    """모든 게임 데이터를 지운다. 되돌릴 수 없다."""
    await pool().execute(f"TRUNCATE {', '.join(RESET_TABLES)} RESTART IDENTITY")
