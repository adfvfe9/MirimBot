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
        title="📜 패치노트 v1.2.7 — 끝말잇기 랭킹",
        description="끝말잇기 실력을 겨뤄 보세요! 자세한 명령어는 `%도움말`에서!",
        color=0xf1c40f  # 노란색
    )
    embed.add_field(
        name="🏆 끝말잇기 랭킹 `%끝말잇기랭킹 [어려움|지옥]`",
        value=(
            "- 봇과 1대1 **🟠어려움 · 🔴지옥**의 한 판 최고 **점수**로 순위를 매겨요 (연습 제외)\n"
            "- 점수는 돈과 따로 계산돼요\n"
            "  🔁 오래 이을수록 · 📏 긴 단어일수록 · ⚡ 빨리 낼수록 (최대 2배) · 🎯 미션 글자 하나당 +30점\n"
            "- 봇이 못 이으면 +100점, 게임이 끝나면 최고 기록 갱신 여부와 순위를 알려줘요"
        ),
        inline=False
    )
    embed.add_field(
        name="🔤 끝말잇기 개선",
        value=(
            "- 단어를 이을 때마다 점수 · 입력 시간 · 보상 · 미션 결과를 **임베드**로 깔끔하게 보여줘요\n"
            "- 하루 보상(1만 5천)을 다 채우면 **계속할지** 물어봐요. 계속하면 보상 없이 점수만 쌓여요\n"
            "- 보상을 다 받은 날에도 점수(랭킹)를 위해 계속 할 수 있어요"
        ),
        inline=False
    )
    embed.set_footer(text="업데이트: 2026-10-22")
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
