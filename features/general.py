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
        title="📜 패치노트 v1.2.3 — 경제 대개편",
        description="재화 밸런스를 전부 다시 맞췄어요. 자세한 명령어는 `%도움말`에서!",
        color=0xf1c40f  # 노란색
    )
    embed.add_field(
        name="✨ 새로운 기능",
        value=(
            "- 🔨 **강화 개편**: 피파 인생강화 스타일, +1~+13, +7부터 파괴 위험 (`%강화확률`)\n"
            "- 🎢 **레버리지**: `%롱` `%숏` `%포지션` `%청산` (최대 5배)\n"
            "- 🏆 **순자산 랭킹**: `%자산` `%자산랭킹`, `%강화랭킹`\n"
            "- 📰 **주식 뉴스**: 30~90분마다 속보! 호재·악재·루머·부도 위기 (`%뉴스`)\n"
            "- 🙈 시장 상태(상승장·하락장)는 이제 안 보여요. 뉴스로 추측하세요!\n"
            "- 📈 `%주가그래프 [주식] [분]`: 60분은 무료, 60분 더 볼 때마다 2천 (최대 1440분)\n"
            "- 🔤 **끝말잇기**: `%끝말잇기` 봇 난이도 4단계(쉬움~지옥), 긴 단어·미션 글자 보너스, `연습` 모드\n"
            "  `%끝말잇기 같이`로 친구들과! 스레드에서 진행 (하루 최대 1만 5천)\n"
            "- ❓ **선착순 퀴즈**: 1~2시간마다 수학(대수·미적분 I, 그래프 문제도!)·국어·영어·사회·한국사·과학·상식\n"
            "  난이도 하(1분)·중(5분)·상(10분), 제일 먼저 맞히면 최대 1만!\n"
            "- 🤖 봇 24시간 구동"
        ),
        inline=False
    )
    embed.add_field(
        name="⚖️ 밸런스 변경",
        value=(
            "- 기초수급: 1만 + 연속일마다 2천 (최대 2만)\n"
            "- 도박: 확률표 방식, 판돈까지만 잃음, 최대 10만\n"
            "- 가위바위보: 이길 때마다 2배, 10연승 자동 수령, 하루 30판\n"
            "- 은행: 대출 5만·이자 10%·24시간 / 적금 하루 1%\n"
            "- 주식 판매 수수료 2%로 통일, 송금 하루 10만 한도"
        ),
        inline=False
    )
    embed.add_field(
        name="🧾 빚(미납금) 규칙",
        value=(
            "- 대출을 24시간 안에 못 갚으면 1.5배가 미납금이 돼요\n"
            "- 미납금은 돈이 들어올 때마다 자동으로 징수돼요\n"
            "- 파산은 빚이 있을 때만, 대신 가진 걸 전부 잃어요"
        ),
        inline=False
    )
    embed.add_field(name="🗑️ 삭제", value="- 출석 체크", inline=False)
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
