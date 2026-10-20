"""봇이 한 번에 하나만 돌게 하는 장치.

봇 두 개(예: 내 컴퓨터 + 호스팅 서버)가 동시에 켜지면, 주가가 1분에 두 번 갱신되고
(주가 그래프가 지그재그가 됨) 명령어에도 두 번 대답한다.

- 실행 중인 봇은 HEARTBEAT_SECONDS 마다 DB(bot_state)에 "나 살아 있어" 신호를 남긴다.
- 새로 켜진 봇은 다른 봇의 신호가 살아 있으면 디스코드에 접속하지 않고 기다린다.
  (바로 종료하지 않는 이유: 서버 재시작 직후에는 방금 꺼진 봇의 신호가 잠깐 남아 있는데,
   그때 종료하면 호스팅 패널이 "너무 자주 꺼진다"며 자동 재시작을 포기할 수 있다.)
- 신호가 STALE_SECONDS 동안 갱신되지 않으면 꺼진 것으로 보고 이어받는다.
"""
import asyncio
import uuid

import database as db

HEARTBEAT_SECONDS = 30
STALE_SECONDS = 90
KEY = "running_instance"

INSTANCE_ID = uuid.uuid4().hex[:12]


async def try_claim() -> bool:
    """신호를 남긴다. 내가 주인이거나 기존 신호가 오래됐으면 성공(True).
    시각은 컴퓨터마다 시계가 조금씩 달라서, 기록과 비교 모두 DB 시계(now())로 한다."""
    row = await db.pool().fetchval(
        """
        INSERT INTO bot_state (key, value) VALUES ($1, $2 || '|' || now()::text)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        WHERE split_part(bot_state.value, '|', 1) = $2
           OR split_part(bot_state.value, '|', 2)::timestamptz < now() - make_interval(secs => $3)
        RETURNING value
        """,
        KEY, INSTANCE_ID, STALE_SECONDS,
    )
    return row is not None


async def wait_until_only_one():
    """다른 봇이 돌고 있으면 꺼질 때까지 기다린다."""
    warned = False
    while not await try_claim():
        if not warned:
            print(
                "⚠️ 다른 곳에서 미림봇이 이미 실행 중이에요. (내 컴퓨터와 서버에서 동시에 켰는지 확인하세요)\n"
                f"   그 봇이 꺼지면 {STALE_SECONDS}초 안에 이 봇이 이어서 시작합니다. 기다리는 중..."
            )
            warned = True
        await asyncio.sleep(HEARTBEAT_SECONDS / 2)
    print(f"✅ 실행 권한 획득 (instance {INSTANCE_ID})")


async def heartbeat(client):
    """살아 있다는 신호를 계속 남긴다. 다른 봇에게 자리를 뺏기면 이 봇을 끈다."""
    while not client.is_closed():
        await asyncio.sleep(HEARTBEAT_SECONDS)
        try:
            if not await try_claim():
                print("⚠️ 다른 미림봇이 실행 권한을 가져갔어요. 중복 실행을 막기 위해 이 봇을 종료합니다.")
                await client.close()
                return
        except Exception as e:
            # DB 가 잠깐 안 되는 건 다음 신호 때 다시 시도
            print(f"[실행 신호 오류] {type(e).__name__}: {e}")
