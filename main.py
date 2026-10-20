import discord
from discord.ext import commands
from dico_token import TOKEN
import datetime
from discord import ui
import asyncio
import json
import os
import requests
import discord
from discord.ext import commands
from discord.ui import Select, View
from discord import SelectOption
import datetime
import math
import json
import os
from random import uniform
from discord import app_commands
from discord.ui import Button, View
from discord.ext import commands
from discord import Embed, ButtonStyle, Interaction
from discord.ui import View, Button
import random
from discord.ext import commands, tasks
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import time
import discord
from discord.ext import commands
from datetime import timedelta
import os
from matplotlib import font_manager

font_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'malgun.ttf'
)

font_manager.fontManager.addfont(font_path)
plt.rcParams['font.family'] = font_manager.FontProperties(
    fname=font_path
).get_name()
plt.rcParams['axes.unicode_minus'] = False

# Bot 선언
intents = discord.Intents.default()
intents.messages = True
intents.members = True # 멤버 정보 접근을 위해 필요
intents.message_content = True  # 필수! 안 켜면 on_message나 command 둘 다 안 먹음

client = commands.Bot(command_prefix='%', intents=intents)

DATA_FILE = "enhance_data.json" # 아이템 강화 데이터를 저장할 파일
money_data_file = "money_data.json"

# 머니 데이터를 파일로 저장하고 불러오는 함수들
def load_money_data():
    if os.path.exists(money_data_file):
        with open(money_data_file, "r") as f:
            return json.load(f)
    return {}

def save_money_data(data):
    with open(money_data_file, "w") as f:
        json.dump(data, f, indent=4)

money_data = load_money_data()

warnings = {}  # 유저 ID를 키로, 경고 수를 값으로 저장
warnings_data = {} # 유저 ID를 키로, 경고 내역을 리스트로 저장
cooldowns = {} # 유저 ID를 키로, 마지막 강화 시도를 저장하는 딕셔너리

PRICE_HISTORY_FILE = "price_history.json"

