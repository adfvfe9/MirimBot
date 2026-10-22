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

    money                NUMERIC NOT NULL DEFAULT 0,      -- 잔액 (항상 0 이상, 빚은 unpaid_amount 로)

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
    unpaid_amount        NUMERIC NOT NULL DEFAULT 0,      -- 미납금(빚). 돈이 들어오면 자동으로 징수된다 (아래 트리거)

    suggestion_last_at   TIMESTAMPTZ,                     -- suggestions.json 의 last_time (건의 쿨타임)

    rps_date             DATE,                            -- 가위바위보 하루 판수 제한
    rps_count            INT     NOT NULL DEFAULT 0,
    send_date            DATE,                            -- 송금 하루 한도
    send_total           NUMERIC NOT NULL DEFAULT 0,
    wordchain_date       DATE,                            -- 끝말잇기 하루 보상 한도
    wordchain_earned     NUMERIC NOT NULL DEFAULT 0
);

-- 예전에 만들어진 users 테이블에 새 컬럼 추가 (이미 있으면 아무 일도 안 한다)
ALTER TABLE users ADD COLUMN IF NOT EXISTS rps_date   DATE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS rps_count  INT     NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS send_date  DATE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS send_total NUMERIC NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS wordchain_date   DATE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS wordchain_earned NUMERIC NOT NULL DEFAULT 0;

-- 미납금 자동 징수
-- users 행이 UPDATE 될 때마다 자동으로 실행된다. (database.py 는 돈을 항상 UPDATE 로 바꾼다)
--   1) 잔액이 마이너스가 되면 → 그만큼 미납금으로 옮기고 잔액은 0
--   2) 미납금이 있는데 잔액이 생기면 → 잔액에서 미납금을 갚을 수 있는 만큼 바로 징수
-- 그래서 빚이 있는 동안에는 잔액이 늘 0 이라 돈을 쓸 수 없다.
CREATE OR REPLACE FUNCTION users_collect_debt() RETURNS trigger AS $$
DECLARE
    pay NUMERIC;
BEGIN
    IF NEW.money < 0 THEN
        NEW.unpaid_amount := NEW.unpaid_amount - NEW.money;
        NEW.money := 0;
    END IF;
    IF NEW.unpaid_amount > 0 AND NEW.money > 0 THEN
        pay := LEAST(NEW.money, NEW.unpaid_amount);
        NEW.money := NEW.money - pay;
        NEW.unpaid_amount := NEW.unpaid_amount - pay;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS users_collect_debt ON users;
CREATE TRIGGER users_collect_debt
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION users_collect_debt();


