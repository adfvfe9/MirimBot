"""일반 명령어: 시간, 패치노트, 급식, 도움말, 청소, 장난 명령어"""
import asyncio
import os
import re

import discord
import requests
from discord.ext import commands

import database as db
from bot import client


@client.command(aliases=['시간'])
async def timeget(ctx):
    await ctx.message.delete()
    now = db.now()  # 한국 시간
    current_time = now.strftime("%Y년 %m월 %d일 %H시 %M분 %S초")
    embed = discord.Embed(title="현재 시간 ⏰", description=f"{current_time}", color=0x3498db)
    await ctx.send(embed=embed)

@client.command(aliases=['패치노트'])
async def patchnote(ctx):
    await ctx.message.delete()
    embed = discord.Embed(
        title="📜 패치노트 v1.3.5.1 — 속도 개선 · 강화 수정",
        description="v1.3.5.1 변경 사항과 v1.3 전체 요약이에요. 버전은 a.b.c.d (대격변 · 큰 기능 · 기능 추가 · 수정). 자세한 명령어는 `%도움말`에서!",
        color=0xf1c40f  # 노란색
    )
    embed.add_field(
        name="⚡ [v1.3.5.1] 속도 개선 · 강화 수정",
        value=(
            "- 버튼을 누르면 화면이 바로 바뀌어요 (디스코드 요청 2번 → 1번). 그래프 · 급식이 다른 명령어를 멈추지 않아요\n"
            "- 자동 강화를 몰아서 계산해서 훨씬 빨라졌고, 진행 상황이 메시지에 실시간으로 보여요\n"
            "- 강화 패널을 연타하거나 같은 아이템 패널 두 개를 쓰면 목표를 넘겨 강화되던 문제 수정\n"
            "- `%핑` 디스코드 · DB · 봇 멈춤 시간 재기 · 관리자용 `%로그` (모든 명령어 / 버튼 기록)"
        ),
        inline=False
    )
    embed.add_field(
        name="🗣️ [v1.3.5] TTS `%읽어`",
        value=(
            "- `%읽어` 내가 있는 통화방으로 봇이 와서 **이 채널의 채팅을 읽어줘요** · `%나가` 하면 나가요\n"
            "- **노래와 동시에 들려요** (읽는 동안 노래 소리를 살짝 줄여요) · `%정지`는 이제 노래만 멈춰요\n"
            "- 명령어 · 봇 메시지는 안 읽고, 80자가 넘는 글은 안 읽고 ❌ 를 달아요\n"
            "- `%줄임말설정 ㅇㅈ 인정` 서버마다 글자 / 초성 / 기호 읽는 법 정하기 (`-` 면 안 읽기) · `%줄임말` 목록"
        ),
        inline=False
    )
    embed.add_field(
        name="🏅 [v1.3.4] 칭호 `%칭호`",
        value=(
            "- 조건을 채우면 얻는 **칭호 28개** (재산 · 강화 · 놀이 · 투자 · 두뇌 · 기타). 진행도도 보여요\n"
            "- `%칭호 [@유저]` 남의 칭호도 보기 · 분류 고르기 / 보유한 것만 보기 버튼\n"
            "- `%칭호장착 <이름>` 하면 `%자산` · `%자산랭킹`에 표시 · `%칭호해제` · `%칭호랭킹`\n"
            "- 한 번 얻으면 돈이 줄거나 파산해도 남아요 (기록은 v1.2.8부터 세요)"
        ),
        inline=False
    )
    embed.add_field(
        name="📈 [v1.3.4] 자산그래프 · 🎵 음악",
        value=(
            "- `%자산그래프 [@유저...] [일]` 1시간마다 기록한 순자산 변화 (최근 30일, 여러 명 비교)\n"
            "- `%재생 <유튜브 링크 | 제목>` 내가 있는 통화방으로 봇이 와서 재생 · 재생 중이면 대기열에 추가\n"
            "- `%스킵` `%일시정지` `%다시재생` `%정지` `%대기열` `%지금곡` `%볼륨` (봇과 같은 통화방에서만)"
        ),
        inline=False
    )
    embed.add_field(
        name="✨ [v1.3.3.1] 강화 능력 상한 해제",
        value=(
            "- 강화에 돈이 많이 들어서 **모든 능력의 상한을 풀었어요.** 같은 능력은 모을수록 끝없이 쌓여요\n"
            "- 숫자가 넘으면 말이 안 되는 것만 한계가 있어요: 🎰 꽝 환급 · 🧯 청산 보험 100%, ⏱️ 단타 시간 단축 30분\n"
            "- 💥 대성공은 여전히 결과가 +6 이하일 때만 · `%내능력`에서 합친 효과 확인"
        ),
        inline=False
    )
    embed.add_field(
        name="⛏️ [v1.3.3] 코인 채굴 `%채굴`",
        value=(
            "- **1시간마다 블록 하나**: 서버 전체 블록 보상(0.1 BTC)을 켜진 채굴기 해시 비율로 나눠 가져요\n"
            "- 채굴기 1대 5만 byte (1인 최대 3대) · `%채굴기업그레이드`로 Lv5까지 (해시 1→5, 해시당 전기세는 싸져요)\n"
            "- 켜 두면 블록마다 전기세 2,000~6,000 byte/대. 돈이 모자라면 자동으로 꺼져요\n"
            "- **336블록(2주)마다 반감기** · `%채굴켜기` `%채굴끄기` `%채굴랭킹`"
        ),
        inline=False
    )
    embed.add_field(
        name="₿ [v1.3.2] 비트코인 `%코인`",
        value=(
            "- **토큰으로만** 사고파는 코인이에요. 가격도 토큰 단위 (시작 1 BTC = 10 토큰)\n"
            "- 주식보다 훨씬 거칠어요: 하루 흔들림 약 25% + 4~8시간마다 코인 뉴스로 ±5~20% 점프\n"
            "- `%코인구매 <토큰>` · `%코인판매 [개수|전부]` · `%코인확인` · `%코인그래프` · `%코인랭킹`\n"
            "- 수수료 살 때 1% / 팔 때 1%. 가격이 너무 낮거나 높아지면 액면 조정(가치는 그대로)"
        ),
        inline=False
    )
    embed.add_field(
        name="🪙 [v1.3.2] 토큰",
        value=(
            "- 토큰 구매 가격이 **하루에 4배씩 다시 떨어져요** (최소 100). 살 때마다 2배는 그대로\n"
            "- `%암시장`에서 **토큰도 사고팔 수 있어요** (개수 + 개당 가격, 개당 100 ~ 10만)\n"
            "- 새 능력 🔻 **토큰 가격 하락 가속**: 하루 4배 하락에 ×1.0~2.0"
        ),
        inline=False
    )
    embed.add_field(
        name="✨ [v1.3.2] 능력 슬롯이 +3부터",
        value=(
            "- 슬롯이 **+3 / +5 / +7 / +9 / +11 / +13** (6칸)에서 열려요\n"
            "- 이미 있는 아이템은 능력이 그대로고, 새로 생긴 빈 칸은 자동으로 채워졌어요"
        ),
        inline=False
    )
    embed.add_field(
        name="🔥 [v1.3.1] 제물 강화 · 능력 변경",
        value=(
            "- `%강화 <아이템> [목표] <제물...>`: 제물마다 다음 강화 성공률 ×(1 + 제물 판매가 ÷ 아이템 판매가), 같은 레벨이면 2배\n"
            "- 🛡️ 파괴 방지 = 파괴 대신 하락 (상한 없음) · ⌛ → 📅 끝말잇기 하루 한도"
        ),
        inline=False
    )
    embed.add_field(
        name="📌 [v1.3.0] 요약",
        value=(
            "- ✨ 강화 능력 14종 (`%강화능력설정`, `%리롤`, `%내능력`) · 🕶️ `%암시장` · 🪙 퀴즈 토큰\n"
            "- 📈 주식: 오르든 내리든 그대로 이어지고, 뉴스가 뜨는 순간 한 번에 튀어요\n"
            "- ⚖️ 레버리지 최대 10배, 진입 수수료 0.5%, 보유 비용 시간당 0.1%"
        ),
        inline=False
    )
    embed.set_footer(text="업데이트: 2026-10-23")
    await ctx.send(embed=embed)

