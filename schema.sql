-- 봇 DB 스키마 (PostgreSQL)
-- 여러 번 실행해도 안전하다 (IF NOT EXISTS).
-- 디스코드 ID(snowflake)는 64비트 정수라 BIGINT로 저장한다. (JSON처럼 문자열 아님)
-- 돈은 NUMERIC으로 저장해서 3001260628.1400003 같은 float 오차가 생기지 않는다.

-- ───────────── 유저 (유저당 1행) ─────────────
-- money_data / bank_data / gamble_stats / gamble_cooldowns / welfare_data /
-- checkin_cooldowns / consolation / token_data 8개 JSON을 이 테이블 하나로 합쳤다.
CREATE TABLE IF NOT EXISTS users (
    user_id            BIGINT PRIMARY KEY,
    money              NUMERIC(24, 2) NOT NULL DEFAULT 0,   -- 음수 허용 (빚)
    savings            NUMERIC(24, 2) NOT NULL DEFAULT 0,   -- 구 bank_data.json (통장)
    gamble_net         NUMERIC(24, 2) NOT NULL DEFAULT 0,   -- 도박 누적 손익
    gamble_last_at     TIMESTAMPTZ,                         -- 도박 쿨타임 기준 시각
    welfare_last_claim DATE,
    welfare_streak     INT NOT NULL DEFAULT 0,
    checkin_last_date  DATE,
    checkin_streak     INT NOT NULL DEFAULT 0,              -- 구 streak_level
    consolation_date   DATE,                                -- 위로금 마지막 수령일
    tokens             BIGINT NOT NULL DEFAULT 0,
    token_price        INT NOT NULL DEFAULT 100
);

-- ───────────── 은행 (대출/예금) ─────────────
CREATE TABLE IF NOT EXISTS bank_accounts (
    user_id        BIGINT PRIMARY KEY,
    credit_score   NUMERIC(10, 2) NOT NULL DEFAULT 1000,
    loan_amount    NUMERIC(24, 2) NOT NULL DEFAULT 0,
    loan_date      TIMESTAMPTZ,
    deposit_amount NUMERIC(24, 2) NOT NULL DEFAULT 0,
    deposit_start  TIMESTAMPTZ
);

-- ───────────── 강화 / 아이템 ─────────────
CREATE TABLE IF NOT EXISTS enhance_items (
    user_id   BIGINT NOT NULL,
    item_name TEXT   NOT NULL,
    level     INT    NOT NULL CHECK (level >= 0),
    PRIMARY KEY (user_id, item_name)
);

CREATE TABLE IF NOT EXISTS inventory (
    user_id   BIGINT NOT NULL,
    item_name TEXT   NOT NULL,
    quantity  INT    NOT NULL CHECK (quantity >= 0),
    PRIMARY KEY (user_id, item_name)
);

-- ───────────── 주식 ─────────────
-- 종목별 base/limit 같은 설정값(stock_info)은 코드에 그대로 둔다.
CREATE TABLE IF NOT EXISTS stocks (
    symbol         TEXT PRIMARY KEY,
    current_price  NUMERIC(18, 2) NOT NULL,
    previous_price NUMERIC(18, 2) NOT NULL
);

-- 1분마다 한 행씩 쌓고, 종목당 최근 1440개만 남기도록 코드에서 정리한다.
-- 기존 JSON에는 시각이 없어서 이전 데이터는 recorded_at이 NULL이다. (순서는 id로 보장)
CREATE TABLE IF NOT EXISTS price_history (
    id          BIGSERIAL PRIMARY KEY,
    symbol      TEXT NOT NULL,
    price       NUMERIC(18, 2) NOT NULL,
    recorded_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_price_history_symbol_id ON price_history (symbol, id DESC);

CREATE TABLE IF NOT EXISTS portfolio (
    user_id   BIGINT NOT NULL,
    symbol    TEXT   NOT NULL,
    quantity  BIGINT NOT NULL CHECK (quantity > 0),
    avg_price NUMERIC(18, 4) NOT NULL,
    PRIMARY KEY (user_id, symbol)
);

-- 상장폐지로 주식을 잃은 유저에게 보여줄 알림 대기열
CREATE TABLE IF NOT EXISTS delisted_notices (
    id      BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    symbol  TEXT   NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_delisted_notices_user ON delisted_notices (user_id);

-- 시장 상태: 항상 1행만 존재한다.
-- remaining_seconds(저장 시점마다 낡는 값) 대신 종료 시각을 저장한다.
CREATE TABLE IF NOT EXISTS market_state (
    id             INT PRIMARY KEY CHECK (id = 1),
    state          TEXT NOT NULL DEFAULT 'BULL',
    state_ends_at  TIMESTAMPTZ NOT NULL,
    override_state TEXT,
    override_end   TIMESTAMPTZ
);

-- ───────────── 경고 ─────────────
CREATE TABLE IF NOT EXISTS user_warnings (
    guild_id          BIGINT NOT NULL,
    user_id           BIGINT NOT NULL,
    count             INT    NOT NULL DEFAULT 0 CHECK (count >= 0),
    restriction_until TIMESTAMPTZ,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS warning_logs (
    id         BIGSERIAL PRIMARY KEY,
    guild_id   BIGINT NOT NULL,
    user_id    BIGINT NOT NULL,
    entry      TEXT   NOT NULL,           -- 기존 reasons 문자열 그대로 ("시각 - 사유 (처벌: ...)")
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_warning_logs_user ON warning_logs (guild_id, user_id, id);

-- ───────────── 건의 / 설정 ─────────────
-- 건의 쿨타임은 별도 컬럼 없이 "그 유저의 가장 최근 created_at"으로 계산한다.
CREATE TABLE IF NOT EXISTS suggestions (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL,
    content    TEXT   NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_suggestions_user ON suggestions (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS suggestion_admins (
    user_id BIGINT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS attendance_channels (
    guild_id   BIGINT PRIMARY KEY,
    channel_id BIGINT NOT NULL
);
