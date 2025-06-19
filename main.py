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

# 한글 폰트 설정 (Windows 기준: 'Malgun Gothic')
plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False  # 마이너스 기호 깨짐 방지

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
async def time(ctx):
    await ctx.message.delete()
    now = datetime.datetime.now()
    current_time = now.strftime("%Y년 %m월 %d일 %H시 %M분 %S초")
    embed = discord.Embed(title="현재 시간 ⏰", description=f"{current_time}", color=0x3498db)
    await ctx.send(embed=embed)

@client.command(aliases=['패치노트'])
async def patchnote(ctx):
    await ctx.message.delete()
    embed = discord.Embed(
        title="📜 패치노트 v1.1.7",
        description="최신 버전 업데이트입니다.",
        color=0xf1c40f  # 노란색
    )
    embed.add_field(name="✨ 새로운 기능", value="- 도박 명령어 개선\n- 경고 명령어 비활성화", inline=False)
    embed.add_field(name="🔮 예정 사항", value="- 버튼출석\n- 봇 24시간 가동\n- 상점 명령어 구현", inline=False)
    embed.set_footer(text="업데이트: 2025-06-19")
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

@client.command(aliases=['강화'])
async def enhance(ctx, item_name: str = None, sacrifice: str = None):
    if item_name is None:
        await ctx.send("아이템 이름을 입력해주세요! 예: `%강화 칼` 처럼 입력하면 돼요.")
        return

    user_id = str(ctx.author.id)
    now = datetime.datetime.now()

    if user_id in cooldowns:
        diff = (now - cooldowns[user_id]).total_seconds()
        if diff < 10:
            await ctx.send(f"아직 쿨타임이에요! {int(10 - diff)}초만 기다려주세요.")
            return
    cooldowns[user_id] = now

    user_items = enhance_data.get(user_id, {})
    current_level = user_items.get(item_name, 0)

    # 제물 적용
    sacrifice_level = 0
    if sacrifice:
        if sacrifice == item_name:
            await ctx.send("⚠️ 강화하려는 아이템을 제물로 사용할 수 없어요!")
            return
        sacrifice_level = user_items.get(sacrifice, 0)
        # 제물 삭제
        user_items.pop(sacrifice, None)

    levels_gained = 0
    log_lines = []

    while True:
        base_success_rate = 100 * math.exp(-0.01 * current_level)
        base_success_rate = max(min(base_success_rate, 100), 0)

        # 곱연산 적용
        final_success_rate = base_success_rate * (1 + (sacrifice_level / 100))
        final_success_rate = min(final_success_rate, 100)  # 최대 100% 제한

        roll = uniform(0.0, 100.0)
        success = roll <= final_success_rate
        log_lines.append(f"+{current_level}: 기본 {base_success_rate:.3f}% + 제물 {base_success_rate * (sacrifice_level / 100):.3f}% = 최종 {final_success_rate:.3f}% → {'성공' if success else '실패'}")

        if success:
            current_level += 1
            levels_gained += 1
        else:
            break

    user_items[item_name] = current_level
    enhance_data[user_id] = user_items
    save_data(enhance_data)

    embed = discord.Embed(title="🔧 아이템 강화 결과 🔧", color=0x3498db)
    embed.add_field(name="아이템", value=item_name, inline=False)
    embed.add_field(name="최종 강화 레벨", value=f"+{current_level}", inline=False)
    embed.add_field(name="성공 횟수", value=f"{levels_gained}번 강화 성공!", inline=False)
    # embed.add_field(name="강화 과정 로그", value="\n".join(log_lines), inline=False)
    if sacrifice:
        embed.add_field(name="제물", value=f"{sacrifice} (+{sacrifice_level})", inline=False)

    await ctx.send(embed=embed)

    chunk_size = 20  # 한 메시지에 보낼 로그 줄 수 (적당히 조절 가능)

    for i in range(0, len(log_lines), chunk_size):
        chunk = log_lines[i:i+chunk_size]
        await ctx.send("```" + "\n".join(chunk) + "```")

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
@client.command(aliases=['머니확인'])
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
        money_data[user_id] = money_data.get(user_id, 0) + amount
        save_money_data(money_data)
        embed = Embed(
            description=f"✅ **{member.display_name}** 님에게 **{amount} byte**를 추가했습니다.",
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

    view = View()

    async def confirm_callback(interaction: Interaction):
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

@client.command(aliases=['상점'])
async def shop(ctx):
    await ctx.message.delete()

    embed = discord.Embed(
        title="🛒 상점 목록",
        description="버튼을 눌러 아이템을 구매하세요!",
        color=0x00bfff
    )
    embed.add_field(name="파산신청", value="마이너스 통장을 0원으로!\n💰 가격: 10000 byte", inline=False)
    embed.add_field(name="상하차", value="상승장 / 하락장 시간 확인\n💰 가격: 2500 byte", inline=False)
    embed.add_field(name="주식과열", value="📈 10분간 초상승장 + 20분간 주식부도\n💰 가격: 100000 byte", inline=False)
    embed.set_footer(text="※ 아이템은 향후 업데이트될 수 있습니다.")

    view = ShopView(ctx.author.id)
    await ctx.send(embed=embed, view=view)

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
        await ctx.send(f"{ctx.author.mention} | ❌ `{item_name}` 아이템이 없습니다.")
        return

    level = enhance_data[user_id][item_name]

    # 공식 분기
    if level <= 100:
        earned = calc_byte_log2(level)
    else:
        earned = calc_byte_log10(level)

    # 최소 0원 보장
    earned = max(0, earned)

    # 머니 업데이트
    money_data[user_id] = money_data.get(user_id, 0) + earned
    save_money_data(money_data)

    # 아이템 삭제
    del enhance_data[user_id][item_name]
    save_data(enhance_data)

    # 임베디드 출력
    embed = discord.Embed(
        title="💰 강화 아이템 판매",
        description=f"{ctx.author.mention}님이 `{item_name} +{level}`을 판매하였습니다!",
        color=0x00ccff
    )
    embed.add_field(name="획득 Byte", value=f"**{earned} byte**", inline=False)
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
    "JAVA":   {"base": 50,  "limit": 0.075},
    "C":      {"base": 30,  "limit": 0.033},
    "C++":    {"base": 80,  "limit": 0.08},
    "C#":     {"base": 100, "limit": 0.025},
    "PYTHON": {"base": 10,  "limit": 0.1},
    "HTML":   {"base": 40,  "limit": 0.04},
    "JS":     {"base": 300, "limit": 0.0142857},
    "TS":     {"base": 100, "limit": 0.3}
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
        bias = (base - prev_price) / base * 0.01
        change += bias

        new_price = prev_price * (1 + change)

        # ✅ 상승장 / 하락장 / 초상승장 / 주식부도 효과 (곱연산)
        if effective_state == "BULL":
            new_price *= (1 + random.uniform(0, 0.025))  # +0~2.5%
        elif effective_state == "BEAR":
            new_price *= (1 - random.uniform(0, 0.02))   # -0~2%
        elif effective_state == "HYPER_BULL":
            new_price *= (1 + random.uniform(0.05, 0.25))  # +5~25%
        elif effective_state == "CRASH":
            new_price *= (1 - random.uniform(0.03, 0.15))    # -3~15%

        # 상장폐지 처리
        if new_price <= base * 0.01:
            new_price = base
            print(f"[📉 상장폐지] {name} → 기본가로 초기화됨")

            for user_id, stocks in list(portfolio.items()):
                if name in stocks:
                    del stocks[name]
                    delisted_stocks.setdefault(user_id, []).append(name)

            save_delisted_stocks(delisted_stocks)

        stock_prices[name]["previous"] = prev_price
        stock_prices[name]["current"] = round(new_price, 2)

        # 가격 히스토리 저장
        price_history.setdefault(name, []).append(round(new_price, 2))
        if len(price_history[name]) > 1440:
            price_history[name] = price_history[name][-1440:]

    last_update_time = datetime.datetime.now(datetime.timezone.utc)
    save_json(stock_file, stock_prices)
    save_price_history(price_history)

    from git import Repo
    import os

    def git_commit_and_push():
        from git import Repo
        repo_dir = r"C:\Users\USER\Desktop\디코 봇\Mirim"
        repo = Repo(repo_dir)

        repo.git.add("price_history.json")
        repo.index.commit("🔄 Update price history")
        origin = repo.remote(name="origin")
        print("📦 pushing to GitHub...")
        origin.push()
        print("✅ push complete")

    git_commit_and_push()

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
    remain = max(0, 60 - int(elapsed))

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
        embed.set_footer(text=f"⏱️ 다음 갱신까지 {remain}초")

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
    last_update_time = datetime.datetime.now(datetime.timezone.utc)

    # ✅ 미림봇 접속 메시지 전송
    channel_id = 1352303919312801943
    channel = client.get_channel(channel_id)

    if channel:
        embed = discord.Embed(
            title="✅ 미림봇 접속",
            description="봇이 온라인 상태입니다.",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now()
        )
        embed.set_footer(text="MirimBot v1.1.7")
        await channel.send(embed=embed)
    else:
        print(f"⚠️ 채널 ID {channel_id}를 찾을 수 없습니다.")

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
    "TS": "TS"
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
    total_earned = round(price * amount * 0.8, 2)  # 수수료 20%

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

    if max_amount == 0:
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

@client.command(aliases=["도움말"])
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

# ✅ 명령어 함수
@client.command(aliases=["출금"])
async def moneyout(ctx, amount: float):
    user_id = str(ctx.author.id)
    amount = round(amount, 2)

    if money_data.get(user_id, 0) < amount:
        await ctx.send("❌ 보유 금액이 부족합니다.")
        return

    if amount < 1000:
        await ctx.send("❌ 최소 출금 금액은 1000입니다.")
        return

    try:
        result = math.log(amount - 998) ** 3
    except ValueError:
        await ctx.send("❌ 로그 계산 실패 (금액 너무 작음).")
        return

    result = round(result, 2)

    # ✅ 상호작용을 위한 임시 저장
    if not hasattr(client, "ctx_temp"):
        client.ctx_temp = {}
    client.ctx_temp[user_id] = {"amount": amount, "result": result}

    # ✅ 버튼 생성
    view = View(timeout=10)
    button_yes = Button(label="확인", style=discord.ButtonStyle.green)
    button_no = Button(label="취소", style=discord.ButtonStyle.red)

    button_yes.callback = confirm_callback
    button_no.callback = cancel_callback

    view.add_item(button_yes)
    view.add_item(button_no)

    embed = discord.Embed(
        title="💰 출금 확인",
        description=f"출금 요청 금액: {amount:.2f}\n예상 통장 적립: {result:.2f}\n\n정말 출금하시겠습니까?",
        color=discord.Color.gold()
    )
    embed.set_footer(text="10초 안에 선택하지 않으면 자동 취소됩니다.")

    await ctx.send(embed=embed, view=view)

@client.command(aliases=["통장"])
async def currentrealmoney(ctx, member: discord.Member = None):
    target = member or ctx.author
    user_id = str(target.id)
    balance = bank_data.get(user_id, 0)

    embed = discord.Embed(
        title="🏦 통장 잔액 확인",
        description=f"{target.mention}님의 현재 통장 잔액은 **{balance:.2f}** byte입니다.",
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"요청자: {ctx.author.display_name}")

    await ctx.send(embed=embed)

@client.command(aliases=["도박"])
async def gamble(ctx, amount: int):
    await ctx.message.delete()
    user_id = str(ctx.author.id)
    now = datetime.datetime.now()

    # 쿨타임 체크
    last_time = gamble_cooldowns.get(user_id)
    if last_time:
        elapsed = (now - last_time).total_seconds()
        if elapsed < 60:
            remain = int(60 - elapsed)
            minutes, seconds = divmod(remain, 60)
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

@client.command(aliases=["통장랭킹"])
async def bank_rank(ctx):
    await ctx.message.delete()
    if not bank_data:
        await ctx.send("❌ 데이터가 없습니다.")
        return

    sorted_users = sorted(bank_data.items(), key=lambda x: x[1], reverse=True)

    embed = discord.Embed(
        title="🏦 통장 랭킹 TOP 10",
        description="통장에 적립된 byte 기준 랭킹입니다.",
        color=discord.Color.blue()
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
        if elapsed < 60:
            remain = int(60 - elapsed)
            minutes, seconds = divmod(remain, 60)
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

class ShopView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=15)
        self.user_id = str(user_id)

    @discord.ui.button(label="💸 파산신청", style=discord.ButtonStyle.primary)
    async def buy_pasan(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != int(self.user_id):
            await interaction.response.send_message("이 버튼은 당신의 것이 아닙니다!", ephemeral=True)
            return

        current_money = money_data.get(self.user_id, 0)
        price = 10000

        if current_money < price:
            await interaction.response.send_message("💸 돈이 부족합니다.", ephemeral=True)
            return

        # 돈 차감
        money_data[self.user_id] = current_money - price
        save_money_data(money_data)

        # 아이템 추가
        user_items.setdefault(self.user_id, {})
        user_items[self.user_id]["파산신청"] = user_items[self.user_id].get("파산신청", 0) + 1
        save_items(user_items)

        await interaction.response.send_message("✅ 파산신청 아이템을 구매했습니다!", ephemeral=True)
        self.stop()

    @discord.ui.button(label="↕️ 상하차", style=discord.ButtonStyle.primary)
    async def buy_sanghacha(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != int(self.user_id):
            await interaction.response.send_message("이 버튼은 당신의 것이 아닙니다!", ephemeral=True)
            return

        current_money = money_data.get(self.user_id, 0)
        price = 2500

        if current_money < price:
            await interaction.response.send_message("💸 돈이 부족합니다.", ephemeral=True)
            return

        # 돈 차감
        money_data[self.user_id] = current_money - price
        save_money_data(money_data)

        # 아이템 추가
        user_items.setdefault(self.user_id, {})
        user_items[self.user_id]["️상하차"] = user_items[self.user_id].get("상하차", 0) + 1
        save_items(user_items)

        await interaction.response.send_message("✅ 상하차 아이템을 구매했습니다!", ephemeral=True)
        self.stop()

    @discord.ui.button(label="🧨 주식과열", style=discord.ButtonStyle.danger)
    async def buy_stockover(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != int(self.user_id):
            await interaction.response.send_message("❌ 이 버튼은 당신의 것이 아닙니다.", ephemeral=True)
            return

        uid = str(interaction.user.id)
        price = 100000
        balance = money_data.get(uid, 0)

        if balance < price:
            await interaction.response.send_message("💸 돈이 부족합니다.", ephemeral=True)
            return

        # 돈 차감
        money_data[uid] = balance - price
        save_money_data(money_data)

        # 아이템 추가
        user_items.setdefault(uid, {})
        user_items[uid]["주식과열"] = user_items[uid].get("주식과열", 0) + 1
        save_items(user_items)

        await interaction.response.send_message("✅ 주식과열 아이템을 구매했습니다!", ephemeral=True)
        self.stop()

@client.command(aliases=["가방"])
async def inventory(ctx, target: discord.Member = None):
    await ctx.message.delete()
    target = target or ctx.author
    uid = str(target.id)
    items = user_items.get(uid, {})

    embed = discord.Embed(
        title=f"🎒 {target.display_name}님의 가방",
        description="보유한 아이템 목록입니다.",
        color=0x95a5a6
    )

    if not items:
        embed.description = "아이템이 없습니다."
    else:
        for name, count in items.items():
            embed.add_field(name=name, value=f"{count}개", inline=False)

    await ctx.send(embed=embed)

@client.command(aliases=["사용"])
async def use_item(ctx, *, item_name: str):
    await ctx.message.delete()
    uid = str(ctx.author.id)
    item_name = item_name.strip()

    items = user_items.get(uid, {})
    if item_name not in items or items[item_name] <= 0:
        await ctx.send("❌ 해당 아이템을 보유하고 있지 않습니다.")
        return

    if item_name == "파산신청":
        current_money = money_data.get(uid, 0)
        if current_money >= 0:
            await ctx.send("❌ 잔액이 0 이하일 때만 사용할 수 있는 아이템입니다.")
            return

        money_data[uid] = 0
        save_money_data(money_data)
        await ctx.send("✅ 파산신청 아이템을 사용하여 잔액이 0으로 초기화되었습니다.")

    elif item_name == "상하차":
        # 상승장/하락장 상태와 남은 시간 가져오기
        state = "📈 상승장" if current_market == "BULL" else "📉 하락장"
        minutes, seconds = divmod(market_wait_seconds, 60)

        embed = discord.Embed(
            title="📊 현재 시장 상태",
            description=f"시장 상태: {state}\n남은 시간: {minutes}분 {seconds}초",
            color=discord.Color.teal()
        )
        await ctx.author.send(embed=embed)
        await ctx.send("📩 시장 정보를 DM으로 보냈습니다!")
    elif item_name == "주식과열":
        global override_state, override_end
        if override_state:
            await ctx.send("⚠️ 이미 시장이 특수 상태입니다.")
            return
        set_override_state("HYPER_BULL", 10 * 60)
        await ctx.send("🔥 '주식과열' 아이템을 사용했습니다! 10분간 초상승장이 시작됩니다.")
    else:
        await ctx.send("⚠️ 이 아이템은 아직 사용할 수 없습니다.")
        return

    # 아이템 차감
    items[item_name] -= 1
    if items[item_name] <= 0:
        del items[item_name]
    user_items[uid] = items
    save_items(user_items)

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
        bonus_amount = int(25 * math.sqrt(debt))

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


client.run(os.getenv("DISCORD_TOKEN"))