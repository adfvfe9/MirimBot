"""DB 접근 계층.

명령어 코드는 SQL을 직접 쓰지 않고 이 모듈의 함수만 호출한다.
(1단계: users 테이블 = 돈 / 도박 / 출석 / 복지 / 위로금 / 토큰)
은행, 주식, 강화, 경고, 건의는 다음 단계에서 같은 방식으로 이 파일에 추가한다.

사용 예 (main.py):
    import database as db

    @client.event
    async def setup_hook():
        await db.connect()

    ok = await db.transfer(sender_id, receiver_id, amount, fee)
"""
from __future__ import annotations

import datetime
import os
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import asyncpg

KST = datetime.timezone(datetime.timedelta(hours=9))
SCHEMA_PATH = Path(__file__).with_name("schema.sql")

_pool: asyncpg.Pool | None = None


# ───────────── 연결 ─────────────


async def connect(dsn: str | None = None) -> None:
    """봇 시작 시 한 번 호출. 풀을 만들고 테이블이 없으면 생성한다."""
    global _pool
    dsn = dsn or os.environ["DATABASE_URL"]
    # statement_cache_size=0: Neon/Supabase 의 pooler(pgbouncer) 주소로도 동작하게 한다.
    _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5, statement_cache_size=0)
    async with _pool.acquire() as conn:
        await conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))


async def close() -> None:
    if _pool:
        await _pool.close()


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("db.connect() 가 먼저 호출되어야 합니다.")
    return _pool


# ───────────── 헬퍼 ─────────────


def _dec(value) -> Decimal:
    """돈 계산용: float → 소수 2자리 Decimal."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _f(value):
    """기존 코드가 float 로 계산하므로, DB에서 읽은 Decimal 은 float 로 돌려준다.
    (실제 덧셈/뺄셈은 DB 안에서 Decimal 로 하므로 오차는 쌓이지 않는다.)"""
    return float(value) if isinstance(value, Decimal) else value


def now_kst() -> datetime.datetime:
    return datetime.datetime.now(KST)


def today_kst() -> datetime.date:
    """'오늘' 기준은 항상 한국 시간. (호스팅 서버가 UTC여도 출석 날짜가 어긋나지 않는다.)"""
    return now_kst().date()


# ───────────── 돈 ─────────────


async def get_money(user_id: int) -> float:
    v = await pool().fetchval("SELECT money FROM users WHERE user_id = $1", user_id)
    return _f(v) if v is not None else 0.0


async def add_money(user_id: int, delta, conn=None) -> float:
    """돈을 더한다 (음수면 뺀다). 유저 행이 없으면 만든다. 변경 후 잔액을 반환."""
    v = await (conn or pool()).fetchval(
        """
        INSERT INTO users (user_id, money) VALUES ($1, $2)
        ON CONFLICT (user_id) DO UPDATE SET money = users.money + EXCLUDED.money
        RETURNING money
        """,
        user_id, _dec(delta),
    )
    return _f(v)


async def try_spend(user_id: int, amount, conn=None) -> bool:
    """잔액이 충분할 때만 차감. 확인과 차감이 한 쿼리라서 동시에 눌러도 이중 지출이 안 생긴다."""
    v = await (conn or pool()).fetchval(
        "UPDATE users SET money = money - $2 WHERE user_id = $1 AND money >= $2 RETURNING money",
        user_id, _dec(amount),
    )
    return v is not None


async def transfer(sender_id: int, receiver_id: int, amount, fee=0) -> bool:
    """송금. (보내는 사람은 amount + fee 차감, 받는 사람은 amount 증가) 한 트랜잭션이라
    중간에 봇이 꺼져도 돈이 사라지거나 복제되지 않는다. 잔액 부족이면 False."""
    async with pool().acquire() as conn:
        async with conn.transaction():
            if not await try_spend(sender_id, _dec(amount) + _dec(fee), conn):
                return False
            await add_money(receiver_id, amount, conn)
            return True


async def top_money(limit: int = 10) -> list[tuple[int, float]]:
    rows = await pool().fetch(
        "SELECT user_id, money FROM users ORDER BY money DESC LIMIT $1", limit
    )
    return [(r["user_id"], _f(r["money"])) for r in rows]


# ───────────── 도박 ─────────────


async def add_gamble_net(user_id: int, delta) -> float:
    """도박 누적 손익에 더한다. 변경 후 값을 반환."""
    v = await pool().fetchval(
        """
        INSERT INTO users (user_id, gamble_net) VALUES ($1, $2)
        ON CONFLICT (user_id) DO UPDATE SET gamble_net = users.gamble_net + EXCLUDED.gamble_net
        RETURNING gamble_net
        """,
        user_id, _dec(delta),
    )
    return _f(v)


async def top_gamble(limit: int = 10, best: bool = True) -> list[tuple[int, float]]:
    """도박 손익 랭킹. best=False 면 가장 많이 잃은 순."""
    order = "DESC" if best else "ASC"
    rows = await pool().fetch(
        f"SELECT user_id, gamble_net FROM users ORDER BY gamble_net {order} LIMIT $1", limit
    )
    return [(r["user_id"], _f(r["gamble_net"])) for r in rows]


# ───────────── 유저 필드 (쿨타임, 출석, 복지, 토큰 등) ─────────────

# 돈(money)은 일부러 제외: 반드시 add_money / try_spend / transfer 로만 바꾼다.
_NUMERIC_FIELDS = {"savings", "gamble_net"}
_USER_FIELDS = _NUMERIC_FIELDS | {
    "gamble_last_at", "welfare_last_claim", "welfare_streak",
    "checkin_last_date", "checkin_streak", "consolation_date",
    "tokens", "token_price",
}


async def get_user(user_id: int) -> dict:
    """유저 한 명의 전체 데이터. 행이 없으면 기본값으로 만들어서 반환."""
    await pool().execute(
        "INSERT INTO users (user_id) VALUES ($1) ON CONFLICT (user_id) DO NOTHING", user_id
    )
    row = await pool().fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
    return {k: _f(v) for k, v in dict(row).items()}


async def update_user(user_id: int, **fields) -> None:
    """유저 필드 일부를 갱신. 예:
        await db.update_user(uid, welfare_last_claim=db.today_kst(), welfare_streak=3)
        await db.update_user(uid, gamble_last_at=db.now_kst())
    """
    if not fields:
        return
    bad = set(fields) - _USER_FIELDS
    if bad:
        raise ValueError(f"update_user 로 바꿀 수 없는 필드: {sorted(bad)}")

    cols = list(fields)
    values = [_dec(v) if c in _NUMERIC_FIELDS else v for c, v in fields.items()]
    placeholders = ", ".join(f"${i}" for i in range(2, len(cols) + 2))
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)
    await pool().execute(
        f"INSERT INTO users (user_id, {', '.join(cols)}) VALUES ($1, {placeholders}) "
        f"ON CONFLICT (user_id) DO UPDATE SET {updates}",
        user_id, *values,
    )
