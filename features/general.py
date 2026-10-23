"""일반 명령어: 시간, 패치노트, 급식, 도움말, 청소, 장난 명령어"""
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
        title="📜 패치노트 v1.3.1 — 제물 강화",
        description="v1.3.1 변경 사항과 v1.3.0 내용이에요. 자세한 명령어는 `%도움말`에서!",
        color=0xf1c40f  # 노란색
    )
    embed.add_field(
        name="🔥 [v1.3.1] 제물 강화 `%강화 <아이템> [목표] <제물...>`",
        value=(
            "- 다른 강화 아이템을 제물로 바치면 **다음 한 번의 강화** 성공률이 올라가요 (제물은 성공/실패 상관없이 사라짐)\n"
            "- 제물마다 성공률 × (1 + 제물 판매가 ÷ 아이템 판매가). **같은 레벨 제물이면 2배**, 높은 제물일수록 더 세요\n"
            "- 개수 제한 없음 (성공률은 100%까지). 예) `%강화 칼 방패 창`, 목표 자동과 같이: `%강화 칼 9 방패`"
        ),
        inline=False
    )
    embed.add_field(
        name="🛠️ [v1.3.1] 능력 변경",
        value=(
            "- 🛡️ **파괴 방지**: 파괴될 때 **파괴 대신 한 단계 하락**으로 바뀌고 상한이 없어졌어요 (100% = 파괴 없음)\n"
            "- ⌛ 끝말잇기 시간 → 📅 **끝말잇기 하루 한도** (하루 최대 1.5만 +N%). 이미 붙은 ⌛는 같은 등급으로 자동 변경\n"
            "- 🔤 끝말잇기 보상은 이제 단어당 보상만 올려요"
        ),
        inline=False
    )
    embed.add_field(
        name="✨ [v1.3.0] 강화 능력 슬롯",
        value=(
            "- **+5 / +7 / +9 / +11 / +13**에 처음 도달하면 슬롯이 열리고 능력이 하나 붙어요\n"
            "- 등급 ⚪일반 🔵희귀 🟣영웅 🟡전설, 수치는 등급 범위 안에서 랜덤. 아이템 레벨이 높을수록 좋은 등급이 잘 나와요\n"
            "- 능력 13종: 💥대성공 🛡️파괴 방지 🍀하락 방지 🚀배율 한계 돌파 🧯청산 보험 ⏱️단타 시간 단축 💸판매 수수료 할인 "
            "✊가위바위보 부활 🎰도박 꽝 환급 📅끝말잇기 하루 한도 🪙퀴즈 토큰 확률 🍚기초수급 보상 🔤끝말잇기 보상\n"
            "- 같은 능력은 모든 아이템에서 합쳐져요 (능력마다 상한 있음)\n"
            "- `%강화능력설정 <아이템>` 🔒잠금 / 🔄리롤 · `%리롤 <아이템>` · `%내능력`\n"
            "- 리롤은 🪙토큰 1개 + 잠근 슬롯 하나당 1개"
        ),
        inline=False
    )
    embed.add_field(
        name="🕶️ [v1.3.0] 암시장 `%암시장`",
        value=(
            "- 유저끼리 강화 아이템을 **능력째로** 사고팔아요. 페이지 넘기고, 골라서 🛒구매, 💰판매는 가격 입력창(예상 가격 표시)\n"
            "- 판매 수수료 10%, 가격은 1,000 ~ 봇 판매가의 20배, 1인 3개까지, 24시간 지나면 돌아와요"
        ),
        inline=False
    )
    embed.add_field(
        name="🪙 퀴즈 토큰",
        value="- 퀴즈를 맞히면 확률로 토큰 1개 (하 10% / 중 30% / 상 60%). 리롤 재료로 써요",
        inline=False
    )
    embed.add_field(
        name="📈 주식이 바뀌었어요",
        value=(
            "- 기준가로 금방 돌아오던 가격이 이제 **오르든 내리든 그대로 이어져요** (몇 주에 걸쳐 아주 천천히만 돌아와요)\n"
            "- 1분마다 흔들리는 폭이 커졌고, **뉴스가 뜨는 순간 가격이 한 번에 튀어요**. 뉴스를 보고 들어가면 이미 움직인 뒤!\n"
            "- 부도 위기는 15~30% 폭락 후 확률로 상장폐지. 거품이 꺼지면 모든 종목이 한 번에 떨어져요"
        ),
        inline=False
    )
    embed.add_field(
        name="⚖️ 레버리지",
        value=(
            "- 최대 배율 **10배** (🚀 능력으로 최대 15배)\n"
            "- 진입 수수료 0.5% 추가 (정리 0.5%는 그대로)\n"
            "- **보유 비용**: 거래 규모의 시간당 0.1%가 증거금에서 빠져요. 오래 들고 있을수록 청산가가 가까워져요"
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
        response = requests.get(url)
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
