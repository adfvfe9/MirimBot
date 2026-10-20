-- 미림봇 DB 스키마 (PostgreSQL)
--
-- 봇이 켜질 때마다 실행되며, 여러 번 실행해도 안전하다 (IF NOT EXISTS).
-- 디스코드 ID(유저/서버/채널)는 64비트 정수라 BIGINT 로 저장한다.
-- 돈은 NUMERIC 으로 저장한다. (float 처럼 0.1 + 0.2 = 0.30000000000000004 같은 오차가 없다)
-- 시각은 모두 TIMESTAMPTZ(타임존 포함), 날짜는 한국 시간 기준 DATE 로 저장한다.


-- ───────────── 유저 (유저당 1행) ─────────────
-- 예전 JSON 파일들 중 "유저 ID → 값" 형태였던 것들을 전부 이 테이블 하나로 합쳤다.
CREATE TABLE IF NOT EXISTS users (
    user_id              BIGINT PRIMARY KEY,

    money                NUMERIC NOT NULL DEFAULT 0,      -- money_data.json (음수 = 빚)

    gamble_net           NUMERIC NOT NULL DEFAULT 0,      -- gamble_stats.json (도박 누적 손익)
    gamble_last_at       TIMESTAMPTZ,                     -- gamble_cooldowns.json

    welfare_last_date    DATE,                            -- welfare_data.json
    welfare_streak       INT     NOT NULL DEFAULT 0,

    consolation_date     DATE,                            -- consolation.json (위로금)
    bankruptcy_date      DATE,                            -- bankruptcy_data.json (파산)

    tokens               BIGINT  NOT NULL DEFAULT 0,      -- token_data.json
    token_price          NUMERIC NOT NULL DEFAULT 100,    -- 살 때마다 2배라 금방 커져서 NUMERIC

    deposit_amount       NUMERIC NOT NULL DEFAULT 0,      -- bank_system.json (적금 원금)
    deposit_start        TIMESTAMPTZ,
    unpaid_amount        NUMERIC NOT NULL DEFAULT 0,      -- 강제징수 미납금

    suggestion_last_at   TIMESTAMPTZ                      -- suggestions.json 의 last_time (건의 쿨타임)
);


-- ───────────── 은행 대출 (유저 1명이 여러 건) ─────────────
CREATE TABLE IF NOT EXISTS loans (
    id                BIGSERIAL PRIMARY KEY,
    user_id           BIGINT      NOT NULL,
    amount            NUMERIC     NOT NULL,               -- 남은 원금 (상환하면 줄어든다)
    taken_at          TIMESTAMPTZ NOT NULL,               -- 대출 시각 (24시간 뒤 강제징수)
    collected         BOOLEAN     NOT NULL DEFAULT FALSE, -- 강제징수 처리 여부
    collection_amount NUMERIC,                            -- 징수해야 했던 금액 (원금²)
    collected_amount  NUMERIC,                            -- 실제로 징수한 금액
    unpaid_from_loan  NUMERIC,                            -- 못 걷어서 미납금으로 넘어간 금액
    collected_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS loans_user_idx ON loans (user_id, id);


-- ───────────── 강화 아이템 / 상점 아이템 ─────────────
CREATE TABLE IF NOT EXISTS enhance_items (            -- enhance_data.json
    user_id   BIGINT NOT NULL,
    item_name TEXT   NOT NULL,
    level     INT    NOT NULL,
    PRIMARY KEY (user_id, item_name)
);

CREATE TABLE IF NOT EXISTS inventory (                -- items.json (상점에서 산 아이템)
    user_id   BIGINT NOT NULL,
    item_name TEXT   NOT NULL,
    quantity  INT    NOT NULL,
    PRIMARY KEY (user_id, item_name)
);


-- ───────────── 주식 ─────────────
-- 종목별 기준가/변동폭(stock_info)은 설정값이라 main.py 에 그대로 둔다.
CREATE TABLE IF NOT EXISTS stocks (                   -- stock_prices.json
    symbol         TEXT PRIMARY KEY,
    current_price  NUMERIC NOT NULL,
    previous_price NUMERIC NOT NULL
);

-- 1분마다 종목별로 한 줄씩 쌓고, 종목당 최근 1440개(24시간)만 남긴다.
CREATE TABLE IF NOT EXISTS price_history (            -- price_history.json
    id          BIGSERIAL PRIMARY KEY,
    symbol      TEXT        NOT NULL,
    price       NUMERIC     NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS price_history_symbol_idx ON price_history (symbol, id);

CREATE TABLE IF NOT EXISTS portfolio (                -- portfolio.json
    user_id   BIGINT  NOT NULL,
    symbol    TEXT    NOT NULL,
    quantity  BIGINT  NOT NULL,
    avg_price NUMERIC NOT NULL,
    PRIMARY KEY (user_id, symbol)
);

-- 상장폐지로 주식을 잃은 유저에게 다음 %주식확인 때 보여줄 알림
CREATE TABLE IF NOT EXISTS delisted_notices (         -- delisted_stocks.json
    id      BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    symbol  TEXT   NOT NULL
);

-- 시장 상태: 항상 1행 (id = 1)
-- JSON 에서는 "남은 초"를 매초 저장했지만, 여기서는 "언제 끝나는지"를 저장해서 매초 쓸 필요가 없다.
CREATE TABLE IF NOT EXISTS market_state (             -- market_state.json
    id             INT PRIMARY KEY CHECK (id = 1),
    state          TEXT        NOT NULL,              -- BULL / BEAR
    state_ends_at  TIMESTAMPTZ NOT NULL,
    override_state TEXT,                              -- HYPER_BULL / CRASH (관리자 이벤트)
    override_end   TIMESTAMPTZ
);


-- ───────────── 경고 ─────────────
CREATE TABLE IF NOT EXISTS warnings (                 -- warnings.json
    guild_id          BIGINT NOT NULL,
    user_id           BIGINT NOT NULL,
    count             INT    NOT NULL DEFAULT 0,
    restriction_until TIMESTAMPTZ,                    -- 이용제한 역할 자동 해제 시각
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS warning_logs (             -- warnings.json 의 reasons 목록
    id       BIGSERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    user_id  BIGINT NOT NULL,
    entry    TEXT   NOT NULL                          -- "2026-10-20 10:00:00 - 사유 (처벌: ...)"
);
CREATE INDEX IF NOT EXISTS warning_logs_user_idx ON warning_logs (guild_id, user_id, id);


-- ───────────── 건의 ─────────────
CREATE TABLE IF NOT EXISTS suggestions (              -- suggestions.json 의 logs
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT      NOT NULL,
    content    TEXT        NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS suggestion_admins (        -- suggestion_admins.json
    user_id BIGINT PRIMARY KEY
);



-- ───────────── 정리: 삭제한 기능이 DB 에 남긴 흔적 지우기 ─────────────
-- 출석 체크 기능을 없애면서 쓰지 않게 된 컬럼/테이블. (이미 없으면 아무 일도 안 한다)
ALTER TABLE users DROP COLUMN IF EXISTS checkin_last_date;
ALTER TABLE users DROP COLUMN IF EXISTS checkin_level;
DROP TABLE IF EXISTS attendance_channels;