@client.command(aliases=['급식'])
async def school_meal(ctx):
    await ctx.message.delete()

    api_key = os.getenv("NEIS_API_KEY")           # .env 의 나이스 API 키
    school_code = '7011569'                       # 미림마이스터고
    edu_office_code = 'B10'                       # 서울교육청
    today = db.today().strftime("%Y%m%d")         # 서버가 해외에 있어도 한국 날짜 기준

    if not api_key:
        await ctx.send("급식 API 키가 설정되지 않았어요 🥲 (.env 의 NEIS_API_KEY)")
        return

    url = f"https://open.neis.go.kr/hub/mealServiceDietInfo?" \
f"KEY={api_key}&Type=json&ATPT_OFCDC_SC_CODE={edu_office_code}&SD_SCHUL_CODE={school_code}&MLSV_YMD={today}"

    try:
        # requests 는 기다리는 동안 봇 전체를 멈추게 해서 다른 스레드에서 부른다. 나이스가 안 받으면 5초에 포기
        response = await asyncio.to_thread(requests.get, url, timeout=5)
        response.raise_for_status()
        data = response.json()

        if 'mealServiceDietInfo' not in data:
            await ctx.send("오늘은 급식 정보가 없어요 🥲 (주말/공휴일일 수 있어요)")
            return

        meal_list = data['mealServiceDietInfo'][1]['row']

        meals_text = []
        for meal in meal_list:
            meal_name = meal['MMEAL_SC_NM']  # 아침, 점심, 저녁
            meal_info = meal['DDISH_NM']
            meal_info = meal_info.replace('<br/>', '\n')
            meal_info = re.sub(r'\([^)]*\)', '', meal_info)  # 괄호 안 내용 제거

            # 식사 구분별 이모지
            if '조식' in meal_name or '아침' in meal_name:
                prefix = "🌅 **[조식]**"
            elif '중식' in meal_name or '점심' in meal_name:
                prefix = "🍱 **[중식]**"
            elif '석식' in meal_name or '저녁' in meal_name:
                prefix = "🌙 **[석식]**"
            else:
                prefix = f"**[{meal_name}]**"

            meals_text.append(f"{prefix}\n{meal_info}")

        final_meal_info = "\n\n".join(meals_text)

        embed = discord.Embed(
            title="🍴 오늘의 급식 🍴",
            description=final_meal_info,
            color=0x2ecc71
        )
        await ctx.send(embed=embed)

    except requests.exceptions.RequestException as e:
        await ctx.send("급식 API 서버에 연결할 수 없어요 🥲")
        print(f"[급식] RequestException: {e}")

    except Exception as e:
        await ctx.send("오늘의 급식 정보를 불러오지 못했어요 🥲")
        print(f"[급식] Exception: {e}")


