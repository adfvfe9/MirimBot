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
    # statement_cache_size=0: Neon 의 -pooler 주소(pgbouncer)에서도 동작하게 한다.
    _pool = await asyncpg.create_pool(
        dsn or os.environ["DATABASE_URL"],
        min_size=1,
        max_size=5,
        statement_cache_size=0,
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
    async with transaction() as conn:
        await conn.execute(
            "INSERT INTO users (user_id) SELECT unnest($1::bigint[]) ON CONFLICT DO NOTHING",
            ids,
        )
        # 항상 같은 순서(user_id 오름차순)로 잠가야 서로 기다리다 멈추는(deadlock) 일이 없다.
        await conn.execute(
            "SELECT 1 FROM users WHERE user_id = ANY($1::bigint[]) ORDER BY user_id FOR UPDATE",
            ids,
        )
        yield conn


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
async def log_money(user_id, source: str, amount, memo: str | None = None, conn=None) -> None:
    """돈이 바뀐 기록을 남긴다. 돈을 바꾼 것과 같은 conn 으로 부르면 함께 취소/저장된다."""
    if not amount:
        return
    await (conn or pool()).execute(
        "INSERT INTO money_log (user_id, source, amount, memo) VALUES ($1, $2, $3, $4)",
        int(user_id), source, _num(amount), memo,
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
                      expires_at: datetime.datetime, conn=None) -> int:
    return await (conn or pool()).fetchval(
        """
        INSERT INTO market_listings (seller_id, item_name, level, abilities, price, expires_at)
        VALUES ($1, $2, $3, $4::jsonb, $5, $6) RETURNING id
        """,
        int(seller_id), item_name, level, json.dumps(abilities), _num(price), expires_at,
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


async def add_trade(seller_id, buyer_id, item_name: str, level: int, slots: int, price: float, conn=None) -> None:
    await (conn or pool()).execute(
        "INSERT INTO market_trades (seller_id, buyer_id, item_name, level, slots, price) VALUES ($1, $2, $3, $4, $5, $6)",
        int(seller_id), int(buyer_id), item_name, level, slots, _num(price),
    )


async def recent_trade_prices(level: int, limit: int = 10) -> list[float]:
    """같은 레벨 최근 거래가 (최근 것부터)"""
    rows = await pool().fetch(
        "SELECT price FROM market_trades WHERE level = $1 ORDER BY id DESC LIMIT $2", level, limit
    )
    return [float(r["price"]) for r in rows]


# ───────────── 상점 아이템 (인벤토리) ─────────────

async def add_inventory_item(user_id, item_name: str, quantity: int = 1, conn=None) -> int:
    """아이템 개수를 더하고 바뀐 개수를 돌려준다."""
    return await (conn or pool()).fetchval(
        """
        INSERT INTO inventory (user_id, item_name, quantity) VALUES ($1, $2, $3)
        ON CONFLICT (user_id, item_name) DO UPDATE
            SET quantity = inventory.quantity + EXCLUDED.quantity
        RETURNING quantity
        """,
        int(user_id), item_name, quantity,
    )


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


async def load_price_history() -> dict[str, list[float]]:
    """{종목: [오래된 가격, ..., 최신 가격]}"""
    rows = await pool().fetch("SELECT symbol, price FROM price_history ORDER BY id")
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


async def get_news_channels() -> list[int]:
    rows = await pool().fetch("SELECT value FROM bot_state WHERE key LIKE 'news_channel:%'")
    return [int(r["value"]) for r in rows]


async def set_news_channel(guild_id, channel_id) -> None:
    await set_state(f"news_channel:{int(guild_id)}", str(int(channel_id)))


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
    "users", "loans", "enhance_items", "enhance_abilities", "inventory",
    "stocks", "price_history", "portfolio", "stock_positions", "stock_notices", "market_state",
    "warnings", "warning_logs", "suggestions", "news", "wordchain_records", "money_log",
    "market_listings", "market_trades",
]


async def reset_all() -> None:
    """모든 게임 데이터를 지운다. 되돌릴 수 없다."""
    await pool().execute(f"TRUNCATE {', '.join(RESET_TABLES)} RESTART IDENTITY")
