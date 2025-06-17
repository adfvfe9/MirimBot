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

DATA_FILE = 'warnings.json' # 경고 데이터를 저장할 파일
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

if os.path.exists(DATA_FILE): # warnings.json 파일이 존재하면 불러오기
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
        warnings = {int(k): v for k, v in data.get('warnings', {}).items()}
        warnings_data = {int(k): v for k, v in data.get('warnings_data', {}).items()}


def save_warnings(): # 경고 데이터를 JSON 파일에 저장하는 함수
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump({'warnings': warnings, 'warnings_data': warnings_data}, f, ensure_ascii=False, indent=4)

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
        title="📜 패치노트 v1.1.5",
        description="최신 버전 업데이트입니다.",
        color=0xf1c40f  # 노란색
    )
    embed.add_field(name="✨ 새로운 기능", value="- 주식 명령어 추가", inline=False)
    embed.add_field(name="🔮 예정 사항", value="- 버튼출석\n- 봇 24시간 가동\n- 상점 명령어 구현", inline=False)
    embed.set_footer(text="업데이트: 2025-06-17")
    await ctx.send(embed=embed)

class WarningView(ui.View): # 경고 확인을 위한 View 클래스
    def __init__(self, ctx, target, count, reason):
        super().__init__(timeout=10)
        self.ctx = ctx
        self.target = target
        self.count = count
        self.reason = reason

    @ui.button(label="확인 ✅", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("이 버튼은 당신을 위한 게 아니에요!", ephemeral=True)
            return

        current_warn = warnings.get(self.target.id, 0)
        new_warn = max(current_warn + self.count, 0)
        warnings[self.target.id] = new_warn

        # 여기서 warnings_data에 기록 추가
        if self.target.id not in warnings_data:
            warnings_data[self.target.id] = []

        warnings_data[self.target.id].append({
            'time': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'count': self.count,
            'giver': self.ctx.author.name,
            'reason': self.reason
        })

        save_warnings() # 경고 데이터를 파일에 저장

        embed = discord.Embed(
            title="경고 적용 완료",
            description=f"**경고 받는 사람:** {self.target.mention}\n"
                        f"**경고 주는 사람:** {self.ctx.author.mention}\n"
                        f"**경고 수:** {self.count}\n"
                        f"**사유:** {self.reason}",
            color=0x2ecc71  # 초록색
        )
        await interaction.response.edit_message(embed=embed, view=None, content=None)

        await asyncio.sleep(10)
        try:
            await interaction.message.delete()
        except:
            pass
        self.stop()

    @ui.button(label="취소 ❌", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("이 버튼은 당신을 위한 게 아니에요!", ephemeral=True)
            return

        embed = discord.Embed(
            title="경고 취소됨",
            description="경고가 취소되었습니다.",
            color=0xe74c3c  # 빨간색
        )
        await interaction.response.edit_message(embed=embed, view=None, content=None)

        await asyncio.sleep(10)
        try:
            await interaction.message.delete()
        except:
            pass
        self.stop()

@client.command(aliases=['경고'])
async def warning(ctx, target: discord.Member, count: int = 1, *, reason: str = "사유 없음"):
    await ctx.message.delete()
    if count == 0:
        await ctx.send("⚠️ 경고 수는 0일 수 없습니다.")
        return

    if count < 0 and reason == "사유 없음":
        reason = "경고 취소"

    embed = discord.Embed(
        title="경고 확인",
        description=f"{target.mention}님에게 경고를 적용하시겠습니까?",
        color=0x3498db  # 파란색
    )
    embed.add_field(name="경고 받는 사람", value=target.mention, inline=True)
    embed.add_field(name="경고 주는 사람", value=ctx.author.mention, inline=True)
    embed.add_field(name="경고 수", value=str(count), inline=True)
    embed.add_field(name="사유", value=reason, inline=False)

    view = WarningView(ctx, target, count, reason)
    await ctx.send(embed=embed, view=view)

class WarningPages(ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=60)  # 60초 뒤 뷰 비활성화
        self.user_id = user_id
        self.current_page = 0

    async def update_embed(self, interaction):
        entries = warnings_data.get(self.user_id, [])
        embed = discord.Embed(title="경고 내역", color=0x3498db)
        start = self.current_page * 3
        end = start + 3
        page_entries = entries[start:end]

        if not page_entries:
            embed.description = "경고 내역이 없습니다."
        else:
            for w in page_entries:
                time_str = w['time'].strftime("%Y-%m-%d %H:%M")
                embed.add_field(
                    name=f"경고 받은 시간: {time_str}",
                    value=f"수: {w['count']}, 준 사람: {w['giver']}, 사유: {w['reason']}",
                    inline=False
                )
            embed.set_footer(text=f"페이지 {self.current_page+1} / {(len(entries)-1)//3+1}")

        await interaction.response.edit_message(embed=embed, view=self)

    @ui.button(label="이전", style=discord.ButtonStyle.green)
    async def prev(self, interaction: discord.Interaction, button: ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await self.update_embed(interaction)

    @ui.button(label="다음", style=discord.ButtonStyle.green)
    async def next(self, interaction: discord.Interaction, button: ui.Button):
        if (self.current_page + 1) * 3 < len(warnings_data.get(self.user_id, [])):
            self.current_page += 1
            await self.update_embed(interaction)

@client.command(aliases=['경고확인'])
async def check_warning(ctx, *, username: str = None):
    await ctx.message.delete()
    if username:
        # 유저 이름으로 멤버 찾기
        member = discord.utils.find(
            lambda m: username.lower() in m.name.lower() or username.lower() in m.display_name.lower(),
            ctx.guild.members
        )
        if not member:
            await ctx.send("해당 유저를 찾을 수 없습니다.")
            return

        entries = warnings_data.get(member.id, [])
        if not entries:
            await ctx.send(f"{member.display_name}님은 경고 내역이 없습니다.")
            return

        view = WarningPages(member.id)
        embed = discord.Embed(title=f"{member.display_name}님의 경고 내역", color=0x3498db)
        # 첫 페이지 내용 세팅
        start = 0
        page_entries = entries[start:start+3]
        for w in page_entries:
            time_str = w['time']
            embed.add_field(
                name=f"경고 받은 시간: {time_str}",
                value=f"수: {w['count']}, 준 사람: {w['giver']}, 사유: {w['reason']}",
                inline=False
            )
        embed.set_footer(text=f"페이지 1 / {(len(entries)-1)//3+1}")

        await ctx.send(embed=embed, view=view)
    else:
        # 경고 1 이상인 모든 유저 리스트
        users = [(uid, sum(w['count'] for w in wl)) for uid, wl in warnings_data.items() if sum(w['count'] for w in wl) > 0]
        if not users:
            await ctx.send("경고를 받은 유저가 없습니다.")
            return
        # 경고 수 오름차순, 동점 시 이름 가나다순
        users.sort(key=lambda x: (
            x[1],
            (discord.utils.get(ctx.guild.members, id=x[0]).name if discord.utils.get(ctx.guild.members, id=x[0]) else "")
        ))

        embed = discord.Embed(title="경고 받은 유저 리스트", color=0x3498db)
        for uid, total_count in users:
            member = discord.utils.get(ctx.guild.members, id=uid)
            if member is None:
                name = f"알 수 없는 유저 ({uid})"
            else:
                name = member.display_name
            embed.add_field(name=name, value=f"경고 수: {total_count}", inline=True)
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
        money_data[user_id] = max(money_data.get(user_id, 0) - amount, 0)
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
        description="아래는 구매 가능한 아이템들입니다.",
        color=0x00bfff
    )
    embed.add_field(name="테스트1", value="가격: 100 byte", inline=False)
    embed.add_field(name="테스트2", value="가격: 150 byte", inline=False)
    embed.add_field(name="테스트3", value="가격: 75 byte", inline=False)
    embed.set_footer(text="※ 아이템은 향후 업데이트될 수 있습니다.")

    await ctx.send(embed=embed)

import math

# log2 공식
def calc_byte_log2(level):
    if level <= 0:
        return 0
    return int(0.1 * level * math.log2(level)) + 1

# log10 공식
def calc_byte_log10(level):
    if level <= 0:
        return 0
    return int(0.5 * level * math.log10(level)) + 1

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

# 주식 시장 상태를 저장하는 파일
def load_market_state():
    if os.path.exists(market_file):
        with open(market_file, "r") as f:
            data = json.load(f)
            return data.get("state", "BULL"), data.get("remaining_seconds", random.randint(300, 7200))
    return "BULL", random.randint(300, 7200)

def save_market_state(state, remaining_seconds):
    with open(market_file, "w") as f:
        json.dump({"state": state, "remaining_seconds": remaining_seconds}, f)

# ───────────── 주식 기본 정보 ─────────────
stock_info = {
    "JAVA":   {"base": 50,  "limit": 0.075},
    "C":      {"base": 30,  "limit": 0.033},
    "C++":    {"base": 80,  "limit": 0.08},
    "C#":     {"base": 100, "limit": 0.025},
    "PYTHON": {"base": 10,  "limit": 0.1},
    "HTML":   {"base": 40,  "limit": 0.04},
    "JS":     {"base": 300, "limit": 0.0142857}
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
    for name, info in stock_info.items():
        base = info["base"]
        limit = info["limit"]
        prev_price = stock_prices[name]["current"]

        # 기본 변동
        change = random.uniform(-limit, limit)

        # 변동에 따라 가격 조정
        bias = (base - prev_price) / base * 0.01
        change += bias

        new_price = prev_price * (1 + change)

        # 상승장 / 하락장 효과 (곱연산)
        if current_market == "BULL":
            new_price *= (1 + random.uniform(0, 0.025))  # 0~2.5% 상승
        elif current_market == "BEAR":
            new_price *= (1 - random.uniform(0, 0.025))  # 0~2.5% 하락

        # 상장폐지 조건
        if new_price <= base * 0.01:
            new_price = base
            print(f"[📉 상장폐지] {name} → 기본가로 초기화됨")

        stock_prices[name]["previous"] = prev_price
        stock_prices[name]["current"] = round(new_price, 2)
        # 가격 히스토리 저장
        price_history.setdefault(name, []).append(round(new_price, 2))
        if len(price_history[name]) > 1440:
            price_history[name] = price_history[name][-1440:]  # 24시간 (1분 간격 * 1440)


    last_update_time = datetime.datetime.now(datetime.timezone.utc)
    save_json(stock_file, stock_prices)
    save_price_history(price_history)

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
    embed.add_field(
    name="📊 현재 시장 상태",
    value=f"{'📈 상승장' if current_market == 'BULL' else '📉 하락장'}", inline=False) # \n⏱️ 다음 전환까지: {market_wait_seconds}초
    embed.set_footer(text=f"⏱️ 다음 변동까지: {remain}초")

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

    await ctx.send(embed=embed)

# ───────────── 봇 시작 시 초기화 ─────────────
stock_prices = load_stock_prices()
last_update_time = datetime.datetime.now(datetime.timezone.utc)

@client.event
async def on_ready():
    global last_update_time
    print(f'{client.user}에 로그인하였습니다.')
    await client.change_presence(status=discord.Status.online, activity=discord.Game('Leauge of Legends'))
    if not auto_update_stocks.is_running():
        auto_update_stocks.start()
        print("✅ 주식 자동 갱신 루프 시작됨")
    asyncio.create_task(market_cycle())
    last_update_time = datetime.datetime.now(datetime.timezone.utc)

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
    "JS": "JS"
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

@client.command(aliases=["주식전량구매"])
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


client.run(os.getenv("DISCORD_TOKEN"))