-- ───────────── 은행 대출 (유저 1명이 여러 건) ─────────────
CREATE TABLE IF NOT EXISTS loans (
    id                BIGSERIAL PRIMARY KEY,
    user_id           BIGINT      NOT NULL,
    amount            NUMERIC     NOT NULL,               -- 남은 상환액 (원금 + 이자 10%, 갚으면 줄어든다)
    taken_at          TIMESTAMPTZ NOT NULL,               -- 대출 시각 (24시간 안에 갚아야 한다)
    collected         BOOLEAN     NOT NULL DEFAULT FALSE, -- 연체 처리 여부 (처리되면 미납금으로 넘어감)
    collection_amount NUMERIC,                            -- 연체로 미납금에 더해진 금액 (남은 상환액 × 1.5)
    collected_amount  NUMERIC,                            -- (예전 규칙에서 쓰던 값)
    unpaid_from_loan  NUMERIC,                            -- (예전 규칙에서 쓰던 값)
    collected_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS loans_user_idx ON loans (user_id, id);


-- ───────────── 강화 아이템 / 상점 아이템 ─────────────
CREATE TABLE IF NOT EXISTS enhance_items (            -- enhance_data.json
    user_id   BIGINT NOT NULL,
    item_name TEXT   NOT NULL,
    level     INT    NOT NULL,                        -- +1 ~ +13
    PRIMARY KEY (user_id, item_name)
);
-- 예전 규칙(+0 ~ +300)으로 만든 아이템은 새 범위(+1 ~ +13)에 맞춘다.
UPDATE enhance_items SET level = LEAST(GREATEST(level, 1), 13) WHERE level < 1 OR level > 13;

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
-- 마지막으로 산 시각. 이 시각부터 30분 안에 팔면 단타 수수료가 붙는다. (features/stocks.py)
ALTER TABLE portfolio ADD COLUMN IF NOT EXISTS last_bought_at TIMESTAMPTZ;

-- 레버리지 포지션 (롱 / 숏)
-- 증거금 × 배율 만큼의 규모로 진입하고, 손실이 증거금의 90% 에 닿으면 강제청산된다.
CREATE TABLE IF NOT EXISTS stock_positions (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT      NOT NULL,
    symbol      TEXT        NOT NULL,
    side        TEXT        NOT NULL CHECK (side IN ('LONG', 'SHORT')),
    margin      NUMERIC     NOT NULL,                 -- 증거금 (내 돈)
    leverage    INT         NOT NULL,                 -- 배율 (1~10)
    entry_price NUMERIC     NOT NULL,                 -- 진입 가격
    opened_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS stock_positions_user_idx ON stock_positions (user_id, id);

-- 상장폐지, 강제청산처럼 유저가 없을 때 생긴 일을 다음 %주식확인 / %포지션 때 보여줄 알림
CREATE TABLE IF NOT EXISTS stock_notices (
    id      BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    message TEXT   NOT NULL
);

-- 예전 상장폐지 알림 테이블(delisted_notices)이 있으면 새 알림 테이블로 옮기고 지운다.
DO $$
BEGIN
    IF to_regclass('delisted_notices') IS NOT NULL THEN
        INSERT INTO stock_notices (user_id, message)
        SELECT user_id, '⚠️ `' || symbol || '` 주식은 상장폐지되어 자동 제거되었습니다.'
        FROM delisted_notices ORDER BY id;
        DROP TABLE delisted_notices;
    END IF;
END $$;

-- 주식 뉴스 (features/news.py). %뉴스 로 최근 기록을 본다.
CREATE TABLE IF NOT EXISTS news (
    id         BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind       TEXT        NOT NULL,                  -- good / bad / market_good / market_bad / bubble / default_risk
    symbol     TEXT,                                  -- 시장 전체 뉴스면 NULL
    headline   TEXT        NOT NULL,
    body       TEXT        NOT NULL
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


-- ───────────── 끝말잇기 랭킹 ─────────────
-- 봇과 1대1 (어려움 / 지옥) 한 판 최고 점수. 연습 모드는 기록하지 않는다.
CREATE TABLE IF NOT EXISTS wordchain_records (
    user_id     BIGINT      NOT NULL,
    difficulty  TEXT        NOT NULL,                  -- hard / hell
    best_score  INT         NOT NULL,                  -- 한 판 최고 점수
    best_words  INT         NOT NULL,                  -- 최고 점수를 낸 판에서 이은 단어 수
    games       INT         NOT NULL DEFAULT 1,        -- 기록된 판 수
    achieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),    -- 최고 점수를 낸 시각
    PRIMARY KEY (user_id, difficulty)
);
CREATE INDEX IF NOT EXISTS wordchain_records_rank_idx ON wordchain_records (difficulty, best_score DESC);


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



-- ───────────── 돈 기록 ─────────────
-- 돈이 들어오고 나간 기록. 어떤 활동으로 누가 얼마를 벌고 잃는지 밸런스를 보려고 남긴다.
-- amount 는 그 활동으로 바뀐 잔액 (들어오면 +, 나가면 -). 미납금 자동 징수는 따로 빼지 않는다.
CREATE TABLE IF NOT EXISTS money_log (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT      NOT NULL,
    source     TEXT        NOT NULL,                  -- stock_sell, futures_close, gamble ... (database.log_money 참고)
    amount     NUMERIC     NOT NULL,
    memo       TEXT,                                  -- 종목, 배율 같은 참고 정보
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS money_log_source_idx ON money_log (source, created_at);
CREATE INDEX IF NOT EXISTS money_log_user_idx ON money_log (user_id, created_at);


-- ───────────── 봇 운영 상태 ─────────────
-- 서버 연장 알림처럼 봇 자체가 기억해야 하는 값. (%초기화 로 지워지지 않는다)
CREATE TABLE IF NOT EXISTS bot_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);


-- ───────────── 정리: 삭제한 기능이 DB 에 남긴 흔적 지우기 ─────────────
-- 출석 체크 기능을 없애면서 쓰지 않게 된 컬럼/테이블. (이미 없으면 아무 일도 안 한다)
ALTER TABLE users DROP COLUMN IF EXISTS checkin_last_date;
ALTER TABLE users DROP COLUMN IF EXISTS checkin_level;
DROP TABLE IF EXISTS attendance_channels;