@client.command(aliases=["도움말", "가이드"])
async def 명령어(ctx):
    await ctx.message.delete()

    embed = discord.Embed(
        title="📘 명령어 목록 (노션)",
        description="모든 명령어는 아래 노션 페이지에서 확인할 수 있습니다.",
        color=discord.Color.blue(),
        url="https://www.notion.so/20cf2c1e9859807781bac6f3ce06c317?v=20cf2c1e98598080afbc000cdbab9133"
    )
    embed.add_field(
        name="🔗 명령어 확인하러 가기",
        value="[👉 노션 링크 열기](https://www.notion.so/20cf2c1e9859807781bac6f3ce06c317?v=20cf2c1e98598080afbc000cdbab9133)",
        inline=False
    )
    embed.set_footer(text="노션에서 실시간으로 최신 명령어가 갱신됩니다.")

    await ctx.send(embed=embed)


@client.command(aliases=["청소"])
@commands.has_permissions(administrator=True)
async def clean(ctx, amount: int):
    # 명령어 메시지 + 그 위의 메시지 amount 개를 지운다 (14일 지난 메시지는 디스코드가 막아서 못 지움)
    await ctx.channel.purge(limit=amount + 1)

@client.command(aliases=["박준현", "ㅄ", "영포티"])
async def fourty(ctx, member: discord.Member = None):
    embed = discord.Embed(
        title='영포티'
    )
    await ctx.send(embed = embed)

@client.command(aliases=["홍성재"])
async def goa(ctx, member: discord.Member = None):
    embed = discord.Embed(
            title='고아',
            description=(
                        "김미영\n"
                        "홍창균\n"
                        "펑"
            ),
            color=discord.Color.gold()
        )
    await ctx.send(embed = embed)
