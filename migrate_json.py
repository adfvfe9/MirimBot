#!/usr/bin/env python3
"""기존 JSON 파일 → PostgreSQL 일회성 마이그레이션.

사용법
  python migrate_json.py --dry-run          # DB 없이 변환 결과만 확인 (먼저 이걸로 검증)
  set DATABASE_URL=postgresql://...         # (Windows) / export DATABASE_URL=... (Linux, Mac)
  python migrate_json.py                    # 실제 적재
  python migrate_json.py --force            # 이미 데이터가 있으면 전부 비우고 다시 적재

옵션
  --data-dir PATH   JSON 파일이 있는 폴더 (기본: 현재 폴더)

주의
  - 날짜/시각이 타임존 없이 저장되어 있어서 한국 시간(KST, UTC+9)으로 간주한다.
  - achievements.json, enhance_ranking.json, shop_items.json 은 main.py 가 읽지 않아서 옮기지 않는다.
  - 이미 데이터가 있는 DB에 --force 없이 실행하면 중단한다. (봇 운영 중 실수로 덮어쓰기 방지)
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import sys
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

KST = datetime.timezone(datetime.timedelta(hours=9))
SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# ───────────── 변환 헬퍼 ─────────────


def dec(value, places: str = "0.01") -> Decimal:
    """float 오차를 정리해서 Decimal로 (3001260628.1400003 → 3001260628.14)."""
    return Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def parse_dt(s: str | None) -> datetime.datetime | None:
    """'2026-10-19T10:36:40.140817' 형식. 타임존이 없으면 KST로 간주."""
    if not s:
        return None
    dt = datetime.datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=KST)


def parse_dt_space(s: str | None) -> datetime.datetime | None:
    """'2026-10-19 10:36:40' 형식 (경고/건의 로그에서 사용)."""
    if not s:
        return None
    return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)


def parse_date(s: str | None) -> datetime.date | None:
    return datetime.date.fromisoformat(s) if s else None


def load(data_dir: Path, name: str, default):
    """JSON 읽기. 파일이 없거나 비어 있으면 default."""
    path = data_dir / name
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8-sig").strip()
    return json.loads(text) if text else default


# ───────────── 변환 본체 (DB 없이 테스트 가능) ─────────────

USER_DEFAULTS = {
    "money": Decimal("0.00"),
    "savings": Decimal("0.00"),
    "gamble_net": Decimal("0.00"),
    "gamble_last_at": None,
    "welfare_last_claim": None,
    "welfare_streak": 0,
    "checkin_last_date": None,
    "checkin_streak": 0,
    "consolation_date": None,
    "tokens": 0,
    "token_price": 100,
}
USER_COLUMNS = list(USER_DEFAULTS)

# 외래키는 없지만, 지울 때/넣을 때 일관된 순서를 유지한다.
TABLE_ORDER = [
    "users", "bank_accounts", "enhance_items", "inventory",
    "stocks", "price_history", "portfolio", "delisted_notices", "market_state",
    "user_warnings", "warning_logs",
    "suggestions", "suggestion_admins", "attendance_channels",
]


def build_rows(d: Path) -> dict[str, tuple[list[str], list[tuple]]]:
    """JSON들을 읽어서 {테이블: (컬럼들, 행들)} 로 변환."""
    tables: dict[str, tuple[list[str], list[tuple]]] = {}

    # ── users: 유저당 1행으로 합치기 ──
    users: dict[int, dict] = defaultdict(dict)

    for uid, v in load(d, "money_data.json", {}).items():
        users[int(uid)]["money"] = dec(v)
    for uid, v in load(d, "bank_data.json", {}).items():
        users[int(uid)]["savings"] = dec(v)
    for uid, v in load(d, "gamble_stats.json", {}).items():
        users[int(uid)]["gamble_net"] = dec(v)
    for uid, v in load(d, "gamble_cooldowns.json", {}).items():
        users[int(uid)]["gamble_last_at"] = parse_dt(v)
    for uid, v in load(d, "welfare_data.json", {}).items():
        users[int(uid)]["welfare_last_claim"] = parse_date(v.get("last_claim"))
        users[int(uid)]["welfare_streak"] = int(v.get("streak", 0))
    for uid, v in load(d, "checkin_cooldowns.json", {}).items():
        users[int(uid)]["checkin_last_date"] = parse_date(v.get("last_date"))
        users[int(uid)]["checkin_streak"] = int(v.get("streak_level", 0))
    for uid, v in load(d, "consolation.json", {}).items():
        users[int(uid)]["consolation_date"] = parse_date(v)
    for uid, v in load(d, "token_data.json", {}).items():
        users[int(uid)]["tokens"] = int(v.get("tokens", 0))
        users[int(uid)]["token_price"] = int(v.get("price", 100))

    tables["users"] = (
        ["user_id", *USER_COLUMNS],
        [(uid, *[u.get(c, USER_DEFAULTS[c]) for c in USER_COLUMNS]) for uid, u in sorted(users.items())],
    )

    # ── 은행 ──
    tables["bank_accounts"] = (
        ["user_id", "credit_score", "loan_amount", "loan_date", "deposit_amount", "deposit_start"],
        [
            (
                int(uid), dec(v.get("credit_score", 1000)), dec(v.get("loan_amount", 0)),
                parse_dt(v.get("loan_date")), dec(v.get("deposit_amount", 0)),
                parse_dt(v.get("deposit_start")),
            )
            for uid, v in load(d, "bank_system.json", {}).items()
        ],
    )

    # ── 강화 / 인벤토리 ──
    tables["enhance_items"] = (
        ["user_id", "item_name", "level"],
        [
            (int(uid), name, int(level))
            for uid, items in load(d, "enhance_data.json", {}).items()
            for name, level in items.items()
        ],
    )
    tables["inventory"] = (
        ["user_id", "item_name", "quantity"],
        [
            (int(uid), name, int(qty))
            for uid, items in load(d, "items.json", {}).items()
            for name, qty in items.items()
            if int(qty) > 0
        ],
    )

    # ── 주식 ──
    tables["stocks"] = (
        ["symbol", "current_price", "previous_price"],
        [
            (sym, dec(v["current"]), dec(v["previous"]))
            for sym, v in load(d, "stock_prices.json", {}).items()
        ],
    )
    # 종목별 리스트 순서대로 넣어야 id 순서가 곧 시간 순서가 된다. 시각 정보는 원래 없으므로 NULL.
    tables["price_history"] = (
        ["symbol", "price", "recorded_at"],
        [
            (sym, dec(p), None)
            for sym, prices in load(d, "price_history.json", {}).items()
            for p in prices
        ],
    )
    tables["portfolio"] = (
        ["user_id", "symbol", "quantity", "avg_price"],
        [
            (int(uid), sym, int(h["quantity"]), dec(h["avg_price"], "0.0001"))
            for uid, holdings in load(d, "portfolio.json", {}).items()
            for sym, h in holdings.items()
            if int(h["quantity"]) > 0
        ],
    )
    tables["delisted_notices"] = (
        ["user_id", "symbol"],
        [
            (int(uid), sym)
            for uid, syms in load(d, "delisted_stocks.json", {}).items()
            for sym in syms
        ],
    )

    # ── 시장 상태: 남은 초 → 종료 시각 ──
    market = load(d, "market_state.json", None)
    market_rows = []
    if market:
        now = datetime.datetime.now(KST)
        ends_at = now + datetime.timedelta(seconds=int(market.get("remaining_seconds", 0)))
        market_rows.append((
            1, market.get("state", "BULL"), ends_at,
            market.get("override_state"), parse_dt(market.get("override_end")),
        ))
    tables["market_state"] = (
        ["id", "state", "state_ends_at", "override_state", "override_end"], market_rows,
    )

    # ── 경고 ──
    warn_rows, log_rows = [], []
    for guild_id, members in load(d, "warnings.json", {}).items():
        for uid, w in members.items():
            warn_rows.append((
                int(guild_id), int(uid), int(w.get("count", 0)),
                parse_dt_space(w.get("restriction_until")),
            ))
            for entry in w.get("reasons", []):
                log_rows.append((int(guild_id), int(uid), entry, None))
    tables["user_warnings"] = (
        ["guild_id", "user_id", "count", "restriction_until"], warn_rows,
    )
    tables["warning_logs"] = (
        ["guild_id", "user_id", "entry", "created_at"], log_rows,
    )

    # ── 건의: 로그를 시간순 한 줄씩 (last_time 은 최근 로그에서 계산되므로 버린다) ──
    sug_rows = [
        (int(uid), log["content"], parse_dt_space(log["time"]))
        for uid, rec in load(d, "suggestions.json", {}).items()
        for log in rec.get("logs", [])
    ]
    sug_rows.sort(key=lambda r: r[2])
    tables["suggestions"] = (["user_id", "content", "created_at"], sug_rows)
    tables["suggestion_admins"] = (
        ["user_id"], [(int(uid),) for uid in load(d, "suggestion_admins.json", [])],
    )
    tables["attendance_channels"] = (
        ["guild_id", "channel_id"],
        [(int(g), int(c)) for g, c in load(d, "attendance_channels.json", {}).items()],
    )

    return {name: tables[name] for name in TABLE_ORDER}


def expected_money_sum(tables) -> Decimal:
    cols, rows = tables["users"]
    i = cols.index("money")
    return sum((r[i] for r in rows), Decimal("0"))


def print_summary(tables) -> None:
    print(f"{'테이블':<22}{'행 수':>8}")
    print("-" * 30)
    for name, (_, rows) in tables.items():
        print(f"{name:<22}{len(rows):>8}")
    print("-" * 30)
    print(f"users.money 합계: {expected_money_sum(tables):,}")


# ───────────── DB 적재 ─────────────


async def migrate(tables, force: bool) -> None:
    try:
        import asyncpg
    except ImportError:
        sys.exit("asyncpg 가 필요합니다:  pip install asyncpg")

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("환경변수 DATABASE_URL 이 없습니다.")

    # statement_cache_size=0: Neon/Supabase 의 pooler(pgbouncer) 주소로도 동작하게 한다.
    conn = await asyncpg.connect(dsn, statement_cache_size=0)
    try:
        await conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

        existing = {
            name: await conn.fetchval(f"SELECT count(*) FROM {name}") for name in TABLE_ORDER
        }
        if any(existing.values()) and not force:
            filled = {k: v for k, v in existing.items() if v}
            sys.exit(f"이미 데이터가 있어서 중단합니다: {filled}\n"
                     "다시 적재하려면 --force (기존 데이터 전부 삭제)를 붙이세요.")

        async with conn.transaction():
            if force:
                await conn.execute(
                    "TRUNCATE " + ", ".join(TABLE_ORDER) + " RESTART IDENTITY"
                )
            for name, (cols, rows) in tables.items():
                if not rows:
                    continue
                placeholders = ", ".join(f"${i}" for i in range(1, len(cols) + 1))
                await conn.executemany(
                    f"INSERT INTO {name} ({', '.join(cols)}) VALUES ({placeholders})", rows
                )

        # 적재 검증: 행 수 + 돈 합계
        for name, (_, rows) in tables.items():
            got = await conn.fetchval(f"SELECT count(*) FROM {name}")
            status = "OK" if got == len(rows) else "불일치!"
            print(f"  {name:<22}{got:>8} / {len(rows):<8}{status}")
        db_sum = await conn.fetchval("SELECT coalesce(sum(money), 0) FROM users")
        want = expected_money_sum(tables)
        print(f"  money 합계  DB={db_sum:,}  JSON={want:,}  {'OK' if db_sum == want else '불일치!'}")
    finally:
        await conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=".", help="JSON 파일 폴더")
    ap.add_argument("--dry-run", action="store_true", help="DB 없이 변환 결과만 출력")
    ap.add_argument("--force", action="store_true", help="기존 데이터를 비우고 다시 적재")
    args = ap.parse_args()

    tables = build_rows(Path(args.data_dir))
    print_summary(tables)

    if args.dry_run:
        print("\n(dry-run: DB에는 아무것도 쓰지 않았습니다)")
        return
    print("\nDB 적재 중...")
    asyncio.run(migrate(tables, args.force))
    print("완료.")


if __name__ == "__main__":
    main()
