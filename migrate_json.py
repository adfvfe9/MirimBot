"""기존 JSON 파일 → PostgreSQL 로 한 번만 옮기는 스크립트.

사용법 (봇을 끈 상태에서)
  python migrate_json.py --dry-run     # DB 는 건드리지 않고, 몇 개가 옮겨질지만 확인
  python migrate_json.py               # 실제로 옮기기 (DB 가 비어 있을 때만 동작)
  python migrate_json.py --reset       # DB 의 봇 테이블을 전부 지우고 새로 만든 뒤 옮기기

DATABASE_URL 은 .env 에서 읽는다.
JSON 파일은 지우지 않는다. 봇이 DB 로 잘 돌아가는 걸 확인한 뒤 직접 백업 폴더로 옮기면 된다.

옮기지 않는 파일 (main.py 에서 쓰지 않음)
  bank_data.json, enhance_ranking.json, shop_items.json, achievements.json
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

import database as db

KST = db.KST
BASE_DIR = Path(__file__).resolve().parent

# --reset 때 지울 테이블. 예전에 쓰던 테이블(attendance_channels, bank_accounts, user_warnings)도 포함한다.
ALL_TABLES = [
    "users", "loans", "enhance_items", "inventory", "stocks", "price_history",
    "portfolio", "delisted_notices", "market_state", "warnings", "warning_logs",
    "suggestions", "suggestion_admins", "attendance_channels",
    "bank_accounts", "user_warnings",
]


# ───────────── 변환 헬퍼 ─────────────

def load(data_dir: Path, name: str, default):
    """JSON 읽기. 파일이 없거나 비어 있으면 default."""
    path = data_dir / name
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return default
    data = json.loads(text)
    return data if isinstance(data, type(default)) else default


def money(value) -> Decimal:
    return db._num(float(value or 0))


def dt(text) -> datetime.datetime | None:
    """'2026-10-19T10:36:40.123' 또는 '2026-10-19 10:36:40'. 타임존이 없으면 한국 시간으로 본다."""
    if not text:
        return None
    value = datetime.datetime.fromisoformat(str(text))
    return value if value.tzinfo else value.replace(tzinfo=KST)


def date(text) -> datetime.date | None:
    return datetime.date.fromisoformat(str(text)[:10]) if text else None


# ───────────── JSON → 테이블별 행 목록 ─────────────

def convert(data_dir: Path) -> dict[str, list[tuple]]:
    now = db.now()
    users: dict[int, dict] = {}

    def user(uid) -> dict:
        return users.setdefault(int(uid), {})

    for uid, value in load(data_dir, "money_data.json", {}).items():
        user(uid)["money"] = money(value)

    for uid, value in load(data_dir, "gamble_stats.json", {}).items():
        user(uid)["gamble_net"] = money(value)

    for uid, value in load(data_dir, "gamble_cooldowns.json", {}).items():
        user(uid)["gamble_last_at"] = dt(value)

    for uid, value in load(data_dir, "welfare_data.json", {}).items():
        user(uid)["welfare_last_date"] = date(value.get("last_claim"))
        user(uid)["welfare_streak"] = int(value.get("streak", 0))

    for uid, value in load(data_dir, "consolation.json", {}).items():
        user(uid)["consolation_date"] = date(value)

    for uid, value in load(data_dir, "bankruptcy_data.json", {}).items():
        user(uid)["bankruptcy_date"] = date(value)

    for uid, value in load(data_dir, "token_data.json", {}).items():
        user(uid)["tokens"] = int(value.get("tokens", 0))
        user(uid)["token_price"] = Decimal(int(value.get("price", 100)))

    suggestions = []
    for uid, value in load(data_dir, "suggestions.json", {}).items():
        user(uid)["suggestion_last_at"] = dt(value.get("last_time"))
        for log in value.get("logs", []):
            suggestions.append((int(uid), log["content"], dt(log["time"])))
    suggestions.sort(key=lambda row: row[2])

    loans = []
    for uid, value in load(data_dir, "bank_system.json", {}).items():
        user(uid)["deposit_amount"] = money(value.get("deposit_amount"))
        user(uid)["deposit_start"] = dt(value.get("deposit_start"))
        user(uid)["unpaid_amount"] = money(value.get("unpaid_amount"))

        user_loans = value.get("loans") or []
        # 아주 예전 형식(loan_amount 하나)도 main.py 의 ensure_bank_user 처럼 대출 1건으로 바꾼다.
        if not user_loans and float(value.get("loan_amount") or 0) > 0:
            user_loans = [{"amount": value["loan_amount"],
                           "date": value.get("loan_date") or now.isoformat()}]
        for loan in user_loans:
            loans.append((
                int(uid),
                money(loan.get("amount")),
                dt(loan.get("date")) or now,
                bool(loan.get("collected", False)),
                money(loan["collection_amount"]) if "collection_amount" in loan else None,
                money(loan["collected_amount"]) if "collected_amount" in loan else None,
                money(loan["unpaid_from_loan"]) if "unpaid_from_loan" in loan else None,
                dt(loan.get("collected_at")),
            ))

    enhance_items = [
        (int(uid), name, int(level))
        for uid, items in load(data_dir, "enhance_data.json", {}).items()
        for name, level in items.items()
    ]

    inventory = [
        (int(uid), name, int(qty))
        for uid, items in load(data_dir, "items.json", {}).items()
        for name, qty in items.items()
        if int(qty) > 0
    ]

    stock_prices = load(data_dir, "stock_prices.json", {})
    stocks = [
        (symbol, money(p["current"]), money(p["previous"]))
        for symbol, p in stock_prices.items()
    ]

    # 예전 기록에는 시각이 없어서, 마지막 값을 지금으로 보고 1분 간격으로 거꾸로 채운다.
    price_history = []
    for symbol, prices in load(data_dir, "price_history.json", {}).items():
        prices = prices[-1440:]
        for i, price in enumerate(prices):
            at = now - datetime.timedelta(minutes=len(prices) - 1 - i)
            price_history.append((symbol, money(price), at))
    price_history.sort(key=lambda row: row[2])

    portfolio = []
    for uid, holdings in load(data_dir, "portfolio.json", {}).items():
        for symbol, h in holdings.items():
            if isinstance(h, dict):
                quantity, avg = int(h.get("quantity", 0)), h.get("avg_price")
            else:  # 아주 예전 형식: 수량만 저장
                quantity, avg = int(h), None
            if avg is None:
                avg = stock_prices.get(symbol, {}).get("current", 0)
            if quantity > 0:
                portfolio.append((int(uid), symbol, quantity, Decimal(repr(float(avg)))))

    delisted = [
        (int(uid), symbol)
        for uid, symbols in load(data_dir, "delisted_stocks.json", {}).items()
        for symbol in symbols
    ]

    market = load(data_dir, "market_state.json", {})
    market_state = []
    if market:
        market_state.append((
            market.get("state", "BULL"),
            now + datetime.timedelta(seconds=int(market.get("remaining_seconds", 0))),
            market.get("override_state"),
            dt(market.get("override_end")),
        ))

    warnings, warning_logs = [], []
    for gid, members in load(data_dir, "warnings.json", {}).items():
        if not isinstance(members, dict):
            continue
        for uid, w in members.items():
            if not isinstance(w, dict) or "count" not in w:
                continue
            warnings.append((int(gid), int(uid), int(w["count"]), dt(w.get("restriction_until"))))
            warning_logs += [(int(gid), int(uid), entry) for entry in w.get("reasons", [])]

    admins = [(int(uid),) for uid in load(data_dir, "suggestion_admins.json", [])]

    columns = list(db.USER_DEFAULTS)
    defaults = {
        c: db._num(v) if isinstance(v, (int, float)) and c not in ("welfare_streak", "tokens") else v
        for c, v in db.USER_DEFAULTS.items()
    }
    user_rows = [(uid, *(fields.get(c, defaults[c]) for c in columns)) for uid, fields in users.items()]

    return {
        f"users (user_id, {', '.join(columns)})": user_rows,
        "loans (user_id, amount, taken_at, collected, collection_amount, collected_amount, "
        "unpaid_from_loan, collected_at)": loans,
        "enhance_items (user_id, item_name, level)": enhance_items,
        "inventory (user_id, item_name, quantity)": inventory,
        "stocks (symbol, current_price, previous_price)": stocks,
        "price_history (symbol, price, recorded_at)": price_history,
        "portfolio (user_id, symbol, quantity, avg_price)": portfolio,
        "delisted_notices (user_id, symbol)": delisted,
        "market_state (id, state, state_ends_at, override_state, override_end)":
            [(1, *row) for row in market_state],
        "warnings (guild_id, user_id, count, restriction_until)": warnings,
        "warning_logs (guild_id, user_id, entry)": warning_logs,
        "suggestions (user_id, content, created_at)": suggestions,
        "suggestion_admins (user_id)": admins,
    }


# ───────────── DB 적재 ─────────────

async def migrate(conn: asyncpg.Connection, tables: dict[str, list[tuple]], reset: bool) -> None:
    async with conn.transaction():
        if reset:
            await conn.execute(f"DROP TABLE IF EXISTS {', '.join(ALL_TABLES)} CASCADE")
        else:
            leftovers = await conn.fetch(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = ANY($1::text[])",
                ALL_TABLES,
            )
            for r in leftovers:
                if await conn.fetchval(f"SELECT EXISTS (SELECT 1 FROM {r['table_name']})"):
                    raise SystemExit(
                        f"❌ DB 에 이미 데이터가 있습니다 ({r['table_name']}). "
                        "전부 지우고 다시 옮기려면 --reset 을 붙이세요."
                    )
            # 비어 있는 예전 테이블은 구조가 다를 수 있으니 지우고 새로 만든다.
            if leftovers:
                await conn.execute(f"DROP TABLE IF EXISTS {', '.join(ALL_TABLES)} CASCADE")

        await conn.execute(db.SCHEMA_PATH.read_text(encoding="utf-8"))

        for target, rows in tables.items():
            if not rows:
                continue
            n = len(rows[0])
            placeholders = ", ".join(f"${i}" for i in range(1, n + 1))
            await conn.executemany(f"INSERT INTO {target} VALUES ({placeholders})", rows)


async def main() -> None:
    parser = argparse.ArgumentParser(description="JSON → PostgreSQL 마이그레이션")
    parser.add_argument("--dry-run", action="store_true", help="DB 는 건드리지 않고 결과만 출력")
    parser.add_argument("--reset", action="store_true", help="봇 테이블을 전부 지우고 다시 옮기기")
    parser.add_argument("--data-dir", default=str(BASE_DIR), help="JSON 파일 폴더 (기본: 이 파일 위치)")
    args = parser.parse_args()

    tables = convert(Path(args.data_dir))
    for target, rows in tables.items():
        print(f"  {target.split(' ')[0]:<20} {len(rows):>6} 행")

    if args.dry_run:
        print("\n(--dry-run: DB 에는 아무것도 쓰지 않았습니다)")
        return

    load_dotenv(BASE_DIR / ".env")
    conn = await asyncpg.connect(os.environ["DATABASE_URL"], statement_cache_size=0)
    try:
        await migrate(conn, tables, reset=args.reset)
    finally:
        await conn.close()
    print("\n✅ 마이그레이션 완료")


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