def load_price_history():
    if not os.path.exists(PRICE_HISTORY_FILE):
        return {}
    with open(PRICE_HISTORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_price_history(data):
    with open(PRICE_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

price_history = load_price_history()

def load_data():
    if not os.path.exists(DATA_FILE): # 파일이 없으면 빈 딕셔너리 반환
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data): # 데이터를 JSON 파일에 저장하는 함수
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

enhance_data = load_data() # 아이템 강화 데이터를 불러오기
price_history = load_price_history() # 주식 가격 변동 이력을 저장하는 딕셔너리

BANK_FILE = "bank_data.json"

def load_bank_data():
    if not os.path.exists(BANK_FILE):
        return {}
    with open(BANK_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_bank_data(data):
    with open(BANK_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# 봇 시작 시 로딩
bank_data = load_bank_data()

GAMBLE_COOLDOWN_FILE = "gamble_cooldowns.json"

def load_gamble_cooldowns():
    if os.path.exists(GAMBLE_COOLDOWN_FILE):
        with open(GAMBLE_COOLDOWN_FILE, "r") as f:
            raw = json.load(f)
            return {k: datetime.datetime.fromisoformat(v) for k, v in raw.items()}
    return {}

def save_gamble_cooldowns(data):
    with open(GAMBLE_COOLDOWN_FILE, "w") as f:
        raw = {k: v.isoformat() for k, v in data.items()}
        json.dump(raw, f, indent=4)

GAMBLE_COOLDOWN_FILE = "gamble_cooldowns.json"

gamble_cooldowns = load_gamble_cooldowns()


GAMBLE_STATS_FILE = "gamble_stats.json"

def load_gamble_stats():
    if os.path.exists(GAMBLE_STATS_FILE):
        with open(GAMBLE_STATS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_gamble_stats(data):
    with open(GAMBLE_STATS_FILE, "w") as f:
        json.dump(data, f, indent=4)

gamble_stats = load_gamble_stats()

DELISTED_FILE = "delisted_stocks.json"

def load_delisted_stocks():
    if os.path.exists(DELISTED_FILE):
        with open(DELISTED_FILE, "r") as f:
            return json.load(f)
    return {}

def save_delisted_stocks(data):
    with open(DELISTED_FILE, "w") as f:
        json.dump(data, f, indent=4)

delisted_stocks = load_delisted_stocks()

ITEMS_FILE = "items.json"

def load_items():
    if os.path.exists(ITEMS_FILE):
        with open(ITEMS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_items(data):
    with open(ITEMS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

user_items = load_items()

CONSOLATION_FILE = "consolation.json"

def load_consolation():
    if os.path.exists(CONSOLATION_FILE):
        with open(CONSOLATION_FILE, "r") as f:
            return json.load(f)
    return {}

def save_consolation(data):
    with open(CONSOLATION_FILE, "w") as f:
        json.dump(data, f, indent=4)

consolation_data = load_consolation()

WARNING_FILE = "warnings.json"

# 경고 데이터 불러오기/저장

def load_warnings():
    if os.path.exists("warnings.json"):
        with open("warnings.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_warnings(data):
    with open("warnings.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

warnings_data = load_warnings()

CHECKIN_FILE = "checkin_cooldowns.json"

def load_checkin_data():
    if os.path.exists(CHECKIN_FILE):
        try:
            with open(CHECKIN_FILE, "r") as f:
                content = f.read().strip()
                if not content:
                    return {}
                return json.loads(content)
        except json.JSONDecodeError:
            print("⚠️ checkin_cooldowns.json 형식 오류 → 초기화함")
            return {}
    return {}

def save_checkin_data(data):
    with open(CHECKIN_FILE, "w") as f:
        json.dump(data, f, indent=4)

ACHIEVEMENT_FILE = "achievements.json"

def load_achievements():
    if os.path.exists(ACHIEVEMENT_FILE):
        with open(ACHIEVEMENT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_achievements(data):
    with open(ACHIEVEMENT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

achievements_data = load_achievements()

def load_attendance_channels():
    if os.path.exists("attendance_channels.json"):
        with open("attendance_channels.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_attendance_channels(data):
    with open("attendance_channels.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

attendance_channels = load_attendance_channels()

TOKEN_FILE = "token_data.json"

def load_token_data():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_token_data(data):
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

token_data = load_token_data()

SUGGESTION_FILE = "suggestions.json"
SUGGESTION_COOLDOWN = 3600  # 초 단위 (1시간)

def load_suggestions():
    if os.path.exists(SUGGESTION_FILE):
        with open(SUGGESTION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_suggestions(data):
    with open(SUGGESTION_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

SUGGESTION_ADMINS_FILE = "suggestion_admins.json"

def load_suggestion_admins():
    if os.path.exists(SUGGESTION_ADMINS_FILE):
        with open(SUGGESTION_ADMINS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_suggestion_admins(data):
    with open(SUGGESTION_ADMINS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


# on_message는 커맨드와 충돌 방지 필요 → process_commands 사용
@client.event
async def on_message(message):
    if message.author.bot:
        return  # 봇의 메시지 무시

    # message.content.startswith()는 해당 문자로 시작하는 단어에 대해서
    # if message.content.startswith('테스트'):
        # await message.channel.send(f"{message.author} | {message.author.mention}, 안녕!")

    # if message.content == '안녕':
        # await message.channel.send(f"{message.author} | {message.author.mention}, 어서오세요!")

    # 개인 메시지로 전송
    # await message.author.send(f"{message.author} | {message.author.mention} 테스트")

    # 반드시 명령어 처리를 호출해줘야 commands.Bot의 @client.command가 작동함!
    await client.process_commands(message)

@client.command(aliases=['시간'])
async def timeget(ctx):
    await ctx.message.delete()
    now = datetime.datetime.now()
    current_time = now.strftime("%Y년 %m월 %d일 %H시 %M분 %S초")
    embed = discord.Embed(title="현재 시간 ⏰", description=f"{current_time}", color=0x3498db)
    await ctx.send(embed=embed)

@client.command(aliases=['패치노트'])
async def patchnote(ctx):
    await ctx.message.delete()
    embed = discord.Embed(
        title="📜 패치노트 v1.2.0",
        description="최신 버전 업데이트입니다.",
        color=0xf1c40f  # 노란색
    )
    embed.add_field(name="✨ 새로운 기능", value="- 봇 24시간 구동", inline=False)
    embed.set_footer(text="업데이트: 2025-10-20")
    await ctx.send(embed=embed)

@client.command(aliases=['급식'])
async def school_meal(ctx):
    await ctx.message.delete()
    import re

    api_key = '94b8b025408f450f8bfef115feb40017'  # API KEY
    school_code = '7011569'                       # 미림마이스터고
    edu_office_code = 'B10'                       # 서울교육청
    today = datetime.datetime.now().strftime("%Y%m%d")

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



class EnhanceView(discord.ui.View):
    def __init__(self, ctx, item_name, do_enhance):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.item_name = item_name
        self.do_enhance = do_enhance
        self.finished = False

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "❌ 명령어를 실행한 사람만 사용할 수 있습니다.",
                ephemeral=True
            )
            return False

        if self.finished:
            await interaction.response.send_message(
                "이미 강화 처리가 완료되었습니다.",
                ephemeral=True
            )
            return False

        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(
        label="강화하기",
        style=discord.ButtonStyle.primary,
        emoji="🔨"
    )
    async def enhance_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        self.finished = True
        await self.do_enhance(interaction, maximum=False)

    @discord.ui.button(
        label="최대 강화",
        style=discord.ButtonStyle.success,
        emoji="💰"
    )
    async def max_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        self.finished = True
        await self.do_enhance(interaction, maximum=True)

    @discord.ui.button(
        label="취소하기",
        style=discord.ButtonStyle.secondary,
        emoji="❌"
    )
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        self.finished = True
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="❌ 강화 취소",
                description="강화를 취소했습니다. 돈과 아이템은 변경되지 않았습니다.",
                color=discord.Color.greyple()
            ),
            view=None
        )


@client.command(aliases=["강화"])
async def enhance(
    ctx,
    item_name: str = None,
    target_level: int = None
):
    if item_name is None:
        await ctx.send(
            "아이템 이름을 입력해주세요!\n"
            "예: `%강화 칼`\n"
            "목표 레벨 지정: `%강화 칼 10`"
        )
        return

    if target_level is not None and target_level < 1:
        await ctx.send("❌ 목표 레벨은 1 이상이어야 합니다.")
        return

    user_id = str(ctx.author.id)
    user_items = enhance_data.get(user_id, {})
    current_level = user_items.get(item_name, 0)
    balance = money_data.get(user_id, 0)

    if (
        target_level is not None
        and target_level <= current_level
    ):
        await ctx.send(
            f"❌ 현재 `{item_name}`의 레벨은 +{current_level}입니다.\n"
            "현재 레벨보다 높은 목표 레벨을 입력해주세요."
        )
        return

    cost = 100 * (2 ** current_level)

    if balance < cost:
        await ctx.send(
            f"💸 돈이 부족합니다!\n"
            f"현재 보유 금액: {balance:,} byte\n"
            f"다음 강화 비용: {cost:,} byte"
        )
        return

    # 실제 강화 확률과 동일한 공식 사용
    next_level = current_level + 1
    success_rate = min(
        100.0,
        100.0 / (next_level ** 0.5)
    )

    failure_rate = 100.0 - success_rate
    maintain_rate = failure_rate * 0.90
    downgrade_rate = failure_rate * 0.09
    destroy_rate = failure_rate * 0.01

    embed = discord.Embed(
        title="🔨 강화 시스템",
        description=(
            f"**아이템:** `{item_name}`\n"
            f"**현재 레벨:** +{current_level}\n"
            f"**목표 레벨:** "
            f"{f'+{target_level}' if target_level is not None else '미지정'}\n"
            f"**보유 금액:** {balance:,} byte\n"
            f"**다음 강화 비용:** {cost:,} byte\n"
            f"**현재 판매가:** {int(100 * (2.25 ** current_level)):,} byte\n\n"
            "강화 방식을 선택해주세요."
        ),
        color=0x3498DB
    )

    embed.add_field(
        name=f"📊 다음 강화 (+{next_level}) 결과 확률",
        value=(
            f"✅ 강화 성공: **{success_rate:.2f}%**\n"
            f"⚪ 레벨 유지: **{maintain_rate:.2f}%**\n"
            f"📉 레벨 하락: **{downgrade_rate:.2f}%**\n"
            f"💥 아이템 파괴: **{destroy_rate:.2f}%**"
        ),
        inline=False
    )

    if target_level is not None:
        embed.add_field(
            name="🎯 목표 강화",
            value=(
                f"최대 강화 버튼을 누르면 +{target_level}에 도달하거나 "
                "강화가 중단될 때까지 진행합니다."
            ),
            inline=False
        )

    embed.set_footer(
        text="강화하기: 1회 시도 | 최대 강화: 가능한 만큼 반복"
    )

    async def do_enhance(
        interaction: discord.Interaction,
        maximum: bool = False
    ):
        await interaction.response.defer()

        # 최신 잔액 및 아이템 레벨 확인
        balance = money_data.get(user_id, 0)
        user_items = enhance_data.setdefault(user_id, {})
        level = user_items.get(item_name, 0)

        attempts = 0
        successes = 0
        maintained = 0
        downgraded = 0
        destroyed = False
        total_cost = 0
        logs = []

        while True:
            # 목표 레벨 도달 시 종료
            if (
                target_level is not None
                and level >= target_level
            ):
                break

            cost = 100 * (2 ** level)

            # 다음 시도 비용이 부족한 경우
            if balance < cost:
                if attempts == 0:
                    result = discord.Embed(
                        title="💸 강화 불가",
                        description=(
                            f"필요한 금액: {cost:,} byte\n"
                            f"보유 금액: {balance:,} byte"
                        ),
                        color=discord.Color.red()
                    )
                    await interaction.edit_original_response(
                        embed=result,
                        view=None
                    )
                    return
                break

            # 강화 비용 차감
            balance -= cost
            total_cost += cost
            attempts += 1

            # 다음 레벨 기준 성공 확률
            next_level = level + 1
            success_rate = min(
                100.0,
                100.0 / (next_level ** 0.5)
            )

            if uniform(0.0, 100.0) < success_rate:
                level += 1
                successes += 1
                logs.append(f"✅ +{level} 강화 성공")

            else:
                penalty = uniform(0.0, 100.0)

                if penalty < 90:
                    maintained += 1
                    logs.append(
                        f"⚪ 강화 실패 (레벨 유지: +{level})"
                    )

                elif penalty < 99:
                    level = max(0, level - 1)
                    downgraded += 1
                    logs.append(
                        f"📉 강화 실패 (레벨 하락: +{level})"
                    )

                else:
                    destroyed = True
                    logs.append("💥 강화 실패 (아이템 파괴)")
                    break

            # 일반 강화는 한 번만 시도
            if not maximum:
                break

            # 목표가 지정되었고 도달했다면 종료
            if (
                target_level is not None
                and level >= target_level
            ):
                break

            # 다음 강화 비용을 감당할 수 없다면 종료
            next_cost = 100 * (2 ** level)

            if balance < next_cost:
                break

        # 데이터 저장
        money_data[user_id] = balance

        if destroyed:
            user_items.pop(item_name, None)
        else:
            user_items[item_name] = level

        enhance_data[user_id] = user_items

        save_json(money_data_file, money_data)
        save_data(enhance_data)

        # 결과 임베드
        result = discord.Embed(
            title="💥 아이템 파괴!" if destroyed else "🔧 강화 결과",
            color=(
                discord.Color.red()
                if destroyed
                else discord.Color.green()
            )
        )

        if destroyed:
            result.description = "강화 실패로 아이템이 파괴되었습니다."

        elif (
            target_level is not None
            and level >= target_level
        ):
            result.description = (
                f"🎉 목표 레벨 +{target_level}에 도달했습니다!"
            )

        elif target_level is not None and maximum:
            result.description = (
                f"목표 레벨: +{target_level}\n"
                f"중단 레벨: +{level}\n"
                "돈이 부족하거나 강화가 중단되었습니다."
            )

        elif maximum:
            result.description = "💰 최대 강화가 완료되었습니다."

        else:
            result.description = (
                logs[0] if logs else "강화가 진행되지 않았습니다."
            )

        result.add_field(
            name="아이템",
            value=f"`{item_name}`",
            inline=True
        )
        result.add_field(
            name="최종 레벨",
            value="파괴됨" if destroyed else f"+{level}",
            inline=True
        )
        result.add_field(
            name="시도 횟수",
            value=f"{attempts}회",
            inline=True
        )
        result.add_field(
            name="성공 횟수",
            value=f"{successes}회",
            inline=True
        )
        result.add_field(
            name="유지 횟수",
            value=f"{maintained}회",
            inline=True
        )
        result.add_field(
            name="하락 횟수",
            value=f"{downgraded}회",
            inline=True
        )
        result.add_field(
            name="총 강화 비용",
            value=f"{total_cost:,} byte",
            inline=True
        )
        result.add_field(
            name="남은 돈",
            value=f"{balance:,} byte",
            inline=True
        )
        result.add_field(
            name="판매가",
            value=(
                "0 byte"
                if destroyed
                else f"{int(100 * (2.25 ** level)):,} byte"
            ),
            inline=True
        )

        if logs:
            result.add_field(
                name="강화 기록 (최근 10회)",
                value="\n".join(logs[-10:]),
                inline=False
            )

        result.set_footer(text="강화 결과가 저장되었습니다.")

        await interaction.edit_original_response(
            embed=result,
            view=None
        )

    view = EnhanceView(ctx, item_name, do_enhance)
    message = await ctx.send(embed=embed, view=view)
    view.message = message

@client.command(aliases=['강화목록'])
async def enhance_list(ctx):
    user_id = str(ctx.author.id)
    user_items = enhance_data.get(user_id, {})

    if not user_items:
        await ctx.send("😢 아직 강화한 아이템이 없어요!")
        return

    embed = discord.Embed(title=f"{ctx.author.display_name}님의 강화 아이템 목록", color=0x2ecc71)
    for item_name, level in user_items.items():
        embed.add_field(name=f"{item_name} (+{level})", value=" ", inline=True)

    await ctx.send(embed=embed)

# 머니 확인
@client.command(aliases=['머니확인', '머니'])
async def money(ctx, member: discord.Member = None):
    await ctx.message.delete()  # 명령어 삭제
    member = member or ctx.author
    user_id = str(member.id)
    balance = money_data.get(user_id, 0)

    embed = Embed(
        title="💰 잔액 확인",
        description=f"**{member.display_name}** 님의 잔액은 **{balance:.2f} byte**입니다.",
        color=discord.Color.gold()
    )
    await ctx.send(embed=embed)

# 머니 추가
@client.command(aliases=['머니추가'])
@commands.has_permissions(administrator=True)
async def moneyadd(ctx, member: discord.Member, amount: int):
    await ctx.message.delete()
    user_id = str(member.id)
    view = View()

    async def confirm_callback(interaction: Interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("이 버튼은 당신의 것이 아닙니다!", ephemeral=True)
            return

        money_data[user_id] = money_data.get(user_id, 0) + amount
        save_money_data(money_data)
        embed = Embed(
            description=f"✅ **{member.display_name}** 님에게@ **{amount} byte**를 추가했습니다.",
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=embed, view=None)

    async def cancel_callback(interaction: Interaction):
        embed = Embed(
            description="❌ 작업이 취소되었습니다.",
            color=discord.Color.red()
        )
        await interaction.response.edit_message(embed=embed, view=None)

    button_yes = Button(label="확인", style=discord.ButtonStyle.green)
    button_no = Button(label="취소", style=discord.ButtonStyle.red)
    button_yes.callback = confirm_callback
    button_no.callback = cancel_callback
    view.add_item(button_yes)
    view.add_item(button_no)

    embed = Embed(
        description=f"⚠️ **{member.display_name}** 님에게 **{amount} byte**를 추가하시겠습니까?",
        color=discord.Color.orange()
    )
    await ctx.send(embed=embed, view=view)

# 머니 제거
@client.command(aliases=['머니제거'])
@commands.has_permissions(administrator=True)
async def moneydel(ctx, member: discord.Member, amount: int):
    await ctx.message.delete()
    user_id = str(member.id)
    view = View()

    async def confirm_callback(interaction: Interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("이 버튼은 당신의 것이 아닙니다!", ephemeral=True)
            return

        money_data[user_id] = money_data.get(user_id, 0) - amount
        save_money_data(money_data)
        embed = Embed(
            description=f"✅ **{member.display_name}** 님에게서 **{amount} byte**를 제거했습니다.",
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=embed, view=None)

    async def cancel_callback(interaction: Interaction):
        embed = Embed(
            description="❌ 작업이 취소되었습니다.",
            color=discord.Color.red()
        )
        await interaction.response.edit_message(embed=embed, view=None)

    button_yes = Button(label="확인", style=discord.ButtonStyle.green)
    button_no = Button(label="취소", style=discord.ButtonStyle.red)
    button_yes.callback = confirm_callback
    button_no.callback = cancel_callback
    view.add_item(button_yes)
    view.add_item(button_no)

    embed = Embed(
        description=f"⚠️ **{member.display_name}** 님에게서 **{amount} byte**를 제거하시겠습니까?",
        color=discord.Color.orange()
    )
    await ctx.send(embed=embed, view=view)

# 송금
@client.command(aliases=['송금'])
async def send(ctx, member: discord.Member, amount: int):
    await ctx.message.delete()
    sender_id = str(ctx.author.id)
    receiver_id = str(member.id)
    fee = int(amount * 0.1)
    total_cost = amount + fee

    if money_data.get(sender_id, 0) < total_cost:
        embed = Embed(
            description="❌ 잔액이 부족합니다! (10% 수수료 포함)",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    if amount <= 0:
        embed = Embed(
            description="❌ 송금 금액은 0보다 커야 합니다.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    view = View()

    async def confirm_callback(interaction: Interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("이 버튼은 당신의 것이 아닙니다!", ephemeral=True)
            return

        money_data[sender_id] -= total_cost
        money_data[receiver_id] = money_data.get(receiver_id, 0) + amount
        save_money_data(money_data)
        embed = Embed(
            description=f"💸 **{ctx.author.display_name}** 님이 **{member.display_name}** 님에게 **{amount} byte**를 송금했습니다! (수수료 {fee} byte)",
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=embed, view=None)

    async def cancel_callback(interaction: Interaction):
        embed = Embed(
            description="❌ 송금이 취소되었습니다.",
            color=discord.Color.red()
        )
        await interaction.response.edit_message(embed=embed, view=None)

    button_yes = Button(label="확인", style=discord.ButtonStyle.green)
    button_no = Button(label="취소", style=discord.ButtonStyle.red)
    button_yes.callback = confirm_callback
    button_no.callback = cancel_callback
    view.add_item(button_yes)
    view.add_item(button_no)

    embed = Embed(
        description=f"⚠️ **{member.display_name}** 님에게 **{amount} byte**를 송금하시겠습니까?\n(💸 수수료 {fee} byte 포함)",
        color=discord.Color.orange()
    )
    await ctx.send(embed=embed, view=view)
class ShopDropdown(Select):
    def __init__(self, user: discord.Member, shop_items):
        self.user = user
        self.shop_items = shop_items

        options = [
            SelectOption(
                label=item["name"],
                description=f"💰 {item['price']} 토큰",
                value=item["name"]
            ) for item in shop_items
        ]
        super().__init__(placeholder="구매할 아이템을 선택하세요", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.user:
            await interaction.response.send_message("이 상점은 당신의 것이 아닙니다!", ephemeral=True)
            return

        selected_name = self.values[0]
        item = next(i for i in self.shop_items if i["name"] == selected_name)
        user_id = str(interaction.user.id)
        price = item["price"]

        # ✅ 토큰 가져오기
        user_token = token_data.get(user_id, {}).get("tokens", 0)

        if user_token < price:
            await interaction.response.send_message(
                f"❌ `{selected_name}` 구매에 필요한 **{price - user_token} 토큰**이 부족합니다!",
                ephemeral=True
            )
            return

        token_data.setdefault(user_id, {})["tokens"] = user_token - price
        save_token_data(token_data)

        user_items.setdefault(user_id, {})
        user_items[user_id][selected_name] = user_items[user_id].get(selected_name, 0) + 1
        save_items(user_items)

        await interaction.response.send_message(
            f"✅ `{selected_name}` 아이템을 **{price} 토큰**에 구매했습니다!",
            ephemeral=True
        )



import math

# log2 공식
def calc_byte_log2(level):
    if level <= 0:
        return 0
    return int(0.15 * level * math.log2(level)) + 1

# log10 공식
def calc_byte_log10(level):
    if level <= 0:
        return 0
    return int(0.8 * level * math.log10(level)) + 1


@client.command(aliases=['강화판매'])
async def sell_enhance(ctx, item_name: str):
    await ctx.message.delete()
    user_id = str(ctx.author.id)

    # 아이템이 없으면
    if user_id not in enhance_data or item_name not in enhance_data[user_id]:
        await ctx.send(
            f"{ctx.author.mention} | ❌ `{item_name}` 아이템이 없습니다."
        )
        return

    level = enhance_data[user_id][item_name]

    # 판매 가격: 1000 * 3^강화 레벨
    earned = (int)(100 * (2.25 ** level))

    # 머니 업데이트
    money_data[user_id] = money_data.get(user_id, 0) + earned
    save_money_data(money_data)

    # 아이템 삭제
    del enhance_data[user_id][item_name]
    save_data(enhance_data)

    # 임베드 출력
    embed = discord.Embed(
        title="💰 강화 아이템 판매",
        description=(
            f"{ctx.author.mention}님이 "
            f"`{item_name} +{level}`을 판매하였습니다!"
        ),
        color=0x00ccff
    )

    embed.add_field(
        name="💵 획득 Byte",
        value=f"**{earned:,} byte**",
        inline=False
    )

    embed.add_field(
        name="💳 현재 보유 금액",
        value=f"**{money_data[user_id]:,} byte**",
        inline=False
    )

    embed.set_footer(text="판매가 완료되었습니다.")

    await ctx.send(embed=embed)


# ───────────── 주식 시장 상태 ─────────────
market_file = "market_state.json"

override_state = None
override_end = None

# 시장 상태를 저장하는 파일
def load_market_state():
    global override_state, override_end
    if os.path.exists(market_file):
        with open(market_file, "r") as f:
            data = json.load(f)
            override_state = data.get("override_state")
            override_end_str = data.get("override_end")
            if override_end_str:
                override_end = datetime.datetime.fromisoformat(override_end_str)
            return data.get("state", "BULL"), data.get("remaining_seconds", random.randint(300, 7200))
    return "BULL", random.randint(300, 7200)

# 시장 상태 저장
def save_market_state(state, remaining_seconds):
    data = {
        "state": state,
        "remaining_seconds": remaining_seconds,
        "override_state": override_state,
        "override_end": override_end.isoformat() if override_end else None
    }
    with open(market_file, "w") as f:
        json.dump(data, f, indent=4)

# 현재 시장 상태를 가져오는 함수
def get_effective_market_state():
    global override_state, override_end, current_market_state
    if override_state and override_end:
        if datetime.datetime.now() < override_end:
            return override_state
        else:
            if override_state == "HYPER_BULL":
                set_override_state("CRASH", 20 * 60)
                return "CRASH"
            elif override_state == "CRASH":
                override_state = None
                override_end = None
                return "BULL"
    return current_market

# 임시 시장 상태 설정 (초상승장, 주식부도)
def set_override_state(state, duration_seconds):
    global override_state, override_end, market_wait_seconds
    override_state = state
    override_end = datetime.datetime.now() + datetime.timedelta(seconds=duration_seconds)
    save_market_state(get_effective_market_state(), market_wait_seconds)

# ───────────── 주식 기본 정보 ─────────────
stock_info = {
    "JAVA":   {"base": 500,  "limit": 0.08},
    "C":      {"base": 300,  "limit": 0.06},
    "C++":    {"base": 800,  "limit": 0.10},
    "C#":     {"base": 1200, "limit": 0.09},
    "PYTHON": {"base": 100,  "limit": 0.15},
    "HTML":   {"base": 400,  "limit": 0.05},
    "JS":     {"base": 2000, "limit": 0.02},
    "TS":     {"base": 1000, "limit": 0.12},
    "RUST":   {"base": 200,  "limit": 0.25},
    "RUBY":   {"base": 1500, "limit": 0.04}
}

stock_file = "stock_prices.json"
stock_prices = {}
last_update_time = datetime.datetime.now(datetime.timezone.utc)

# 현재 시장 상태 (초기값: 상승장)
current_market, market_wait_seconds = load_market_state()

# 시장 전환 루프
async def market_cycle():
    global current_market, market_wait_seconds
    await client.wait_until_ready()

    while True:
        print(f"[📢 시장 전환 대기] {market_wait_seconds // 60}분 후 상태 변경 예정")

        # 저장된 시간 기준으로 대기
        while market_wait_seconds > 0:
            await asyncio.sleep(1)
            market_wait_seconds -= 1
            save_market_state(current_market, market_wait_seconds)

        # 상태 전환
        current_market = "BEAR" if current_market == "BULL" else "BULL"
        market_wait_seconds = random.randint(300, 7200)  # 5~120분
        save_market_state(current_market, market_wait_seconds)
        print(f"[🔁 시장 상태 변경됨] 현재 시장: {'📈 상승장' if current_market == 'BULL' else '📉 하락장'}")

# ───────────── 저장/로드 함수 ─────────────
def load_stock_prices():
    if os.path.exists(stock_file):
        with open(stock_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        name: {"current": data["base"], "previous": data["base"]}
        for name, data in stock_info.items()
    }

def save_stock_prices():
    with open(stock_file, "w", encoding="utf-8") as f:
        json.dump(stock_prices, f, indent=4)

# ───────────── 주식 가격 갱신 ─────────────
def update_stocks():
    global last_update_time, price_history

    effective_state = get_effective_market_state()  # ✅ 현재 실질 시장 상태

    for name, info in stock_info.items():
        base = info["base"]
        limit = info["limit"]
        prev_price = stock_prices[name]["current"]

        # 기본 변동
        change = random.uniform(-limit, limit)

        # 과한 변동 억제
        bias = (base - prev_price) / base * 0.05
        change += bias

        new_price = prev_price + base * change

        # ✅ 상승장 / 하락장 / 초상승장 / 주식부도 효과 (곱연산)
        if effective_state == "BULL":
            new_price *= (1 + random.uniform(-0.005, 0.015))  # +-0.5~1%
        elif effective_state == "BEAR":
            new_price *= (1 - random.uniform(-0.005, 0.01))   # 0.5~-1.5%
        elif effective_state == "HYPER_BULL":
            new_price *= (1 + random.uniform(-0.02, 0.1))  # -2~10%
        elif effective_state == "CRASH":
            new_price *= (1 - random.uniform(-0.015, 0.15))    # 1.5~-15%

        # 상장폐지 처리
        if new_price <= 0:
            new_price = base
            print(f"[📉 상장폐지] {name} → 기본가로 초기화됨")

            for user_id, stocks in list(portfolio.items()):
                if name in stocks:
                    del stocks[name]
                    delisted_stocks.setdefault(user_id, []).append(name)

            save_delisted_stocks(delisted_stocks)
            save_json(portfolio_file, portfolio)

        stock_prices[name]["previous"] = prev_price
        stock_prices[name]["current"] = round(new_price, 2)

        # 가격 히스토리 저장
        price_history.setdefault(name, []).append(round(new_price, 2))
        if len(price_history[name]) > 1440:
            price_history[name] = price_history[name][-1440:]

    last_update_time = datetime.datetime.now(datetime.timezone.utc)
    save_json(stock_file, stock_prices)
    save_price_history(price_history)

    # from git import Repo
    # import os

    # def git_commit_and_push():
    #     from git import Repo
    #     repo_dir = r"C:\Users\USER\Desktop\디코 봇\Mirim"
    #     repo = Repo(repo_dir)

    #     repo.git.add("price_history.json")
    #     repo.git.add("market_state.json")
    #     repo.index.commit("🔄 Update price history")
    #     origin = repo.remote(name="origin")
    #     print("📦 pushing to GitHub...")
    #     origin.push()
    #     print("✅ push complete")

    # git_commit_and_push()

# ───────────── 자동 1분 갱신 루프 ─────────────
@tasks.loop(minutes=1)
async def auto_update_stocks():
    update_stocks()

@auto_update_stocks.before_loop
async def before_loop():
    await client.wait_until_ready()

# ───────────── %주식 명령어 ─────────────
@client.command(aliases=["주식"])
async def stock(ctx):
    await ctx.message.delete()

    now = datetime.datetime.now(datetime.timezone.utc)
    elapsed = (now - last_update_time).total_seconds()
    next_update = last_update_time + datetime.timedelta(seconds=60)
    timestamp = int(next_update.timestamp())

    embed = discord.Embed(
        title="📈 실시간 주식 시세",
        description="1분마다 자동 갱신됩니다.",
        color=discord.Color.green()
    )
    name="📊 현재 시장 상태",
    state = get_effective_market_state()
    state_text = {
        "BULL": "📈 상승장",
        "BEAR": "📉 하락장",
        "HYPER_BULL": "🚀 초상승장",
        "CRASH": "💥 주식부도"
    }.get(state, "❓ 알 수 없음")

    embed.add_field(
        name="📊 현재 시장 상태",
        value=state_text,
        inline=False
    )


    for name, price_data in stock_prices.items():
        current = price_data["current"]
        previous = price_data["previous"]
        diff = current - previous
        percent = (current / previous) * 100 - 100 if previous != 0 else 0

        diff_str = (
            f"▲ {abs(diff):.2f} byte (+{percent:.2f}%)" if diff > 0 else
            f"▼ {abs(diff):.2f} byte ({percent:.2f}%)" if diff < 0 else
            "― 변동 없음"
        )

        embed.add_field(
            name=name,
            value=f"💵 {current:.2f} byte\n({diff_str})",
            inline=True
        )
    embed.add_field(
        name="⏱️ 다음 갱신",
        value=f"<t:{timestamp}:R>",  # ✅ 여기에 쓰면 디스코드가 해석함
        inline=False
    )

    await ctx.send(embed=embed)

# ───────────── 봇 시작 시 초기화 ─────────────
stock_prices = load_stock_prices()
# 🛠️ 누락된 주식 보정 (예: TS)
for name, data in stock_info.items():
    if name not in stock_prices:
        stock_prices[name] = {
            "current": data["base"],
            "previous": data["base"]
        }

save_stock_prices()
last_update_time = datetime.datetime.now(datetime.timezone.utc)

async def auto_remove_expired_roles():
    await client.wait_until_ready()
    while True:
        now = datetime.datetime.now()
        try:
            with open("warnings.json", "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"❌ warnings.json 불러오기 실패: {e}")
            await asyncio.sleep(60)
            continue

        updated = False

        for guild in client.guilds:
            role = guild.get_role(1352540239985643571)
            for user_id, user_data in list(data.items()):
                if "restriction_until" not in user_data:
                    continue
                try:
                    until = datetime.datetime.strptime(user_data["restriction_until"], "%Y-%m-%d %H:%M:%S")
                    if now >= until:
                        member = guild.get_member(int(user_id))
                        if member and role in member.roles:
                            await member.remove_roles(role)
                            print(f"✅ 역할 제거됨: {member.display_name}")
                        del user_data["restriction_until"]
                        updated = True
                except Exception as e:
                    print(f"❌ 시간 파싱 오류: {e}")
                    continue

        if updated:
            try:
                with open("warnings.json", "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
            except Exception as e:
                print(f"❌ 저장 실패: {e}")

        await asyncio.sleep(1)  # 1분마다 확인

@client.event
async def on_ready():
    global last_update_time
    print(f'{client.user}에 로그인하였습니다.')

    await client.change_presence(
        status=discord.Status.online,
        activity=discord.Game('\'%도움말\'을 입력해보세요')
    )

    if not auto_update_stocks.is_running():
        auto_update_stocks.start()
        print("✅ 주식 자동 갱신 루프 시작됨")

    asyncio.create_task(market_cycle())
    asyncio.create_task(auto_remove_expired_roles())

    last_update_time = datetime.datetime.now(datetime.timezone.utc)

    # ✅ 미림봇 접속 메시지 및 출석 메시지 전송
    for guild in client.guilds:
        guild_id = str(guild.id)
        channel_id = attendance_channels.get(guild_id)

        if channel_id:
            try:
                channel = await client.fetch_channel(channel_id)

                # 출석 메시지
                embed = discord.Embed(
                    title="📅 출석 체크",
                    description="버튼을 눌러 오늘의 출석을 완료하세요!",
                    color=discord.Color.blurple()
                )
                await channel.send(embed=embed, view=CheckinButtonView())
            except discord.NotFound:
                print(f"⚠️ 채널 ID {channel_id}를 찾을 수 없습니다. (존재하지 않음)")
            except discord.Forbidden:
                print(f"⚠️ 채널 ID {channel_id}에 접근 권한이 없습니다.")
            except discord.HTTPException as e:
                print(f"⚠️ 채널 ID {channel_id} 로드 실패: {e}")
        else:
            print(f"⚠️ 서버 {guild_id}의 출석 채널이 설정되어 있지 않습니다.")

@client.command(aliases=["주식초기화"])
@commands.has_permissions(administrator=True)
async def reset_stock(ctx):
    await ctx.message.delete()
    global stock_prices, last_update_time

    # 주식 초기화
    stock_prices = {
        name: {"current": info["base"], "previous": info["base"]}
        for name, info in stock_info.items()
    }
    save_stock_prices()
    price_history.clear()
    save_price_history(price_history)
    last_update_time = datetime.datetime.now(datetime.timezone.utc)

    embed = discord.Embed(
        title="🔄 주식 초기화 완료",
        description="모든 주식이 기본가로 초기화되었습니다.",
        color=discord.Color.orange()
    )
    embed.set_footer(text=f"요청자: {ctx.author.display_name}")
    await ctx.send(embed=embed)

# ───────────── 유저 데이터 로딩 및 저장 ─────────────
portfolio_file = "portfolio.json"
money_data_file = "money_data.json"

def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

portfolio = load_json(portfolio_file, {})
money_data = load_json(money_data_file, {})

# ───────────── 주식 이름 줄임말 처리 ─────────────
stock_aliases = {
    "J": "JAVA", "JAVA": "JAVA",
    "C": "C",
    "+": "C++", "C++": "C++",
    "#": "C#", "C#": "C#",
    "P": "PYTHON", "PYTHON": "PYTHON",
    "H": "HTML", "HTML": "HTML",
    "JS": "JS",
    "TS": "TS",
    "RUST": "RUST", "RS" : "RUST",
    "RUBY": "RUBY", "RB": "RUBY"
}

# ───────────── %주식구매 ─────────────
@client.command(aliases=["주식구매"])
async def buy_stock(ctx, stock_name: str, amount: int):
    await ctx.message.delete()
    user_id = str(ctx.author.id)
    stock_key = stock_aliases.get(stock_name.upper())

    if not stock_key or stock_key not in stock_prices:
        await ctx.send("❌ 존재하지 않는 주식입니다.")
        return
    if amount <= 0:
        await ctx.send("❌ 1 이상의 수량을 입력해주세요.")
        return

    price = stock_prices[stock_key]["current"]
    total_cost = round(price * amount, 2)

    if money_data.get(user_id, 0) < total_cost:
        await ctx.send("❌ 잔액이 부족합니다.")
        return

    embed = discord.Embed(
        title="📥 주식 구매 확인",
        description=f"{ctx.author.mention}님, 아래 거래를 확인해주세요.",
        color=discord.Color.blue()
    )
    embed.add_field(name="종목", value=stock_key, inline=True)
    embed.add_field(name="수량", value=f"{amount} 주", inline=True)
    embed.add_field(name="총 가격", value=f"{total_cost} byte", inline=False)

    view = View()

    async def confirm_callback(interaction: discord.Interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("이 버튼은 당신의 것이 아니에요!", ephemeral=True)
            return

        money_data[user_id] -= total_cost
        portfolio.setdefault(user_id, {}).setdefault(stock_key, {"quantity": 0, "avg_price": price})
        stock = portfolio[user_id][stock_key]

        # 새 평균 단가 계산
        total_quantity = stock["quantity"] + amount
        total_spent = stock["quantity"] * stock["avg_price"] + total_cost
        stock["quantity"] = total_quantity
        stock["avg_price"] = total_spent / total_quantity

        save_json(portfolio_file, portfolio)
        save_json(money_data_file, money_data)

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="✅ 구매 완료",
                description=f"{stock_key} {amount}주 구매 완료!",
                color=discord.Color.green()
            ),
            view=None
        )

    async def cancel_callback(interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="❌ 구매 취소",
                description="거래가 취소되었습니다.",
                color=discord.Color.red()
            ),
            view=None
        )

    yes = Button(label="확인", style=discord.ButtonStyle.green)
    no = Button(label="취소", style=discord.ButtonStyle.red)
    yes.callback = confirm_callback
    no.callback = cancel_callback
    view.add_item(yes)
    view.add_item(no)

    await ctx.send(embed=embed, view=view)

# ───────────── %주식판매 ─────────────
@client.command(aliases=["주식판매"])
async def sell_stock(ctx, stock_name: str, amount: int):
    await ctx.message.delete()
    user_id = str(ctx.author.id)
    stock_key = stock_aliases.get(stock_name.upper())

    if not stock_key or stock_key not in stock_prices:
        await ctx.send("❌ 존재하지 않는 주식입니다.")
        return
    if amount <= 0:
        await ctx.send("❌ 1 이상의 수량을 입력해주세요.")
        return
    stock = portfolio.get(user_id, {}).get(stock_key)
    quantity = stock["quantity"] if isinstance(stock, dict) else stock
    stock = portfolio.get(user_id, {}).get(stock_key)

    # 주식이 아예 없을 경우
    if stock is None:
        await ctx.send("❌ 보유 중인 해당 주식이 없습니다.")
        return

    # 구조에 따라 수량 확인
    quantity = stock["quantity"] if isinstance(stock, dict) else stock

    if quantity < amount:
        await ctx.send("❌ 보유 수량이 부족합니다.")
        return


    price = stock_prices[stock_key]["current"]
    total_earned = round(price * amount * 0.98, 2)  # 수수료 20%

    embed = discord.Embed(
        title="📤 주식 판매 확인",
        description=f"{ctx.author.mention}님, 아래 거래를 확인해주세요.",
        color=discord.Color.orange()
    )
    embed.add_field(name="종목", value=stock_key, inline=True)
    embed.add_field(name="수량", value=f"{amount} 주", inline=True)
    embed.add_field(name="수수료 차감 후", value=f"{total_earned} byte", inline=False)

    view = View()

    async def confirm_callback(interaction: discord.Interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("이 버튼은 당신의 것이 아니에요!", ephemeral=True)
            return

        portfolio[user_id][stock_key]["quantity"] -= amount
        if portfolio[user_id][stock_key]["quantity"] <= 0:
            del portfolio[user_id][stock_key]

        money_data[user_id] = money_data.get(user_id, 0) + total_earned
        save_json(money_data_file, money_data)
        save_json(portfolio_file, portfolio)

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="✅ 판매 완료",
                description=f"{stock_key} {amount}주 판매 완료!",
                color=discord.Color.green()
            ),
            view=None
        )

    async def cancel_callback(interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="❌ 판매 취소",
                description="거래가 취소되었습니다.",
                color=discord.Color.red()
            ),
            view=None
        )

    yes = Button(label="확인", style=discord.ButtonStyle.green)
    no = Button(label="취소", style=discord.ButtonStyle.red)
    yes.callback = confirm_callback
    no.callback = cancel_callback
    view.add_item(yes)
    view.add_item(no)

    await ctx.send(embed=embed, view=view)

@client.command(aliases=["주식확인"])
async def stock_status(ctx, member: discord.Member = None):
    await ctx.message.delete()
    member = member or ctx.author
    user_id = str(member.id)

    if user_id not in portfolio or not portfolio[user_id]:
        await ctx.send(f"{member.display_name}님은 보유 중인 주식이 없습니다.")
        return

    # ✅ 알림 먼저 띄우기
    if delisted_stocks.get(user_id):
        deleted_list = delisted_stocks[user_id]
        alert = ", ".join(deleted_list)
        await ctx.send(f"⚠️ 알림: `{alert}` 주식은 상장폐지되어 자동 제거되었습니다.")
        del delisted_stocks[user_id]
        save_delisted_stocks(delisted_stocks)

    embed = discord.Embed(
        title=f"📊 {member.display_name}님의 주식 상태",
        description="보유 수량 및 현재 평가 금액",
        color=discord.Color.purple()
    )

    total_value = 0.0
    total_cost = 0.0

    for name, stock in portfolio[user_id].items():
        quantity = stock.get("quantity", 0)
        avg_price = stock.get("avg_price", stock_info.get(name, {}).get("base", 0))
        current_price = stock_prices.get(name, {}).get("current", avg_price)
        value = round(current_price * quantity, 2)
        cost = round(avg_price * quantity, 2)

        total_value += value
        total_cost += cost

        # 손익률 계산
        profit_rate = ((current_price - avg_price) / avg_price * 100) if avg_price > 0 else 0
        profit_str = f"{profit_rate:+.2f}%"

        embed.add_field(
            name=name,
            value=(
                f"보유량: **{quantity}주**\n"
                f"총 매입가: **{avg_price * quantity:.2f} byte**\n"
                f"평가액: **{value:.2f} byte**\n"
                f"손익률: **{profit_str}**"
            ),
            inline=False
        )

    if total_cost > 0:
        profit_amount = round(total_value - total_cost, 2)
        total_profit_rate = (profit_amount / total_cost) * 100
        profit_str = f"{total_profit_rate:+.2f}%"
        profit_amount_str = f"{profit_amount:+.2f} byte"
    else:
        profit_str = "N/A"
        profit_amount_str = "N/A"

    embed.add_field(name="📈 총 이익금", value=f"**{profit_amount_str}**", inline=False)
    embed.add_field(name="📊 총 손익률", value=f"**{profit_str}**", inline=False)
    embed.set_footer(text=f"요청자: {ctx.author.display_name}")

    await ctx.send(embed=embed)

@client.command(aliases=["주식올인", "주식전량구매"])
async def buy_all_stock(ctx, stock_name: str):
    await ctx.message.delete()
    user_id = str(ctx.author.id)
    stock_key = stock_aliases.get(stock_name.upper())

    if not stock_key or stock_key not in stock_prices:
        await ctx.send("❌ 존재하지 않는 주식입니다.")
        return

    price = stock_prices[stock_key]["current"]
    balance = money_data.get(user_id, 0)
    max_amount = int(balance // price)

    if max_amount <= 0:
        await ctx.send("❌ 잔액이 부족합니다.")
        return

    total_cost = round(price * max_amount, 2)

    embed = discord.Embed(
        title="📥 주식 전량 구매 확인",
        description=f"{ctx.author.mention}, **{stock_key}**를 최대 수량만큼 구매하시겠습니까?",
        color=discord.Color.blue()
    )
    embed.add_field(name="구매 수량", value=f"{max_amount} 주", inline=True)
    embed.add_field(name="1주 가격", value=f"{price:.2f} byte", inline=True)
    embed.add_field(name="총 가격", value=f"{total_cost:.2f} byte", inline=False)

    view = View()

    async def confirm_callback(interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("이 버튼은 당신의 것이 아닙니다.", ephemeral=True)
            return

        money_data[user_id] -= total_cost
        portfolio.setdefault(user_id, {}).setdefault(stock_key, {"quantity": 0, "avg_price": price})
        stock = portfolio[user_id][stock_key]

        total_quantity = stock["quantity"] + max_amount
        total_spent = stock["quantity"] * stock["avg_price"] + total_cost
        stock["quantity"] = total_quantity
        stock["avg_price"] = total_spent / total_quantity

        save_json(money_data_file, money_data)
        save_json(portfolio_file, portfolio)

        result = discord.Embed(
            title="✅ 전량 구매 완료",
            description=f"{stock_key} {max_amount}주를 구매했습니다.",
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=result, view=None)

    async def cancel_callback(interaction):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="❌ 거래 취소됨",
                description="구매가 취소되었습니다.",
                color=discord.Color.red()
            ),
            view=None
        )

    yes = Button(label="확인", style=ButtonStyle.green)
    no = Button(label="취소", style=ButtonStyle.red)
    yes.callback = confirm_callback
    no.callback = cancel_callback
    view.add_item(yes)
    view.add_item(no)

    await ctx.send(embed=embed, view=view)

@client.command(aliases=["주식절반구매"])
async def buy_half_stock(ctx, stock_name: str):
    await ctx.message.delete()
    user_id = str(ctx.author.id)
    stock_key = stock_aliases.get(stock_name.upper())

    if not stock_key or stock_key not in stock_prices:
        await ctx.send("❌ 존재하지 않는 주식입니다.")
        return

    price = stock_prices[stock_key]["current"]
    balance = money_data.get(user_id, 0)

    # 현재 잔액으로 구매 가능한 최대 수량의 절반
    max_amount = int(balance // price)
    buy_amount = max_amount // 2

    if buy_amount <= 0:
        await ctx.send("❌ 잔액이 부족하거나 절반 구매가 가능한 수량이 없습니다.")
        return

    total_cost = round(price * buy_amount, 2)

    embed = discord.Embed(
        title="📥 주식 절반 구매 확인",
        description=f"{ctx.author.mention}, **{stock_key}**를 구매 가능한 최대 수량의 절반만큼 구매하시겠습니까?",
        color=discord.Color.blue()
    )
    embed.add_field(name="구매 수량", value=f"{buy_amount} 주", inline=True)
    embed.add_field(name="1주 가격", value=f"{price:.2f} byte", inline=True)
    embed.add_field(name="총 가격", value=f"{total_cost:.2f} byte", inline=False)
    embed.add_field(
        name="구매 후 예상 잔액",
        value=f"{balance - total_cost:.2f} byte",
        inline=False
    )

    view = View()

    async def confirm_callback(interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message(
                "이 버튼은 당신의 것이 아닙니다.",
                ephemeral=True
            )
            return

        # 확인 버튼을 누르기 전 잔액 및 주가가 변경되었는지 검사
        current_price = stock_prices[stock_key]["current"]
        current_balance = money_data.get(user_id, 0)

        if current_price != price or current_balance < total_cost:
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="❌ 구매 실패",
                    description="주가 또는 잔액이 변경되었습니다. 명령어를 다시 실행해주세요.",
                    color=discord.Color.red()
                ),
                view=None
            )
            return

        money_data[user_id] -= total_cost

        portfolio.setdefault(user_id, {}).setdefault(
            stock_key,
            {"quantity": 0, "avg_price": price}
        )
        stock = portfolio[user_id][stock_key]

        total_quantity = stock["quantity"] + buy_amount
        total_spent = stock["quantity"] * stock["avg_price"] + total_cost

        stock["quantity"] = total_quantity
        stock["avg_price"] = total_spent / total_quantity

        save_json(money_data_file, money_data)
        save_json(portfolio_file, portfolio)

        result = discord.Embed(
            title="✅ 절반 구매 완료",
            description=f"{stock_key} {buy_amount}주를 구매했습니다.",
            color=discord.Color.green()
        )
        result.add_field(
            name="사용 금액",
            value=f"{total_cost:.2f} byte",
            inline=True
        )
        result.add_field(
            name="남은 잔액",
            value=f"{money_data[user_id]:.2f} byte",
            inline=True
        )

        await interaction.response.edit_message(embed=result, view=None)

    async def cancel_callback(interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message(
                "이 버튼은 당신의 것이 아닙니다.",
                ephemeral=True
            )
            return

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="❌ 거래 취소됨",
                description="구매가 취소되었습니다.",
                color=discord.Color.red()
            ),
            view=None
        )

    yes = Button(label="확인", style=ButtonStyle.green)
    no = Button(label="취소", style=ButtonStyle.red)

    yes.callback = confirm_callback
    no.callback = cancel_callback

    view.add_item(yes)
    view.add_item(no)

    await ctx.send(embed=embed, view=view)

@client.command(aliases=["주식전량판매"])
async def sell_all_stock(ctx, stock_name: str = None):
    await ctx.message.delete()
    user_id = str(ctx.author.id)

    # 개별 주식 판매
    if stock_name:
        stock_key = stock_aliases.get(stock_name.upper())
        if not stock_key or stock_key not in stock_prices:
            await ctx.send("❌ 존재하지 않는 주식입니다.")
            return

        stock = portfolio.get(user_id, {}).get(stock_key)
        if not stock or stock["quantity"] <= 0:
            await ctx.send("❌ 해당 주식을 보유하고 있지 않습니다.")
            return

        quantity = stock["quantity"]
        price = stock_prices[stock_key]["current"]
        gross = price * quantity
        net = round(gross * 0.8, 2)  # 20% 수수료

        embed = discord.Embed(
            title="📤 전량 판매 확인",
            description=f"{ctx.author.mention}, **{stock_key}** {quantity}주를 판매하시겠습니까?",
            color=discord.Color.orange()
        )
        embed.add_field(name="1주 가격", value=f"{price:.2f} byte", inline=True)
        embed.add_field(name="수익 (수수료 적용)", value=f"{net:.2f} byte", inline=False)

        view = View()

        async def confirm_callback(interaction):
            if interaction.user != ctx.author:
                await interaction.response.send_message("이 버튼은 당신의 것이 아닙니다.", ephemeral=True)
                return

            del portfolio[user_id][stock_key]
            money_data[user_id] = money_data.get(user_id, 0) + net

            save_json(money_data_file, money_data)
            save_json(portfolio_file, portfolio)

            result = discord.Embed(
                title="✅ 전량 판매 완료",
                description=f"{stock_key} {quantity}주를 판매했습니다.",
                color=discord.Color.green()
            )
            await interaction.response.edit_message(embed=result, view=None)

        async def cancel_callback(interaction):
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="❌ 거래 취소됨",
                    description="판매가 취소되었습니다.",
                    color=discord.Color.red()
                ),
                view=None
            )

        yes = Button(label="확인", style=ButtonStyle.green)
        no = Button(label="취소", style=ButtonStyle.red)
        yes.callback = confirm_callback
        no.callback = cancel_callback
        view.add_item(yes)
        view.add_item(no)

        await ctx.send(embed=embed, view=view)
        return

    # 전체 주식 전량 판매
    user_stocks = portfolio.get(user_id, {})
    if not user_stocks:
        await ctx.send("❌ 보유 중인 주식이 없습니다.")
        return

    total_net = 0
    total_quantity = 0
    summary_lines = []

    for name, stock in user_stocks.items():
        q = stock["quantity"]
        avg = stock["avg_price"]
        cost = q * avg

        p = stock_prices.get(name, {}).get("current", stock_info[name]["base"])
        gross = p * q
        net = gross * 0.8

        is_loss = net < cost  # ✅ 손해 여부 판단

        if is_loss:
            summary_lines.append(f"⚠️ {name}: {q}주 → {net:.2f} byte (손해!)")
        else:
            summary_lines.append(f"{name}: {q}주 → {net:.2f} byte")

        total_quantity += q
        total_net += net

    embed = discord.Embed(
        title="📤 전체 주식 전량 판매 확인",
        description=f"{ctx.author.mention}님, 모든 보유 주식을 전량 판매하시겠습니까?",
        color=discord.Color.red()
    )
    embed.add_field(name="총 수량", value=f"{total_quantity} 주", inline=True)
    embed.add_field(name="예상 수익", value=f"{total_net:.2f} byte", inline=True)
    embed.add_field(name="📋 상세 목록", value="\n".join(summary_lines), inline=False)

    view = View()

    async def confirm_callback(interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("이 버튼은 당신의 것이 아닙니다.", ephemeral=True)
            return

        for name in list(user_stocks.keys()):
            del portfolio[user_id][name]

        money_data[user_id] = money_data.get(user_id, 0) + round(total_net, 2)

        save_json(money_data_file, money_data)
        save_json(portfolio_file, portfolio)

        result = discord.Embed(
            title="✅ 전체 주식 전량 판매 완료",
            description=f"{round(total_net, 2):.2f} byte를 획득했습니다.",
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=result, view=None)

    async def cancel_callback(interaction):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="❌ 거래 취소됨",
                description="전체 판매가 취소되었습니다.",
                color=discord.Color.red()
            ),
            view=None
        )

    yes = Button(label="확인", style=ButtonStyle.green)
    no = Button(label="취소", style=ButtonStyle.red)
    yes.callback = confirm_callback
    no.callback = cancel_callback
    view.add_item(yes)
    view.add_item(no)

    await ctx.send(embed=embed, view=view)

import matplotlib.pyplot as plt
import io
from discord import File

@client.command(aliases=["주가그래프"])
async def stock_chart(ctx, stock_name: str = None):
    await ctx.message.delete()
    if not price_history:
        await ctx.send("❌ 아직 기록된 가격 데이터가 없습니다.")
        return

    if stock_name:
        stock_key = stock_aliases.get(stock_name.upper())
        if not stock_key or stock_key not in price_history:
            await ctx.send("❌ 해당 주식의 가격 데이터가 없습니다.")
            return

        prices = price_history[stock_key]
        plt.figure(figsize=(10, 4))
        plt.plot(prices, label=stock_key)
        plt.title(f"{stock_key} 24시간 주가")
        plt.xlabel("시간 (1분 단위)")
        plt.ylabel("가격")
        plt.grid(True)
        plt.legend()

        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        plt.close()

        await ctx.send(file=File(buf, filename=f"{stock_key}_chart.png"))
    else:
        plt.figure(figsize=(12, 6))
        for name, prices in price_history.items():
            plt.plot(prices, label=name)

        plt.title("모든 주식 24시간 주가")
        plt.xlabel("시간 (1분 단위)")
        plt.ylabel("가격")
        plt.legend()
        plt.grid(True)

        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        plt.close()

        await ctx.send(file=File(buf, filename="all_stock_chart.png"))

    # 링크 임베드 추가
    link_embed = discord.Embed(
        title="📊 실시간 주식 그래프 웹사이트",
        description="[👉 그래프 웹에서 보기](https://mirimbot.netlify.app/)",
        color=discord.Color.blue()
    )
    link_embed.set_footer(text="웹사이트는 실시간 가격 데이터를 반영합니다.")
    await ctx.send(embed=link_embed)

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

async def confirm_callback(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    ctx_data = interaction.client.ctx_temp[user_id]
    amount = ctx_data["amount"]
    result = ctx_data["result"]

    if money_data.get(user_id, 0) < amount:
        await interaction.channel.send("❌ 금액이 부족합니다.")
        return

    money_data[user_id] = round(money_data[user_id] - amount, 2)
    bank_data[user_id] = bank_data.get(user_id, 0) + result

    save_money_data(money_data)
    save_bank_data(bank_data)

    embed = discord.Embed(
        title="💰 출금 완료",
        description=(
            f"출금 금액: {amount:.2f}\n"
            f"통장 적립: {result:.2f}\n"
            f"📦 현재 통장 잔액: {bank_data[user_id]:.2f}"
        ),
        color=discord.Color.green()
    )
    embed.set_footer(text=interaction.user.display_name)

    await interaction.channel.send(embed=embed)
    await interaction.message.delete()
async def cancel_callback(interaction: discord.Interaction):
    await interaction.channel.send("❌ 출금이 취소되었습니다.")
    await interaction.message.delete()

@client.command(aliases=["도박"])
async def gamble(ctx, amount: int):
    await ctx.message.delete()
    user_id = str(ctx.author.id)
    now = datetime.datetime.now()

    # 쿨타임 체크
    last_time = gamble_cooldowns.get(user_id)
    if last_time:
        elapsed = (now - last_time).total_seconds()
        if elapsed < 10:
            remain = int(10 - elapsed)
            minutes, seconds = divmod(remain, 10)
            await ctx.send(f"⏳ 아직 도박할 수 없어요! 다시 시도하려면 **{seconds}초** 기다려주세요.")
            return

    if amount <= 0:
        await ctx.send("❌ 1 이상의 금액을 입력해주세요.")
        return

    current_money = money_data.get(user_id, 0)
    if current_money < amount:
        await ctx.send("❌ 잔액이 부족합니다.")
        return

    # -100% ~ +200%
    multiplier = random.uniform(-10.0, 10.0)
    # 실제 도박 결과 계산 (float 유지)
    profit = round(amount * multiplier, 2)
    net_change = profit - amount
    new_balance = round(current_money - amount + profit, 2)


    money_data[user_id] = new_balance
    save_money_data(money_data)
    delta = round(profit - amount, 2)
    gamble_stats[user_id] = round(gamble_stats.get(user_id, 0) + delta, 2)
    save_gamble_stats(gamble_stats)

    # 쿨타임 갱신 및 저장
    gamble_cooldowns[user_id] = now
    save_gamble_cooldowns(gamble_cooldowns)

    # 결과 메시지
    color = 0x2ecc71 if profit > amount else (0xe74c3c if profit < amount else 0x95a5a6)
    outcome = "🎉 잭팟!" if multiplier > 5 else "👍 성공!" if profit > amount else "😢 손해..." if profit < amount else "💸 본전"
    net_symbol = "📈" if net_change > 0 else "📉" if net_change < 0 else "💸"

    embed = discord.Embed(
        title="🎲 도박 결과",
        description=f"{ctx.author.mention}님이 **{amount} byte**를 도박했습니다!",
        color=color
    )
    embed.add_field(name="배율", value=f"{multiplier:.2f}배", inline=True)
    embed.add_field(name="획득 금액", value=f"{profit:.2f} byte", inline=True)

    net_change = profit - amount
    net_symbol = "📈" if net_change > 0 else "📉" if net_change < 0 else "💸"
    embed.add_field(name="순이익", value=f"{net_symbol} {net_change:+.2f} byte", inline=True)

    embed.add_field(name="현재 잔액", value=f"{money_data[user_id]:.2f} byte", inline=False)
    embed.set_footer(text=outcome)

    await ctx.send(embed=embed)

@client.command(aliases=["머니랭킹"])
async def money_rank(ctx):
    await ctx.message.delete()
    if not money_data:
        await ctx.send("❌ 데이터가 없습니다.")
        return

    # 금액 기준 내림차순 정렬
    sorted_users = sorted(money_data.items(), key=lambda x: x[1], reverse=True)

    embed = discord.Embed(
        title="💰 머니 랭킹 TOP 10",
        description="현재 보유한 byte 기준 랭킹입니다.",
        color=discord.Color.gold()
    )

    for i, (user_id, amount) in enumerate(sorted_users[:10], start=1):
        member = ctx.guild.get_member(int(user_id))
        name = member.display_name if member else f"알 수 없음 ({user_id})"
        embed.add_field(name=f"{i}위: {name}", value=f"{amount:.2f} byte", inline=False)

    await ctx.send(embed=embed)

@client.command(aliases=["도박랭킹"])
async def gamble_rank(ctx):
    await ctx.message.delete()
    if not gamble_stats:
        await ctx.send("❌ 아직 도박 기록이 없습니다.")
        return

    sorted_users = sorted(gamble_stats.items(), key=lambda x: x[1], reverse=True)

    embed = discord.Embed(
        title="🎰 도박 수익 랭킹 TOP 10",
        description="도박으로 가장 많이 벌거나 잃은 유저 순위입니다.",
        color=discord.Color.purple()
    )

    for i, (user_id, profit) in enumerate(sorted_users[:10], start=1):
        member = ctx.guild.get_member(int(user_id))
        name = member.display_name if member else f"알 수 없음 ({user_id})"
        symbol = "📈" if profit > 0 else "📉" if profit < 0 else "💸"
        embed.add_field(name=f"{i}위: {name}", value=f"{symbol} {profit:+.2f} byte", inline=False)

    await ctx.send(embed=embed)

@client.command(aliases=["주식랭킹"])
async def stock_rank(ctx):
    await ctx.message.delete()

    user_profits = []

    for user_id, stocks in portfolio.items():
        total_cost = 0.0
        total_value = 0.0

        for name, data in stocks.items():
            quantity = data.get("quantity", 0)
            avg_price = data.get("avg_price", 0)
            current_price = stock_prices.get(name, {}).get("current", avg_price)

            total_cost += quantity * avg_price
            total_value += quantity * current_price

        if total_cost == 0:
            continue  # 매입 금액이 없으면 계산 불가

        profit = total_value - total_cost
        profit_rate = (profit / total_cost) * 100

        user_profits.append((user_id, round(profit, 2), round(profit_rate, 2)))

    if not user_profits:
        await ctx.send("❌ 주식을 보유한 유저가 없습니다.")
        return

    # 수익금 기준 내림차순 정렬
    user_profits.sort(key=lambda x: x[1], reverse=True)

    embed = discord.Embed(
        title="📈 주식 수익 랭킹 TOP 10",
        description="보유 주식의 총 수익금 기준 랭킹입니다.",
        color=discord.Color.teal()
    )

    for i, (user_id, profit, rate) in enumerate(user_profits[:10], start=1):
        member = ctx.guild.get_member(int(user_id))
        name = member.display_name if member else f"알 수 없음 ({user_id})"
        symbol = "📈" if profit > 0 else "📉" if profit < 0 else "💸"
        embed.add_field(
            name=f"{i}위: {name}",
            value=f"{symbol} 수익금: {profit:+.2f} byte\n💹 수익률: {rate:+.2f}%",
            inline=False
        )

    await ctx.send(embed=embed)

@client.command(aliases=["도박올인"])
async def gamble_allin(ctx):
    await ctx.message.delete()
    user_id = str(ctx.author.id)
    now = datetime.datetime.now()

    current_money = money_data.get(user_id, 0)

    if current_money <= 0:
        await ctx.send("❌ 잔액이 부족합니다.")
        return

    # 쿨타임 체크
    last_time = gamble_cooldowns.get(user_id)
    if last_time:
        elapsed = (now - last_time).total_seconds()
        if elapsed < 10:
            remain = int(10 - elapsed)
            minutes, seconds = divmod(remain, 10)
            await ctx.send(f"⏳ 아직 도박할 수 없어요! 다시 시도하려면 **{seconds}초** 기다려주세요.")
            return

    amount = current_money  # 올인!

    # 도박 결과 계산
    multiplier = random.uniform(-10.0, 10.0)
    profit = round(amount * multiplier, 2)
    net_change = profit - amount
    new_balance = round(current_money - amount + profit, 2)
    save_gamble_stats(gamble_stats)

    money_data[user_id] = new_balance
    save_money_data(money_data)

    # 도박 통계
    delta = net_change
    gamble_stats[user_id] = round(gamble_stats.get(user_id, 0) + delta, 2)
    save_gamble_stats(gamble_stats)

    # 쿨타임 저장
    gamble_cooldowns[user_id] = now
    save_gamble_cooldowns(gamble_cooldowns)

    # 결과 메시지
    color = 0x2ecc71 if profit > amount else (0xe74c3c if profit < amount else 0x95a5a6)
    outcome = "🎉 잭팟!" if multiplier > 5 else "👍 성공!" if profit > amount else "😢 손해..." if profit < amount else "💸 본전"
    net_symbol = "📈" if net_change > 0 else "📉" if net_change < 0 else "💸"

    embed = discord.Embed(
        title="🎲 도박 올인 결과",
        description=f"{ctx.author.mention}님이 **{amount:.2f} byte**를 올인했습니다!",
        color=color
    )
    embed.add_field(name="배율", value=f"{multiplier:.2f}배", inline=True)
    embed.add_field(name="획득 금액", value=f"{profit:.2f} byte", inline=True)
    embed.add_field(name="순이익", value=f"{net_symbol} {net_change:+.2f} byte", inline=True)
    embed.add_field(name="현재 잔액", value=f"{money_data[user_id]:.2f} byte", inline=False)
    embed.set_footer(text=outcome)

    await ctx.send(embed=embed)

@client.command(aliases=["위로금"])
async def consolation(ctx):
    await ctx.message.delete()
    user_id = str(ctx.author.id)
    today = datetime.datetime.now().strftime("%Y-%m-%d")

    if consolation_data.get(user_id) == today:
        await ctx.send("❌ 이미 오늘 위로금을 받으셨습니다. 내일 다시 시도해주세요.")
        return

    base_amount = random.randint(1, 1000)
    bonus_amount = 0

    # ✅ 머니가 마이너스일 경우 추가 위로금 지급
    money_balance = money_data.get(user_id, 0)
    if money_balance < 0:
        debt = abs(money_balance)
        bonus_amount = int(500 * math.sqrt(debt))

    total_amount = base_amount + bonus_amount
    money_data[user_id] = money_balance + total_amount
    save_money_data(money_data)

    consolation_data[user_id] = today
    save_consolation(consolation_data)

    # ✅ 메시지 출력
    description = f"{ctx.author.mention}님께 {base_amount} byte를 지급했습니다!"
    if bonus_amount > 0:
        description += f"\n💸 추가 위로금 +{bonus_amount} byte (머니 {money_balance + total_amount:.2f} byte)"

    embed = discord.Embed(
        title="💸 위로금 지급 완료!",
        description=description,
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)

import json
import datetime
import os
import discord
from discord.ext import commands
from discord.ui import View, Modal, TextInput, Button
from discord import ButtonStyle

BANK_SYSTEM_FILE = "bank_system.json"
money_data_file = "money_data.json"

LOAN_DEADLINE_HOURS = 24
COLLECTION_INTERVAL_SECONDS = 60


# =========================
# JSON 데이터 관리
# =========================

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                result = json.load(f)
                return result if isinstance(result, dict) else default
        except (json.JSONDecodeError, OSError):
            return default
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


bank_system = load_json(BANK_SYSTEM_FILE, {})
money_data = load_json(money_data_file, {})


def ensure_bank_user(user_id):
    user_id = str(user_id)

    if user_id not in bank_system:
        bank_system[user_id] = {
            "loans": [],
            "deposit_amount": 0.0,
            "deposit_start": None,
            "unpaid_amount": 0.0
        }

    data = bank_system[user_id]

    data.setdefault("loans", [])
    data.setdefault("deposit_amount", 0.0)
    data.setdefault("deposit_start", None)
    data.setdefault("unpaid_amount", 0.0)

    # 구버전의 단일 대출 데이터를 새 대출 목록으로 변환
    old_amount = float(data.get("loan_amount", 0) or 0)

    if not data["loans"] and old_amount > 0:
        data["loans"].append({
            "amount": old_amount,
            "date": (
                data.get("loan_date")
                or datetime.datetime.now().isoformat()
            ),
            "collected": False
        })

    # 구버전 신용점수 시스템 제거
    data.pop("credit_score", None)

    save_json(BANK_SYSTEM_FILE, bank_system)
    return data


def get_total_loan(data):
    return sum(
        max(0.0, float(loan.get("amount", 0)))
        for loan in data["loans"]
    )


def parse_amount(value):
    try:
        amount = float(value.replace(",", "").strip())

        if not math.isfinite(amount):
            return None

        return amount

    except (ValueError, AttributeError, TypeError):
        return None


def get_server_average_balance():
    """
    잔액이 양수인 유저만 평균에 포함한다.
    """
    balances = []

    for balance in money_data.values():
        try:
            balance = float(balance)

            if math.isfinite(balance) and balance > 0:
                balances.append(balance)

        except (ValueError, TypeError):
            continue

    if not balances:
        return 0.0

    return sum(balances) / len(balances)


# =========================
# 강제징수 처리
# =========================

def collect_overdue(user_id):
    """
    대출별 24시간 경과 여부를 확인한다.

    강제징수액 = 대출 원금의 제곱
    잔액이 부족하면 보유 잔액을 징수하고 부족분을 미납금에 누적한다.
    이미 처리한 대출은 다시 징수하지 않는다.
    """
    user_id = str(user_id)
    data = ensure_bank_user(user_id)
    now = datetime.datetime.now()

    try:
        balance = float(money_data.get(user_id, 0))
    except (ValueError, TypeError):
        balance = 0.0

    messages = []
    changed = False

    for loan in data["loans"]:
        if loan.get("collected", False):
            continue

        try:
            loan_date = datetime.datetime.fromisoformat(loan["date"])
            principal = float(loan["amount"])
        except (ValueError, TypeError, KeyError):
            continue

        deadline = loan_date + datetime.timedelta(
            hours=LOAN_DEADLINE_HOURS
        )

        if now < deadline:
            continue

        if principal <= 0:
            loan["collected"] = True
            changed = True
            continue

        collection_amount = principal ** 2

        # 징수 가능한 금액은 현재 보유 잔액까지
        collected_now = min(max(balance, 0.0), collection_amount)
        balance -= collected_now

        unpaid = max(0.0, collection_amount - collected_now)

        data["unpaid_amount"] = (
            float(data.get("unpaid_amount", 0)) + unpaid
        )

        # 중복 징수 방지
        loan["collected"] = True
        loan["collection_amount"] = collection_amount
        loan["collected_amount"] = collected_now
        loan["unpaid_from_loan"] = unpaid
        loan["collected_at"] = now.isoformat()

        changed = True

        message = (
            f"대출 원금 {principal:.2f} Byte: "
            f"징수 {collected_now:.2f} Byte"
        )

        if unpaid > 0:
            message += f", 미납 {unpaid:.2f} Byte"

        messages.append(message)

    if changed:
        money_data[user_id] = round(balance, 2)
        save_json(money_data_file, money_data)
        save_json(BANK_SYSTEM_FILE, bank_system)

    return messages


def collect_all_overdue():
    """
    저장된 모든 유저의 대출을 검사한다.
    은행 명령어를 사용하지 않은 유저의 연체도 처리한다.
    """
    all_messages = []

    for user_id in list(bank_system.keys()):
        messages = collect_overdue(user_id)

        if messages:
            all_messages.append((user_id, messages))

    return all_messages


# =========================
# 자동 강제징수 작업
# =========================

@tasks.loop(seconds=COLLECTION_INTERVAL_SECONDS)
async def bank_collection_loop():
    try:
        results = await asyncio.to_thread(collect_all_overdue)

        for user_id, messages in results:
            print(
                f"[은행 강제징수] 유저 {user_id}: "
                + " / ".join(messages)
            )

    except Exception as e:
        print(f"[은행 강제징수 오류] {e}")


@bank_collection_loop.before_loop
async def before_bank_collection_loop():
    await client.wait_until_ready()


# on_ready 이벤트를 이미 사용 중이라면 기존 on_ready에
# 아래의 시작 코드를 합쳐서 사용해야 한다.
@client.listen("on_ready")
async def start_bank_collection_loop():
    if not bank_collection_loop.is_running():
        bank_collection_loop.start()

    # 봇이 꺼져 있던 동안 발생한 연체도 시작 시 검사
    try:
        results = await asyncio.to_thread(collect_all_overdue)

        for user_id, messages in results:
            print(
                f"[은행 재시작 강제징수] 유저 {user_id}: "
                + " / ".join(messages)
            )

    except Exception as e:
        print(f"[은행 시작 시 강제징수 오류] {e}")


# =========================
# 은행 명령어
# =========================

@client.command(aliases=["은행"])
async def bank(ctx):
    await ctx.message.delete()

    user_id = str(ctx.author.id)
    data = ensure_bank_user(user_id)

    # 명령어 실행 시에도 즉시 연체 확인
    collection_messages = await asyncio.to_thread(
        collect_overdue,
        user_id
    )

    data = ensure_bank_user(user_id)

    total_loan = get_total_loan(data)
    average_balance = get_server_average_balance()
    max_loan = average_balance

    deadline_lines = []

    for index, loan in enumerate(data["loans"], start=1):
        if loan.get("collected", False):
            continue

        try:
            loan_date = datetime.datetime.fromisoformat(loan["date"])
        except (ValueError, TypeError, KeyError):
            continue

        deadline = loan_date + datetime.timedelta(
            hours=LOAN_DEADLINE_HOURS
        )

        remain = deadline - datetime.datetime.now()

        if remain.total_seconds() > 0:
            total_seconds = int(remain.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            deadline_text = f"{hours}시간 {minutes}분 남음"
        else:
            deadline_text = "강제징수 대기"

        deadline_lines.append(
            f"대출 {index}: {float(loan['amount']):.2f} Byte "
            f"({deadline_text})"
        )

    embed = discord.Embed(
        title="🏦 은행 시스템",
        description="버튼을 눌러 기능을 선택하세요.",
        color=discord.Color.teal()
    )

    embed.add_field(
        name="💳 총 대출금",
        value=f"{total_loan:.2f} Byte",
        inline=True
    )

    embed.add_field(
        name="💰 적금 원금",
        value=f"{float(data['deposit_amount']):.2f} Byte",
        inline=True
    )

    embed.add_field(
        name="⚠️ 미납 강제징수액",
        value=f"{float(data['unpaid_amount']):.2f} Byte",
        inline=True
    )

    embed.add_field(
        name="🏦 최대 총대출 한도",
        value=f"{max_loan:.2f} Byte",
        inline=True
    )

    embed.add_field(
        name="📆 대출별 강제징수 기한",
        value=(
            "\n".join(deadline_lines)
            if deadline_lines
            else "진행 중인 대출 없음"
        ),
        inline=False
    )

    embed.set_footer(
        text=f"요청자: {ctx.author}",
        icon_url=ctx.author.avatar.url if ctx.author.avatar else None
    )

    if collection_messages:
        embed.add_field(
            name="🚨 강제징수 결과",
            value="\n".join(collection_messages),
            inline=False
        )

    view = View(timeout=300)

    loan_button = Button(
        label="💵 대출",
        style=ButtonStyle.green
    )
    repay_button = Button(
        label="✅ 상환",
        style=ButtonStyle.primary
    )
    deposit_button = Button(
        label="💰 적금",
        style=ButtonStyle.secondary
    )
    withdraw_button = Button(
        label="💳 출금",
        style=ButtonStyle.red
    )

    async def loan_callback(interaction):
        if str(interaction.user.id) != user_id:
            return await interaction.response.send_message(
                "이 버튼은 당신의 것이 아닙니다.",
                ephemeral=True
            )

        await interaction.response.send_modal(LoanModal(user_id))

    async def repay_callback(interaction):
        if str(interaction.user.id) != user_id:
            return await interaction.response.send_message(
                "이 버튼은 당신의 것이 아닙니다.",
                ephemeral=True
            )

        await interaction.response.send_modal(RepayModal(user_id))

    async def deposit_callback(interaction):
        if str(interaction.user.id) != user_id:
            return await interaction.response.send_message(
                "이 버튼은 당신의 것이 아닙니다.",
                ephemeral=True
            )

        await interaction.response.send_modal(DepositModal(user_id))

    async def withdraw_callback(interaction):
        if str(interaction.user.id) != user_id:
            return await interaction.response.send_message(
                "이 버튼은 당신의 것이 아닙니다.",
                ephemeral=True
            )

        await interaction.response.send_modal(WithdrawModal(user_id))

    loan_button.callback = loan_callback
    repay_button.callback = repay_callback
    deposit_button.callback = deposit_callback
    withdraw_button.callback = withdraw_callback

    view.add_item(loan_button)
    view.add_item(repay_button)
    view.add_item(deposit_button)
    view.add_item(withdraw_button)

    await ctx.send(embed=embed, view=view)


# =========================
# 대출
# =========================

class LoanModal(Modal, title="💵 대출 금액 입력"):
    amount = TextInput(
        label="대출할 금액",
        placeholder="숫자만 입력",
        required=True
    )

    def __init__(self, user_id):
        super().__init__()
        self.user_id = str(user_id)

    async def on_submit(self, interaction):
        amount = parse_amount(self.amount.value)

        if amount is None or amount <= 0:
            return await interaction.response.send_message(
                "❌ 올바른 대출 금액을 입력하세요.",
                ephemeral=True
            )

        # 신청자 본인의 연체 대출부터 처리
        await asyncio.to_thread(collect_overdue, self.user_id)

        data = ensure_bank_user(self.user_id)

        # 총대출금 기준으로 한도 검사
        average_balance = get_server_average_balance()
        max_total_loan = average_balance
        current_total_loan = get_total_loan(data)
        remaining_limit = max(
            0.0,
            max_total_loan - current_total_loan
        )

        if amount > remaining_limit:
            return await interaction.response.send_message(
                f"❌ 대출 한도를 초과했습니다.\n"
                f"서버 평균 잔액: {average_balance:.2f} Byte\n"
                f"현재 총대출금: {current_total_loan:.2f} Byte\n"
                f"최대 총대출 한도: {max_total_loan:.2f} Byte\n"
                f"추가 대출 가능 금액: {remaining_limit:.2f} Byte",
                ephemeral=True
            )

        data["loans"].append({
            "amount": amount,
            "date": datetime.datetime.now().isoformat(),
            "collected": False
        })

        money_data[self.user_id] = (
            float(money_data.get(self.user_id, 0)) + amount
        )

        save_json(money_data_file, money_data)
        save_json(BANK_SYSTEM_FILE, bank_system)

        await interaction.response.send_message(
            f"✅ {amount:.2f} Byte 대출 완료!\n"
            f"현재 총대출금: {get_total_loan(data):.2f} Byte\n"
            f"최대 총대출 한도: {max_total_loan:.2f} Byte\n"
            f"대출일로부터 24시간 후 강제징수됩니다.",
            ephemeral=True
        )


# =========================
# 상환
# =========================

class RepayModal(Modal, title="✅ 상환 금액 입력"):
    amount = TextInput(
        label="상환할 금액",
        placeholder="숫자만 입력",
        required=True
    )

    def __init__(self, user_id):
        super().__init__()
        self.user_id = str(user_id)

    async def on_submit(self, interaction):
        amount = parse_amount(self.amount.value)

        if amount is None or amount <= 0:
            return await interaction.response.send_message(
                "❌ 올바른 상환 금액을 입력하세요.",
                ephemeral=True
            )

        data = ensure_bank_user(self.user_id)
        balance = float(money_data.get(self.user_id, 0))
        total_loan = get_total_loan(data)

        if total_loan <= 0:
            return await interaction.response.send_message(
                "❌ 상환할 대출이 없습니다.",
                ephemeral=True
            )

        if amount > total_loan:
            return await interaction.response.send_message(
                f"❌ 총 대출금은 {total_loan:.2f} Byte입니다.",
                ephemeral=True
            )

        if amount > balance:
            return await interaction.response.send_message(
                "❌ 잔액이 부족합니다.",
                ephemeral=True
            )

        remaining = amount

        # 오래된 대출부터 상환
        for loan in data["loans"]:
            if remaining <= 0:
                break

            loan_amount = float(loan["amount"])
            paid = min(loan_amount, remaining)

            loan["amount"] = round(loan_amount - paid, 2)
            remaining = round(remaining - paid, 2)

        data["loans"] = [
            loan for loan in data["loans"]
            if float(loan["amount"]) > 0.001
        ]

        money_data[self.user_id] = round(balance - amount, 2)

        save_json(money_data_file, money_data)
        save_json(BANK_SYSTEM_FILE, bank_system)

        await interaction.response.send_message(
            f"✅ {amount:.2f} Byte 상환 완료!\n"
            f"남은 대출금: {get_total_loan(data):.2f} Byte",
            ephemeral=True
        )


# =========================
# 적금
# =========================

class DepositModal(Modal, title="💰 적금 금액 입력"):
    amount = TextInput(
        label="적금할 금액",
        placeholder="숫자만 입력",
        required=True
    )

    def __init__(self, user_id):
        super().__init__()
        self.user_id = str(user_id)

    async def on_submit(self, interaction):
        amount = parse_amount(self.amount.value)

        if amount is None or amount <= 0:
            return await interaction.response.send_message(
                "❌ 올바른 적금 금액을 입력하세요.",
                ephemeral=True
            )

        data = ensure_bank_user(self.user_id)
        balance = float(money_data.get(self.user_id, 0))

        if balance < amount:
            return await interaction.response.send_message(
                "❌ 잔액이 부족합니다.",
                ephemeral=True
            )

        now = datetime.datetime.now()

        if float(data["deposit_amount"]) <= 0:
            data["deposit_start"] = now.isoformat()

        data["deposit_amount"] = round(
            float(data["deposit_amount"]) + amount,
            2
        )

        money_data[self.user_id] = round(balance - amount, 2)

        save_json(money_data_file, money_data)
        save_json(BANK_SYSTEM_FILE, bank_system)

        await interaction.response.send_message(
            f"✅ {amount:.2f} Byte 적금 완료!\n"
            f"현재 적금 원금: {data['deposit_amount']:.2f} Byte",
            ephemeral=True
        )


# =========================
# 적금 부분 출금 / 전액 출금
# =========================

class WithdrawModal(Modal, title="💳 적금 출금"):
    amount = TextInput(
        label="출금할 금액 (전액은 '전액')",
        placeholder="예: 1000 또는 전액",
        required=True
    )

    def __init__(self, user_id):
        super().__init__()
        self.user_id = str(user_id)

    async def on_submit(self, interaction):
        data = ensure_bank_user(self.user_id)

        principal = float(data["deposit_amount"])

        if principal <= 0:
            return await interaction.response.send_message(
                "❌ 적금이 없습니다.",
                ephemeral=True
            )

        now = datetime.datetime.now()
        start_str = data.get("deposit_start")

        if start_str:
            start = datetime.datetime.fromisoformat(start_str)
            days = max((now - start).days, 0)
        else:
            days = 0

        # 기존 일복리 10% 유지
        multiplier = 1.1 ** days
        total_value = principal * multiplier

        raw_amount = self.amount.value.strip()

        if raw_amount.lower() in ("전액", "전체", "all", "max"):
            withdraw_amount = total_value
        else:
            withdraw_amount = parse_amount(raw_amount)

            if withdraw_amount is None or withdraw_amount <= 0:
                return await interaction.response.send_message(
                    "❌ 올바른 출금 금액을 입력하세요.",
                    ephemeral=True
                )

            if withdraw_amount > total_value:
                return await interaction.response.send_message(
                    f"❌ 출금 가능 금액은 {total_value:.2f} Byte입니다.",
                    ephemeral=True
                )

        withdraw_amount = round(withdraw_amount, 2)

        # 출금액에 비례해 적금 원금 차감
        principal_to_remove = min(
            principal,
            withdraw_amount / multiplier
        )

        remaining_principal = max(
            0.0,
            principal - principal_to_remove
        )

        money_data[self.user_id] = round(
            float(money_data.get(self.user_id, 0)) + withdraw_amount,
            2
        )

        if remaining_principal < 0.01:
            data["deposit_amount"] = 0.0
            data["deposit_start"] = None
        else:
            data["deposit_amount"] = round(
                remaining_principal,
                2
            )

            # 잔여 적금의 이자는 출금 시점부터 다시 계산
            data["deposit_start"] = now.isoformat()

        save_json(money_data_file, money_data)
        save_json(BANK_SYSTEM_FILE, bank_system)

        await interaction.response.send_message(
            f"✅ {withdraw_amount:.2f} Byte 출금 완료!\n"
            f"남은 적금 원금: {data['deposit_amount']:.2f} Byte",
            ephemeral=True
        )

WELFARE_FILE = "welfare_data.json"

def load_welfare():
    return load_json(WELFARE_FILE, {})

def save_welfare(data):
    save_json(WELFARE_FILE, data)

@client.command(aliases=["기초수급"])
async def welfare(ctx):
    await ctx.message.delete()
    user_id = str(ctx.author.id)
    today = datetime.datetime.now().date()

    welfare_data = load_welfare()
    user = welfare_data.get(user_id, {"last_claim": None, "streak": 0})

    last_claim_date = datetime.date.fromisoformat(user["last_claim"]) if user["last_claim"] else None

    if last_claim_date == today:
        embed = discord.Embed(
            title="📛 수급 불가",
            description="오늘은 이미 기초수급을 받으셨습니다.",
            color=discord.Color.red()
        )
        embed.set_footer(text="내일 다시 이용해주세요.")
        return await ctx.send(embed=embed)

    # 연속 수급 여부 확인
    yesterday = today - datetime.timedelta(days=1)
    if last_claim_date == yesterday:
        user["streak"] += 1
    else:
        user["streak"] = 0

    bonus_times = min(user["streak"], 20)
    amount = 10000 * (4 ** bonus_times)

    # 지급
    money_data[user_id] = money_data.get(user_id, 0) + amount
    save_json(money_data_file, money_data)

    # 수급 정보 저장
    user["last_claim"] = today.isoformat()
    welfare_data[user_id] = user
    save_welfare(welfare_data)

    embed = discord.Embed(
        title="✅ 기초수급 지급 완료!",
        color=discord.Color.green()
    )
    embed.add_field(name="💰 지급 금액", value=f"{amount} byte", inline=True)
    embed.add_field(name="📆 연속 수급", value=f"{user['streak'] + 1}일차", inline=True)
    embed.set_footer(text="내일 다시 오시면 2배 보너스를 받을 수 있어요!")
    embed.set_author(name=str(ctx.author), icon_url=ctx.author.avatar.url if ctx.author.avatar else None)

    await ctx.send(embed=embed)

bankruptcy_data_file = "bankruptcy_data.json"

def load_bankruptcy():
    try:
        with open(bankruptcy_data_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_bankruptcy(data):
    with open(bankruptcy_data_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

@client.command()
async def 파산(ctx):
    await ctx.message.delete()

    user_id = str(ctx.author.id)
    money = money_data.get(user_id, 0)
    today = datetime.datetime.now().date().isoformat()

    bankruptcy_data = load_bankruptcy()
    last_bankruptcy = bankruptcy_data.get(user_id)

    if last_bankruptcy == today:
        embed = discord.Embed(
            title="📛 파산 불가",
            description="오늘은 이미 파산했습니다.",
            color=discord.Color.red()
        )
        embed.set_footer(text="내일 다시 이용해주세요.")
        return await ctx.send(embed=embed)

    embed = discord.Embed(
        title="⚠️ 파산 확인",
        description=(
            f"현재 보유한 돈이 **{money:,} byte** 있습니다.\n\n"
            "정말 파산하시겠습니까?\n"
            "파산하면 보유한 돈이 전부 **0 byte**로 초기화됩니다."
        ),
        color=discord.Color.orange()
    )

    class BankruptcyView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=30)

        async def interaction_check(self, interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message(
                    "❌ 명령어를 실행한 사람만 선택할 수 있습니다.",
                    ephemeral=True
                )
                return False
            return True

        @discord.ui.button(
            label="파산하기",
            style=discord.ButtonStyle.danger,
            emoji="💸"
        )
        async def confirm(
            self,
            interaction: discord.Interaction,
            button: discord.ui.Button
        ):
            try:
                money_data[user_id] = 0
                save_json(money_data_file, money_data)

                bankruptcy_data = load_bankruptcy()
                bankruptcy_data[user_id] = datetime.datetime.now().date().isoformat()
                save_bankruptcy(bankruptcy_data)

                for item in self.children:
                    item.disabled = True

                result_embed = discord.Embed(
                    title="💸 파산 완료",
                    description=(
                        f"기존 보유 금액: **{money:,} byte**\n"
                        "현재 보유 금액: **0 byte**\n\n"
                        "모든 돈을 잃었습니다. 다시 열심히 모아보세요!"
                    ),
                    color=discord.Color.red()
                )

                await interaction.response.edit_message(
                    embed=result_embed,
                    view=self
                )

            except Exception as e:
                print(f"[파산 버튼 오류] {type(e).__name__}: {e}")

                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ 파산 처리 중 오류가 발생했습니다. 관리자에게 문의해주세요.",
                        ephemeral=True
                    )

        @discord.ui.button(
            label="취소",
            style=discord.ButtonStyle.secondary,
            emoji="❌"
        )
        async def cancel(
            self,
            interaction: discord.Interaction,
            button: discord.ui.Button
        ):
            for item in self.children:
                item.disabled = True

            cancel_embed = discord.Embed(
                title="✅ 파산 취소",
                description="파산을 취소했습니다. 기존 자산은 그대로 유지됩니다.",
                color=discord.Color.green()
            )

            await interaction.response.edit_message(
                embed=cancel_embed,
                view=self
            )

        async def on_timeout(self):
            for item in self.children:
                item.disabled = True

            # 메시지가 이미 삭제되었거나 수정할 수 없으면 무시
            try:
                if self.message:
                    await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    view = BankruptcyView()
    message = await ctx.send(embed=embed, view=view)
    view.message = message


# 유저 찾기 함수
async def find_member(ctx, name_or_mention):
    if name_or_mention.startswith("<@") and name_or_mention.endswith(">"):
        user_id = int(name_or_mention.strip("<@!>"))
        return ctx.guild.get_member(user_id)
    for member in ctx.guild.members:
        if member.name == name_or_mention or member.display_name == name_or_mention:
            return member
    return None

# 경고 명령어
@client.command(aliases=["경고"])
@commands.has_permissions(administrator=True)
async def warn(ctx, name: str, amount: int = 1, *, reason: str = None):
    await ctx.message.delete()
    member = await find_member(ctx, name)

    if not member:
        await ctx.send(f"❌ 유저 `{name}` 을 찾을 수 없습니다. 정확한 닉네임이나 멘션을 입력해주세요.")
        return

    guild_id = str(ctx.guild.id)
    user_id = str(member.id)
    view = View()

    async def confirm_callback(interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("❌ 당신의 명령이 아닙니다.", ephemeral=True)
            return

        # 서버 ID에 해당하는 딕셔너리 생성
        if guild_id not in warnings_data:
            warnings_data[guild_id] = {}
        if user_id not in warnings_data[guild_id]:
            warnings_data[guild_id][user_id] = {"count": 0, "reasons": []}

        # 경고 수 갱신
        warnings_data[guild_id][user_id]["count"] += amount
        warnings_data[guild_id][user_id]["count"] = max(0, warnings_data[guild_id][user_id]["count"])

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        punishment = "없음"
        count = warnings_data[guild_id][user_id]["count"]

        try:
            if amount >= 0:
                if count == 1:
                    await member.timeout(datetime.timedelta(minutes=5))
                    punishment = "타임아웃 5분"
                elif count == 2:
                    await member.timeout(datetime.timedelta(minutes=10))
                    punishment = "타임아웃 10분"
                elif count == 3:
                    await member.timeout(datetime.timedelta(hours=1))
                    punishment = "타임아웃 1시간"
                elif count == 4:
                    await member.timeout(datetime.timedelta(days=1))
                    punishment = "타임아웃 1일"
                elif count == 5:
                    await member.timeout(datetime.timedelta(days=7))
                    punishment = "타임아웃 7일"
                elif count == 6:
                    role = ctx.guild.get_role(1352540239985643571)
                    await member.add_roles(role)
                    end_time = datetime.datetime.now() + datetime.timedelta(days=3)
                    warnings_data[guild_id][user_id]["restriction_until"] = end_time.strftime("%Y-%m-%d %H:%M:%S")
                    punishment = "서버 이용제한 역할 부여 (3일)"
                elif count == 7:
                    role = ctx.guild.get_role(1352540239985643571)
                    await member.add_roles(role)
                    end_time = datetime.datetime.now() + datetime.timedelta(days=7)
                    warnings_data[guild_id][user_id]["restriction_until"] = end_time.strftime("%Y-%m-%d %H:%M:%S")
                    punishment = "서버 이용제한 역할 부여 (7일)"
                elif count == 8:
                    role = ctx.guild.get_role(1352540239985643571)
                    await member.add_roles(role)
                    end_time = datetime.datetime.now() + datetime.timedelta(days=30)
                    warnings_data[guild_id][user_id]["restriction_until"] = end_time.strftime("%Y-%m-%d %H:%M:%S")
                    punishment = "서버 이용제한 역할 부여 (30일)"
                elif count == 9:
                    role = ctx.guild.get_role(1352540239985643571)
                    await member.add_roles(role)
                    end_time = datetime.datetime.now() + datetime.timedelta(days=90)
                    warnings_data[guild_id][user_id]["restriction_until"] = end_time.strftime("%Y-%m-%d %H:%M:%S")
                    punishment = "서버 이용제한 역할 부여 (90일)"
                elif count >= 10:
                    await member.ban(reason="경고 10회 누적 - 자동 차단")
                    punishment = "영구 차단 (자동 밴)"

                warnings_data[guild_id][user_id]["reasons"].append(f"{now} - {reason} (처벌: {punishment})")
            else:
                warnings_data[guild_id][user_id]["reasons"].append(f"{now} - ❌ 경고 취소: {reason}")
        except Exception as e:
            punishment += f" ⚠️ 제재 실패: {e}"

        save_warnings(warnings_data)

        embed = discord.Embed(
            title="⚠️ 경고 완료",
            description=f"{member.mention}님에게 경고 {amount}회를 적용했습니다.\n현재 총 경고 수: {count}회\n처벌: {punishment}",
            color=discord.Color.red()
        )
        await interaction.response.edit_message(embed=embed, view=None)

    async def cancel_callback(interaction):
        embed = discord.Embed(title="❌ 작업 취소됨", color=discord.Color.light_grey())
        await interaction.response.edit_message(embed=embed, view=None)

    yes = Button(label="확인", style=discord.ButtonStyle.red)
    no = Button(label="취소", style=discord.ButtonStyle.grey)
    yes.callback = confirm_callback
    no.callback = cancel_callback
    view.add_item(yes)
    view.add_item(no)

    embed = discord.Embed(
        title="🚨 경고 확인",
        description=f"{member.mention}에게 경고 {amount}회를 적용하려고 합니다.\n사유: {reason}\n정말 진행하시겠습니까?",
        color=discord.Color.orange()
    )
    await ctx.send(embed=embed, view=view)

@client.command(aliases=["경고확인"])
async def check_warning(ctx, *, target: str = None):
    await ctx.message.delete()
    if target:
        member = None
        # 멘션일 경우
        if target.startswith("<@") and target.endswith(">"):
            try:
                user_id = int(target.strip("<@!>"))
                member = ctx.guild.get_member(user_id)
            except:
                pass
        # 이름으로 찾기
        if not member:
            for m in ctx.guild.members:
                if m.name == target or m.display_name == target:
                    member = m
                    break
        if not member:
            await ctx.send(f"❌ 유저 `{target}` 를 찾을 수 없습니다.")
            return
    else:
        member = ctx.author

    guild_id = str(ctx.guild.id)
    user_id = str(member.id)

    data = warnings_data.get(guild_id, {}).get(user_id)

    if not data:
        await ctx.send(f"✅ {member.display_name}님은 경고 기록이 없습니다.")
        return

    embed = discord.Embed(
        title=f"⚠️ {member.display_name}님의 경고 내역",
        color=discord.Color.orange()
    )
    embed.add_field(name="총 경고 수", value=f"{data.get('count', 0)}회", inline=False)

    reasons = data.get("reasons", [])
    if reasons:
        for i, reason in enumerate(reasons[-10:], 1):  # 최근 10개만 표시
            embed.add_field(name=f"{i}.", value=reason, inline=False)
    else:
        embed.add_field(name="📄 사유 없음", value="경고 사유가 없습니다.", inline=False)

    if "restriction_until" in data:
        embed.add_field(name="⏳ 이용제한 만료 예정", value=data["restriction_until"], inline=False)

    await ctx.send(embed=embed)

from discord.ui import View, Button
from discord import Interaction

class CheckinButtonView(View):
    def __init__(self):
        super().__init__(timeout=None)  # 무제한 버튼 유지

    @discord.ui.button(label="✅ 출석 체크", style=discord.ButtonStyle.green, custom_id="persistent_checkin")
    async def checkin_button(self, interaction: Interaction, button: Button):
        user_id = str(interaction.user.id)
        now = datetime.datetime.now()
        today_str = now.strftime("%Y-%m-%d")

        checkin_data = load_checkin_data()
        user_info = checkin_data.get(user_id, {"last_date": None, "streak_level": 0})

        if user_info["last_date"] == today_str:
            await interaction.response.send_message("⛔ 오늘은 이미 출석했어요!", ephemeral=True)
            return

        # 50% 확률로 레벨 업
        leveled_up = False
        if random.random() < 0.5:  # 50% 확률
            user_info["streak_level"] += 1
            leveled_up = True

        level = user_info["streak_level"]
        reward = 1.2 ** level
        money_data[user_id] = money_data.get(user_id, 0) + reward
        save_money_data(money_data)

        user_info["last_date"] = today_str
        checkin_data[user_id] = user_info
        save_checkin_data(checkin_data)

        embed = discord.Embed(
            title="📅 출석 체크 완료!",
            description=f"{interaction.user.mention}님이 출석하셨습니다!",
            color=discord.Color.green()
        )
        embed.add_field(name="📈 현재 출석 레벨", value=f"Lv. {level}", inline=True)
        embed.add_field(name="💰 지급 보상", value=f"{reward:.2f} byte", inline=True)
        if leveled_up:
            embed.set_footer(text="🎉 출석 레벨이 상승했습니다!")
        else:
            embed.set_footer(text="📌 출석 레벨 상승에 실패했습니다.")

        await interaction.response.send_message(embed=embed, ephemeral=True)

@client.command(aliases=["출석설정"])
@commands.has_permissions(administrator=True)  # 관리자 권한 제한
async def set_attendance_channel(ctx, channel_id: int):
    await ctx.message.delete()
    guild_id = str(ctx.guild.id)
    attendance_channels[guild_id] = str(channel_id)
    save_attendance_channels(attendance_channels)
    await ctx.send(f"✅ 출석 채널이 <#{channel_id}>로 설정되었습니다.")

@set_attendance_channel.error
async def set_attendance_channel_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ 이 명령어는 관리자만 사용할 수 있어요!")
    else:
        await ctx.send("⚠️ 알 수 없는 오류가 발생했어요.")

@client.command(aliases=["토큰구매", "토큰교환"])
async def buy_token(ctx, amount: int = 1):
    await ctx.message.delete()
    user_id = str(ctx.author.id)
    user_name = ctx.author.display_name

    if amount <= 0:
        await ctx.send("❌ 1 이상의 수량을 입력해주세요.")
        return

    user_tokens = token_data.get(user_id, {"tokens": 0, "price": 100})
    price = user_tokens["price"]
    total_cost = sum([price * (2 ** i) for i in range(amount)])

    if money_data.get(user_id, 0) < total_cost:
        shortfall = total_cost - money_data.get(user_id, 0)
        await ctx.send(f"❌ 잔액이 부족합니다. 부족한 금액: **{shortfall:.2f} byte**")
        return

    # 확인 임베드 및 버튼
    embed = discord.Embed(
        title="🎫 토큰 구매 확인",
        description=f"{ctx.author.mention}님, 아래 내용을 확인해주세요.",
        color=discord.Color.teal()
    )
    embed.add_field(name="구매 수량", value=f"{amount} 개", inline=True)
    embed.add_field(name="총 가격", value=f"{total_cost} byte", inline=True)
    embed.set_footer(text="※ 토큰 가격은 구매 시마다 2배로 증가합니다.")

    view = View()

    async def confirm_callback(interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("이 버튼은 당신의 것이 아니에요!", ephemeral=True)
            return

        # 결제 및 토큰 증가
        money_data[user_id] -= total_cost
        user_tokens["tokens"] += amount
        user_tokens["price"] *= (2 ** amount)

        token_data[user_id] = user_tokens
        save_money_data(money_data)
        save_token_data(token_data)

        result = discord.Embed(
            title="✅ 토큰 구매 완료",
            description=f"{amount}개의 토큰을 구매하였습니다!",
            color=discord.Color.green()
        )
        result.add_field(name="보유 토큰", value=f"{user_tokens['tokens']} 개", inline=True)
        result.add_field(name="소모한 금액", value=f"{total_cost} byte", inline=True)
        result.add_field(name="다음 구매 가격", value=f"{user_tokens['price']} byte", inline=True)

        await interaction.response.edit_message(embed=result, view=None)

    async def cancel_callback(interaction):
        await interaction.response.edit_message(
            embed=discord.Embed(title="❌ 구매 취소", description="구매가 취소되었습니다.", color=discord.Color.red()),
            view=None
        )

    button_yes = Button(label="확인", style=ButtonStyle.green)
    button_no = Button(label="취소", style=ButtonStyle.red)
    button_yes.callback = confirm_callback
    button_no.callback = cancel_callback

    view.add_item(button_yes)
    view.add_item(button_no)

    await ctx.send(embed=embed, view=view)

@client.command(aliases=["토큰확인", "토큰"])
async def check_token(ctx, member: discord.Member = None):
    await ctx.message.delete()
    member = member or ctx.author
    user_id = str(member.id)
    data = token_data.get(user_id, {"tokens": 0, "price": 100})

    embed = discord.Embed(
        title="🎫 토큰 현황",
        description=f"{member.display_name}님의 토큰 정보입니다.",
        color=discord.Color.purple()
    )
    embed.add_field(name="보유 토큰", value=f"{data['tokens']} 개", inline=True)
    embed.add_field(name="다음 구매 가격", value=f"{data['price']} byte", inline=True)

    await ctx.send(embed=embed)

@client.command(aliases=["토큰최대교환"])
async def buy_token_max(ctx):
    await ctx.message.delete()
    user_id = str(ctx.author.id)
    user_name = ctx.author.display_name

    current_money = money_data.get(user_id, 0)
    user_tokens = token_data.get(user_id, {"tokens": 0, "price": 100})

    price = user_tokens["price"]
    total_cost = 0
    max_tokens = 0

    # 보유 머니로 교환 가능한 최대 수량 계산
    while total_cost + price <= current_money:
        total_cost += price
        price *= 2
        max_tokens += 1

    if max_tokens == 0:
        await ctx.send(f"{ctx.author.mention} ❌ 보유 금액으로는 토큰을 구매할 수 없습니다.")
        return

    embed = discord.Embed(
        title="💸 최대 토큰 교환 확인",
        description=f"{ctx.author.mention}님이 보유한 금액으로 교환 가능한 최대 토큰 수는 다음과 같습니다.",
        color=discord.Color.blue()
    )
    embed.add_field(name="최대 교환 수량", value=f"{max_tokens} 개", inline=True)
    embed.add_field(name="총 필요 금액", value=f"{total_cost:.2f} byte", inline=True)
    embed.set_footer(text="※ 확인을 누르면 바로 교환이 진행됩니다.")

    view = View()

    async def confirm_callback(interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("이 버튼은 당신의 것이 아닙니다!", ephemeral=True)
            return

        # 교환 처리
        money_data[user_id] -= total_cost
        user_tokens["tokens"] += max_tokens
        user_tokens["price"] *= (2 ** max_tokens)

        token_data[user_id] = user_tokens
        save_money_data(money_data)
        save_token_data(token_data)

        result = discord.Embed(
            title="✅ 최대 토큰 교환 완료",
            description=f"{max_tokens}개의 토큰을 교환했습니다!",
            color=discord.Color.green()
        )
        result.add_field(name="남은 금액", value=f"{money_data[user_id]:.2f} byte", inline=True)
        result.add_field(name="보유 토큰", value=f"{user_tokens['tokens']} 개", inline=True)
        result.add_field(name="소모한 금액", value=f"{total_cost} byte", inline=True)
        result.add_field(name="다음 가격", value=f"{user_tokens['price']} byte", inline=True)

        await interaction.response.edit_message(embed=result, view=None)

    async def cancel_callback(interaction):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="❌ 교환 취소",
                description="최대 교환이 취소되었습니다.",
                color=discord.Color.red()
            ),
            view=None
        )

    button_yes = Button(label="확인", style=discord.ButtonStyle.green)
    button_no = Button(label="취소", style=discord.ButtonStyle.red)
    button_yes.callback = confirm_callback
    button_no.callback = cancel_callback
    view.add_item(button_yes)
    view.add_item(button_no)

    await ctx.send(embed=embed, view=view)

@client.command(aliases=["토큰추가"])
@commands.has_permissions(administrator=True)
async def add_token(ctx, member: discord.Member, amount: int):
    await ctx.message.delete()
    if amount <= 0:
        await ctx.send("❌ 1 이상의 수량을 입력해주세요.")
        return

    user_id = str(member.id)
    user_data = token_data.get(user_id, {"tokens": 0, "price": 100})

    embed = discord.Embed(
        title="🟢 토큰 추가 확인",
        description=(
            f"{member.mention}님에게 **{amount}개**의 토큰을 추가하려고 합니다.\n"
            f"확인을 누르면 즉시 적용됩니다."
        ),
        color=discord.Color.teal()
    )

    view = View()

    async def confirm_callback(interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("이 버튼은 당신의 명령이 아닙니다!", ephemeral=True)
            return

        user_data["tokens"] += amount
        token_data[user_id] = user_data
        save_token_data(token_data)

        result = discord.Embed(
            title="✅ 토큰 추가 완료",
            description=f"{member.display_name}님에게 **{amount}개**의 토큰을 지급했습니다.",
            color=discord.Color.green()
        )
        result.add_field(name="총 보유 토큰", value=f"{user_data['tokens']} 개", inline=False)
        await interaction.response.edit_message(embed=result, view=None)

    async def cancel_callback(interaction):
        await interaction.response.edit_message(
            embed=discord.Embed(title="❌ 작업 취소", description="토큰 추가가 취소되었습니다.", color=discord.Color.red()),
            view=None
        )

    button_yes = Button(label="확인", style=discord.ButtonStyle.green)
    button_no = Button(label="취소", style=discord.ButtonStyle.red)
    button_yes.callback = confirm_callback
    button_no.callback = cancel_callback
    view.add_item(button_yes)
    view.add_item(button_no)

    await ctx.send(embed=embed, view=view)

@client.command(aliases=["토큰제거"])
@commands.has_permissions(administrator=True)
async def remove_token(ctx, member: discord.Member, amount: int):
    await ctx.message.delete()
    if amount <= 0:
        await ctx.send("❌ 1 이상의 수량을 입력해주세요.")
        return

    user_id = str(member.id)
    user_data = token_data.get(user_id, {"tokens": 0, "price": 100})

    if user_data["tokens"] < amount:
        await ctx.send("❌ 해당 유저의 토큰 수가 부족합니다.")
        return

    embed = discord.Embed(
        title="🔴 토큰 제거 확인",
        description=(
            f"{member.mention}님에게서 **{amount}개**의 토큰을 제거하려고 합니다.\n"
            f"확인을 누르면 즉시 적용됩니다."
        ),
        color=discord.Color.orange()
    )

    view = View()

    async def confirm_callback(interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("이 버튼은 당신의 명령이 아닙니다!", ephemeral=True)
            return

        user_data["tokens"] -= amount
        token_data[user_id] = user_data
        save_token_data(token_data)

        result = discord.Embed(
            title="🗑️ 토큰 제거 완료",
            description=f"{member.display_name}님에게서 **{amount}개**의 토큰을 제거했습니다.",
            color=discord.Color.red()
        )
        result.add_field(name="남은 토큰", value=f"{user_data['tokens']} 개", inline=False)
        await interaction.response.edit_message(embed=result, view=None)

    async def cancel_callback(interaction):
        await interaction.response.edit_message(
            embed=discord.Embed(title="❌ 작업 취소", description="토큰 제거가 취소되었습니다.", color=discord.Color.red()),
            view=None
        )

    button_yes = Button(label="확인", style=discord.ButtonStyle.green)
    button_no = Button(label="취소", style=discord.ButtonStyle.red)
    button_yes.callback = confirm_callback
    button_no.callback = cancel_callback
    view.add_item(button_yes)
    view.add_item(button_no)

    await ctx.send(embed=embed, view=view)

@client.command(aliases=["토큰구매가"])
@commands.has_permissions(administrator=True)
async def set_token_price(ctx, member: discord.Member, new_price: int = 100):
    await ctx.message.delete()

    if new_price <= 0:
        await ctx.send("❌ 가격은 1 이상이어야 합니다.")
        return

    user_id = str(member.id)
    user_data = token_data.get(user_id, {"tokens": 0, "price": 100})
    old_price = user_data["price"]

    embed = discord.Embed(
        title="⚙️ 토큰 구매가 설정 확인",
        description=(
            f"{member.mention}님의 토큰 **구매가를 {old_price} → {new_price}** byte로 변경하려고 합니다.\n"
            f"확인을 누르면 즉시 적용됩니다."
        ),
        color=discord.Color.blurple()
    )

    view = View()

    async def confirm_callback(interaction):
        if interaction.user != ctx.author:
            await interaction.response.send_message("이 버튼은 당신의 명령이 아닙니다!", ephemeral=True)
            return

        user_data["price"] = new_price
        token_data[user_id] = user_data
        save_token_data(token_data)

        result = discord.Embed(
            title="✅ 토큰 구매가 설정 완료",
            description=(
                f"{member.display_name}님의 토큰 구매가를 **{new_price} byte**로 설정했습니다."
            ),
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=result, view=None)

    async def cancel_callback(interaction):
        await interaction.response.edit_message(
            embed=discord.Embed(title="❌ 작업 취소", description="구매가 설정이 취소되었습니다.", color=discord.Color.red()),
            view=None
        )

    button_yes = Button(label="확인", style=discord.ButtonStyle.green)
    button_no = Button(label="취소", style=discord.ButtonStyle.red)
    button_yes.callback = confirm_callback
    button_no.callback = cancel_callback
    view.add_item(button_yes)
    view.add_item(button_no)

    await ctx.send(embed=embed, view=view)

@client.command(aliases=["건의"])
async def suggestion(ctx, *, content: str = None):
    await ctx.message.delete()
    user_id = str(ctx.author.id)
    now = datetime.datetime.now()

    suggestion_data = load_suggestions()  # 항상 최신 상태 유지

    if not content:
        await ctx.send("❌ 건의 내용을 입력해주세요.\n예: `%건의 강화 시스템 개선해주세요`")
        return

    user_record = suggestion_data.get(user_id, {})
    last_time_str = user_record.get("last_time")

    if last_time_str:
        try:
            last_time = datetime.datetime.fromisoformat(last_time_str)
            diff = (now - last_time).total_seconds()
            if diff < SUGGESTION_COOLDOWN:
                remain = int(SUGGESTION_COOLDOWN - diff)
                minutes, seconds = divmod(remain, 60)
                await ctx.send(f"⏳ 아직 건의를 할 수 없어요! 다시 시도하려면 **{minutes}분 {seconds}초** 후에 가능해요.")
                return
        except Exception as e:
            print(f"[건의 쿨타임 파싱 오류] {e}")

    # 건의 저장
    user_record["last_time"] = now.isoformat()
    user_record.setdefault("logs", []).append({
        "time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "content": content
    })
    suggestion_data[user_id] = user_record
    save_suggestions(suggestion_data)

    embed = discord.Embed(
        title="📮 건의 접수 완료",
        description=f"{ctx.author.mention}님의 건의가 접수되었습니다!\n```{content}```",
        color=discord.Color.blurple()
    )
    embed.set_footer(text="관리자가 확인할 수 있도록 저장되었습니다.")
    await ctx.send(embed=embed)

@client.command(aliases=["건의목록"])
async def suggestion_list(ctx):
    if not isinstance(ctx.channel, discord.DMChannel):
        return  # ❌ DM에서만 허용

    user_id = str(ctx.author.id)
    allowed_ids = load_suggestion_admins()

    if user_id not in allowed_ids:
        await ctx.send("❌ 이 명령어를 사용할 수 있는 권한이 없습니다.")
        return

    suggestion_data = load_suggestions()
    all_logs = []

    for uid, data in suggestion_data.items():
        for entry in data.get("logs", []):
            all_logs.append((uid, entry["time"], entry["content"]))

    if not all_logs:
        await ctx.send("📭 현재 등록된 건의가 없습니다.")
        return

    embed = discord.Embed(
        title="📮 전체 건의사항 목록",
        description="`%건의제거 <번호>`로 개별 삭제 가능",
        color=discord.Color.blurple()
    )

    for idx, (uid, time_str, content) in enumerate(all_logs, start=1):
        try:
            user = await client.fetch_user(int(uid))
            username = f"{user.name}#{user.discriminator}"
        except:
            username = f"Unknown ({uid})"

        embed.add_field(
            name=f"{idx}. ({username}) {time_str}",
            value=content,
            inline=False
        )

    await ctx.send(embed=embed)

@client.command(aliases=["건의제거"])
async def remove_suggestion(ctx, number: int = None):
    if not isinstance(ctx.channel, discord.DMChannel):
        return  # ❌ DM에서만 허용

    user_id = str(ctx.author.id)
    allowed_ids = load_suggestion_admins()

    if user_id not in allowed_ids:
        await ctx.send("❌ 이 명령어를 사용할 수 있는 권한이 없습니다.")
        return

    if number is None:
        await ctx.send("❗ 삭제할 건의 번호를 입력해주세요.\n예: `%건의제거 2`")
        return

    suggestion_data = load_suggestions()
    all_logs = []

    for uid, data in suggestion_data.items():
        for log in data.get("logs", []):
            all_logs.append((uid, log))

    if number <= 0 or number > len(all_logs):
        await ctx.send("❌ 올바른 건의 번호를 입력해주세요.")
        return

    # 삭제할 항목
    del_uid, del_entry = all_logs[number - 1]
    logs = suggestion_data[del_uid]["logs"]
    suggestion_data[del_uid]["logs"] = [l for l in logs if l != del_entry]

    save_suggestions(suggestion_data)

    embed = discord.Embed(
        title="🗑️ 건의 삭제 완료",
        description=f"{number}번 건의가 삭제되었습니다.",
        color=discord.Color.red()
    )
    embed.add_field(name="삭제된 건의 내용", value=del_entry["content"], inline=False)
    embed.set_footer(text=f"작성자 ID: {del_uid}, 시간: {del_entry['time']}")

    await ctx.send(embed=embed)

@client.command(aliases=["청소"])
@commands.has_permissions(administrator=True)
async def clean(ctx, amount: int):
    for i in range(amount):
        await ctx.message.delete()

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

rps_streaks = {}
rps_cooldowns = {}


class RPSView(discord.ui.View):
    def __init__(self, player_id: int):
        super().__init__(timeout=600)

        self.player_id = player_id
        self.streak = 0
        self.pending_reward = 0
        self.finished = False
        self.played = False
        self.waiting_for_choice = True

        # 처음에는 가위바위보 버튼만 사용 가능
        self.continue_game.disabled = True
        self.cash_out.disabled = True

    async def interaction_check(
        self,
        interaction: discord.Interaction
    ) -> bool:
        # 다른 유저의 버튼 클릭 차단
        if interaction.user.id != self.player_id:
            await interaction.response.send_message(
                "❌ 다른 사람의 가위바위보 게임입니다! "
                "본인이 시작한 게임의 버튼만 누를 수 있습니다.",
                ephemeral=True
            )
            return False

        # 종료된 게임의 버튼 클릭 차단
        if self.finished:
            await interaction.response.send_message(
                "이미 종료된 게임입니다.",
                ephemeral=True
            )
            return False

        return True

    def make_embed(
        self,
        title: str,
        description: str,
        color=discord.Color.blurple()
    ):
        embed = discord.Embed(
            title=title,
            description=description,
            color=color
        )

        embed.add_field(
            name="🔥 현재 연승",
            value=f"**{self.streak}연승**",
            inline=True
        )

        embed.add_field(
            name="💰 누적 보상",
            value=f"**{self.pending_reward:,} Byte**",
            inline=True
        )

        next_reward = 1000 * math.factorial(self.streak + 1)

        embed.add_field(
            name="🎁 다음 승리 보상",
            value=f"**+{next_reward:,} Byte**",
            inline=False
        )

        embed.set_footer(
            text="그만하고 수령을 누르면 누적 보상을 받을 수 있습니다."
        )

        return embed

    async def play(
        self,
        interaction: discord.Interaction,
        choice: str
    ):
        if not self.waiting_for_choice:
            await interaction.response.send_message(
                "먼저 계속하기 버튼을 눌러 다음 판을 시작해 주세요.",
                ephemeral=True
            )
            return

        user_id = str(self.player_id)
        now = time.time()

        # 첫 판 시작 시에만 쿨타임 검사
        if not self.played:
            last_play = rps_cooldowns.get(user_id, 0)
            remaining = 60 - (now - last_play)

            if remaining > 0:
                await interaction.response.send_message(
                    f"⏳ 쿨타임이 **{math.ceil(remaining)}초** 남았습니다.",
                    ephemeral=True
                )
                return

            rps_cooldowns[user_id] = now
            self.played = True

        # 선택 중복 방지
        self.waiting_for_choice = False

        # 이번 판의 선택 버튼 비활성화
        self.scissors.disabled = True
        self.rock.disabled = True
        self.paper.disabled = True

        bot_choice = random.choice(["가위", "바위", "보"])

        embed = discord.Embed(
            title="✊ 가위바위보 결과",
            description=(
                f"👤 **내 선택:** {choice}\n"
                f"🤖 **봇 선택:** {bot_choice}"
            ),
            color=discord.Color.blurple()
        )

        # 무승부: 연승과 누적 보상 유지
        if choice == bot_choice:
            embed.color = discord.Color.gold()

            embed.add_field(
                name="🤝 무승부!",
                value="연승과 누적 보상이 유지됩니다.",
                inline=False
            )

        # 승리
        elif (
            (choice == "가위" and bot_choice == "보")
            or (choice == "바위" and bot_choice == "가위")
            or (choice == "보" and bot_choice == "바위")
        ):
            self.streak += 1

            reward = 1000 * math.factorial(self.streak)
            self.pending_reward += reward

            embed.color = discord.Color.green()

            embed.add_field(
                name="🎉 승리!",
                value=(
                    f"이번 승리 보상: **{reward:,} Byte**\n"
                    f"누적 보상: **{self.pending_reward:,} Byte**"
                ),
                inline=False
            )

        # 패배: 연승과 누적 보상 초기화
        else:
            self.streak = 0
            self.pending_reward = 0
            self.finished = True

            rps_streaks[user_id] = 0

            for button in self.children:
                button.disabled = True

            embed.color = discord.Color.red()

            embed.add_field(
                name="💀 패배!",
                value="연승이 초기화되었고 누적 보상을 잃었습니다.",
                inline=False
            )

            embed.set_footer(text="게임 종료")

            await interaction.response.edit_message(
                embed=embed,
                view=self
            )
            return

        rps_streaks[user_id] = self.streak

        # 결과가 나온 뒤에만 계속하기/수령 버튼 활성화
        self.continue_game.disabled = False
        self.cash_out.disabled = self.pending_reward <= 0

        embed.add_field(
            name="❓ 계속하시겠습니까?\n",
            value=(
                "🎲 **계속하기:** 다음 판에 도전합니다.\n"
                "💰 **그만하고 수령:** 누적 보상을 받습니다."
            ),
            inline=False
        )

        await interaction.response.edit_message(
            embed=embed,
            view=self
        )

    # ==============================
    # 가위바위보 선택 버튼
    # ==============================

    @discord.ui.button(
        label="가위",
        emoji="✌️",
        style=discord.ButtonStyle.primary,
        row=0
    )
    async def scissors(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await self.play(interaction, "가위")

    @discord.ui.button(
        label="바위",
        emoji="✊",
        style=discord.ButtonStyle.primary,
        row=0
    )
    async def rock(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await self.play(interaction, "바위")

    @discord.ui.button(
        label="보",
        emoji="✋",
        style=discord.ButtonStyle.primary,
        row=0
    )
    async def paper(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await self.play(interaction, "보")

    # ==============================
    # 다음 판 진행 버튼
    # ==============================

    @discord.ui.button(
        label="계속하기",
        emoji="🎲",
        style=discord.ButtonStyle.success,
        row=1
    )
    async def continue_game(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not self.played:
            await interaction.response.send_message(
                "먼저 가위바위보를 진행해 주세요.",
                ephemeral=True
            )
            return

        if self.waiting_for_choice:
            await interaction.response.send_message(
                "이미 다음 판을 진행할 수 있는 상태입니다.",
                ephemeral=True
            )
            return

        self.waiting_for_choice = True

        # 다음 판을 위해 선택 버튼 활성화
        self.scissors.disabled = False
        self.rock.disabled = False
        self.paper.disabled = False

        self.continue_game.disabled = True
        self.cash_out.disabled = True

        embed = self.make_embed(
            "✊ 다음 판!",
            "가위·바위·보 중 하나를 선택하세요."
        )

        await interaction.response.edit_message(
            embed=embed,
            view=self
        )

    # ==============================
    # 누적 보상 수령 버튼
    # ==============================

    @discord.ui.button(
        label="그만하고 수령",
        emoji="💰",
        style=discord.ButtonStyle.danger,
        row=1
    )
    async def cash_out(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        user_id = str(self.player_id)

        if self.pending_reward <= 0:
            await interaction.response.send_message(
                "수령할 보상이 없습니다.",
                ephemeral=True
            )
            return

        reward = self.pending_reward

        # 보상 지급 및 저장
        money_data[user_id] = money_data.get(user_id, 0) + reward
        save_money_data(money_data)

        self.finished = True

        for button in self.children:
            button.disabled = True

        embed = discord.Embed(
            title="💰 보상 수령 완료!",
            description=(
                f"수령 보상: **+{reward:,} Byte**\n"
                f"현재 잔액: **{money_data[user_id]:,} Byte**\n"
                f"최종 연승: **{self.streak}연승**"
            ),
            color=discord.Color.green()
        )

        embed.set_footer(text="가위바위보 게임 종료")

        await interaction.response.edit_message(
            embed=embed,
            view=self
        )

    # ==============================
    # 시간 초과 처리
    # ==============================

    async def on_timeout(self):
        if self.finished:
            return

        self.finished = True

        for button in self.children:
            button.disabled = True

        # 시간 초과 시 미수령 보상은 지급하지 않음
        try:
            if hasattr(self, "message") and self.message:
                await self.message.edit(view=self)
        except discord.HTTPException:
            pass


# ==============================
# 가위바위보 명령어
# ==============================

@client.command(aliases=["가위바위보", "가위바위보게임", "ㄱㅇㅂㅇㅂ", "짱깨뽀"])
async def rps(ctx):
    user_id = str(ctx.author.id)

    # 새 게임 시작 쿨타임 확인
    remaining = 60 - (
        time.time() - rps_cooldowns.get(user_id, 0)
    )

    if remaining > 0:
        await ctx.send(
            f"⏳ 가위바위보 쿨타임이 **{math.ceil(remaining)}초** 남았습니다."
        )
        return

    view = RPSView(ctx.author.id)

    embed = discord.Embed(
        title="✊ 가위바위보",
        description=(
            "아래 버튼을 눌러 봇과 대결하세요!\n\n"
            "✌️ **가위** · ✊ **바위** · ✋ **보**\n\n"
        ),
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="🔥 현재 연승",
        value="**0연승**",
        inline=True
    )

    embed.add_field(
        name="💰 누적 보상",
        value="**0 Byte**",
        inline=True
    )

    embed.set_footer(
        text=f"{ctx.author.display_name}의 가위바위보"
    )

    view.message = await ctx.send(
        embed=embed,
        view=view
    )

client.run(os.getenv("DISCORD_TOKEN"))