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

def load_data():
    if not os.path.exists(DATA_FILE): # 파일이 없으면 빈 딕셔너리 반환
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data): # 데이터를 JSON 파일에 저장하는 함수
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

enhance_data = load_data() # 아이템 강화 데이터를 불러오기

if os.path.exists(DATA_FILE): # warnings.json 파일이 존재하면 불러오기
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
        warnings = {int(k): v for k, v in data.get('warnings', {}).items()}
        warnings_data = {int(k): v for k, v in data.get('warnings_data', {}).items()}


def save_warnings(): # 경고 데이터를 JSON 파일에 저장하는 함수
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump({'warnings': warnings, 'warnings_data': warnings_data}, f, ensure_ascii=False, indent=4)

# on_ready는 시작할 때 한번만 실행
@client.event
async def on_ready():
    print('Login...')
    print(f'{client.user}에 로그인하였습니다.')
    print(f'ID: {client.user.name}')
    await client.change_presence(status=discord.Status.online, activity=discord.Game('기범이랑 키스'))

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

@client.command(aliases=['패치노트', 'patch'])
async def patchnote(ctx):
    await ctx.message.delete()
    embed = discord.Embed(
        title="📜 패치노트 v1.1.4",
        description="최신 버전 업데이트입니다.",
        color=0xf1c40f  # 노란색
    )
    embed.add_field(name="✨ 새로운 기능", value="- 봇 24시간 가동", inline=False)
    embed.add_field(name="🔮 예정 사항", value="- 버튼출석\n", inline=False)
    embed.set_footer(text="업데이트: 2025-06-14")
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
@client.command(aliases=['머니'])
async def money(ctx, member: discord.Member = None):
    await ctx.message.delete()  # 명령어 삭제
    member = member or ctx.author
    user_id = str(member.id)
    balance = money_data.get(user_id, 0)

    embed = Embed(
        title="💰 잔액 확인",
        description=f"**{member.display_name}** 님의 잔액은 **{balance} byte**입니다.",
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

#  머니 송금
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

client.run(os.getenv("DISCORD_TOKEN"))

# --- 웹 서버로 포트 바인딩해서 Render가 안 죽게 하기 위함 ---
from flask import Flask
import threading

app = Flask(__name__)

@app.route('/')
def index():
    return "MirimBot is alive"

def run_web():
    app.run(host='0.0.0.0', port=8080)

threading.Thread(target=run_web).start()