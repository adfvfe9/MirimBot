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
        title="📜 패치노트 v1.2.6 — 끝말잇기 & 선착순 퀴즈",
        description="공짜로 돈 버는 방법이 두 개 늘었어요! 자세한 명령어는 `%도움말`에서!",
        color=0xf1c40f  # 노란색
    )
    embed.add_field(
        name="🔤 끝말잇기 `%끝말잇기`",
        value=(
            "- 명령어를 치면 **스레드**가 새로 생기고 거기서 진행돼요\n"
            "- 봇 난이도 🟢쉬움 · 🟡보통 · 🟠어려움 · 🔴지옥 — 어려울수록 보상 UP (×0.05 ~ ×2)\n"
            "- 📏 긴 단어일수록, 오래 이을수록 보상 UP\n"
            "- 🎯 **미션 글자**가 들어간 단어를 내면 보너스, 봇을 이기면 승리 보너스\n"
            "- 🧪 `%끝말잇기 연습`: 보상 없이 연습 (난이도 선택 가능)\n"
            "- 👥 `%끝말잇기 같이`: 친구들과 다같이 (2~8명, 마지막까지 남으면 우승 보너스)\n"
            "- 턴당 20초, 두음법칙 OK, `그만`으로 끝내기 · 하루 최대 **1만 5천 byte**"
        ),
        inline=False
    )
    embed.add_field(
        name="❓ 선착순 퀴즈",
        value=(
            "- 1~2시간마다(8시~24시) 퀴즈 채널에 문제가 떠요. **제일 먼저 맞힌 사람**이 보상!\n"
            "- 과목: 🧮수학 · 📚국어 · 🔠영어 · 🏛️사회 · 📜한국사 · 🔬과학 · 💡상식\n"
            "- 수학은 대수·미적분 I 범위, **그래프 보고 푸는 문제**도 나와요\n"
            "- 난이도 하(1분, 1.5천~2.5천) · 중(5분, 3천~5천) · 상(10분, 6천~1만)\n"
            "- 객관식은 번호로 한 번만, 숫자 답은 3번까지, 끝나면 해설도 보여줘요\n"
            "- 문제가 매번 새로 만들어져서 같은 문제가 거의 안 나와요"
        ),
        inline=False
    )
    embed.add_field(
        name="⚖️ 밸런스 변경",
        value=(
            "- 🔨 **강화 확률 조정**: +7부터 파괴 가능 (최대 10%), +13 성공 1%\n"
            "  판매가 UP: +10 160만 · +11 1,200만 · +12 1.7억 · **+13 80억**\n"
            "- 📈 `%주가그래프 [주식] [분]`: 최근 60분은 무료, 60분 더 볼 때마다 2,000 byte (최대 24시간)\n"
            "- 💸 `%파산`: 연체 전 은행 대출만 있어도 파산할 수 있어요 (빚 = 미납금 + 남은 대출)"
        ),
        inline=False
    )
    embed.add_field(
        name="🛠️ 수정",
        value="- 은행 대출 한도 표기를 실제 값(**5만**)으로 바로잡았어요",
        inline=False
    )
    embed.set_footer(text="업데이트: 2026-10-21")
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
