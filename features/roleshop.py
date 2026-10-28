"""역할 상점: byte 로 디스코드 역할을 산다 (돈이 빠져나가는 곳)

    %역할상점          (%상점) 팔고 있는 역할 보기 · 골라서 구매
    %내역할            산 역할과 남은 기간
    %상점관리          (관리자) 역할 추가 / 가격 · 기간 · 설명 수정 / 판매 중지 / 상점에서 빼기

- 역할은 관리자가 디스코드에서 직접 만들고, %상점관리 에서 골라 가격을 붙인다.
- 기간: 0 이면 영구, N 이면 N일 뒤 봇이 역할을 회수한다. 가진 상태에서 또 사면 기간이 늘어난다. (영구는 한 번만)
- 위험한 권한(관리자, 역할 관리, 추방 …)이 있는 역할은 올릴 수 없다. 봇 역할보다 위에 있는 역할도 봇이 줄 수 없어서 막는다.
- 상점에서 빼거나 판매를 멈춰도 이미 산 사람의 역할은 그대로 둔다. (기간이 있으면 그때 회수)
- 돈을 먼저 빼고 역할을 준다. 역할을 못 주면 (봇 권한 문제 등) 돈을 돌려준다.
"""
import asyncio
import datetime

import discord
from discord.ext import commands
from discord.ui import Button, Modal, RoleSelect, Select, TextInput, View

import database as db
import respond
from bot import client
from fmt import num

MAX_ROLES = 25            # 상점에 올릴 수 있는 역할 수 (메뉴 한 개에 25개까지)
PRICE_MAX = 10 ** 12
DANGEROUS = (
    "administrator", "manage_guild", "manage_roles", "manage_channels", "manage_webhooks",
    "kick_members", "ban_members", "moderate_members", "manage_messages", "mention_everyone",
    "manage_nicknames", "manage_events", "manage_threads", "manage_expressions",
)


def period_text(days):
    return "영구" if not days else f"{days}일"


def role_problem(guild, role):
    """이 역할을 상점에 올릴 수 없는 이유. 괜찮으면 None"""
    if role.is_default():
        return "@everyone 은 팔 수 없어요."
    if role.managed:
        return "봇 / 연동 전용 역할은 팔 수 없어요."
    bad = [p for p in DANGEROUS if getattr(role.permissions, p, False)]
    if bad:
        return f"위험한 권한이 있는 역할은 팔 수 없어요: `{', '.join(bad)}`"
    me = guild.me
    if not me.guild_permissions.manage_roles:
        return "봇에게 **역할 관리** 권한이 없어요."
    if role >= me.top_role:
        return f"봇 역할(**{me.top_role.name}**)보다 아래에 있어야 봇이 줄 수 있어요. 서버 설정 → 역할에서 순서를 바꿔주세요."
    return None


# ───────────── 구매 ─────────────

async def buy(member, role_id):
    """구매. 실패하면 안내(str), 성공하면 {"role", "price", "expires_at", "balance"}"""
    guild = member.guild
    item = await db.get_shop_role(guild.id, role_id)
    role = guild.get_role(role_id)
    if item is None or not item["active"] or role is None:
        return "❌ 지금 팔지 않는 역할이에요."
    problem = role_problem(guild, role)
    if problem:
        return f"❌ 지금은 살 수 없어요. (관리자에게 알려주세요: {problem})"
    now = db.now()

    async with db.user_tx(member.id) as conn:
        owned = await db.get_role_purchase(guild.id, member.id, role_id, conn)
        if owned and owned["expires_at"] is None:
            return "✅ 이미 영구로 가진 역할이에요."
        money = await db.get_money(member.id, conn)
        price = item["price"]
        if money < price:
            return f"💸 돈이 부족해요. (필요: {num(price)} byte / 보유: {num(money)} byte)"
        if item["days"]:
            base = owned["expires_at"] if owned and owned["expires_at"] and owned["expires_at"] > now else now
            expires = base + datetime.timedelta(days=item["days"])
        else:
            expires = None
        await db.update_user(member.id, conn, money=money - price)
        await db.log_money(member.id, "role_shop", -price, f"{role.name} {period_text(item['days'])}", conn)
        await db.set_role_purchase(guild.id, member.id, role_id, expires, conn)

    try:
        await member.add_roles(role, reason=f"역할 상점 구매 ({num(price)} byte)")
    except discord.HTTPException as e:
        # 역할을 못 줬으면 되돌린다
        async with db.user_tx(member.id) as conn:
            await db.receive(member.id, price, conn)
            await db.log_money(member.id, "role_shop_refund", price, f"{role.name} 지급 실패", conn)
            if owned:
                await db.set_role_purchase(guild.id, member.id, role_id, owned["expires_at"], conn)
            else:
                await db.delete_role_purchase(guild.id, member.id, role_id, conn)
        return f"❌ 역할을 주지 못해서 돈을 돌려줬어요. ({type(e).__name__}, 관리자에게 알려주세요)"
    return {"role": role, "price": price, "expires_at": expires, "balance": money - price, "extended": bool(owned)}


async def expire_due():
    """기간이 끝난 역할을 회수한다. 회수한 수"""
    removed = 0
    for p in await db.expired_role_purchases(db.now()):
        guild = client.get_guild(p["guild_id"])
        member = guild and guild.get_member(p["user_id"])
        role = guild and guild.get_role(p["role_id"])
        if member and role and role in member.roles:
            try:
                await member.remove_roles(role, reason="역할 상점 기간 끝")
            except discord.HTTPException as e:
                print(f"[역할상점] 회수 실패 {p}: {type(e).__name__}")
                continue        # 다음에 다시 시도
            await db.add_notice(p["user_id"], f"⌛ 역할 상점에서 산 **{role.name}** 역할의 기간이 끝났어요. (`%역할상점`)")
            removed += 1
        await db.delete_role_purchase(p["guild_id"], p["user_id"], p["role_id"])
    return removed


async def expire_loop():
    """setup_hook 에서 한 번 시작한다. 1분마다 기간이 끝난 역할을 회수한다."""
    await client.wait_until_ready()
    while True:
        try:
            await expire_due()
        except Exception as e:
            print(f"[역할상점] 기간 확인 실패: {type(e).__name__} {e}")
        await asyncio.sleep(60)


# ───────────── 상점 화면 ─────────────

def shop_embed(guild, items, owned):
    embed = discord.Embed(title="🛍️ 역할 상점", color=discord.Color.gold())
    lines = []
    for it in items:
        role = guild.get_role(it["role_id"])
        if role is None:
            continue
        mine = owned.get(it["role_id"], "없음")
        mark = ""
        if mine != "없음":
            mark = " · ✅ 영구 보유" if mine is None else f" · ⏳ <t:{int(mine.timestamp())}:R> 끝"
        desc = f"\n> {it['description']}" if it["description"] else ""
        lines.append(f"{role.mention} — **{num(it['price'])} byte** · {period_text(it['days'])}{mark}{desc}")
    embed.description = "\n".join(lines) if lines else "아직 파는 역할이 없어요. 관리자가 `%상점관리`로 올릴 수 있어요."
    embed.set_footer(text="아래 메뉴에서 골라서 사요 · 기간제는 또 사면 기간이 늘어나요 · %내역할")
    return embed


class ShopView(View):
    def __init__(self, member, items):
        super().__init__(timeout=180)
        self.member = member
        guild = member.guild
        options = []
        for it in items:
            role = guild.get_role(it["role_id"])
            if role is None:
                continue
            options.append(discord.SelectOption(
                label=f"{role.name} — {num(it['price'])} byte"[:100],
                description=(f"{period_text(it['days'])} · {it['description'] or ''}")[:100],
                value=str(it["role_id"]),
            ))
        if options:
            menu = Select(placeholder="살 역할을 골라주세요", options=options[:25])
            menu.callback = self.on_pick
            self.add_item(menu)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.member.id:
            await respond.reply(interaction, "❌ `%역할상점`으로 직접 열어서 사주세요.", ephemeral=True)
            return False
        return True

    async def on_pick(self, interaction):
        role_id = int(interaction.data["values"][0])
        item = await db.get_shop_role(interaction.guild.id, role_id)
        role = interaction.guild.get_role(role_id)
        if item is None or role is None:
            await respond.reply(interaction, "❌ 지금 팔지 않는 역할이에요.", ephemeral=True)
            return
        confirm = respond.ConfirmView(interaction.user, timeout=60)   # 두 번 눌러도 한 번만 산다
        button = Button(label=f"{num(item['price'])} byte에 사기", emoji="🛒", style=discord.ButtonStyle.success)

        async def go(inner):
            await respond.defer(inner)
            result = await buy(inner.user, role_id)
            if isinstance(result, str):
                await respond.edit(inner, content=result, view=None)
                return
            until = "영구" if result["expires_at"] is None else f"<t:{int(result['expires_at'].timestamp())}:f>까지"
            what = "기간을 늘렸어요" if result["extended"] else "샀어요"
            await respond.edit(inner, content=f"🎉 {result['role'].mention} 역할을 {what}! ({until}) 남은 돈 {num(result['balance'])} byte", view=None)

        button.callback = go
        confirm.add_item(button)
        await respond.reply(
            interaction,
            f"{role.mention} 역할을 **{num(item['price'])} byte**에 살까요? ({period_text(item['days'])})",
            view=confirm, ephemeral=True,
        )


@client.command(aliases=["역할상점", "상점"])
async def role_shop(ctx):
    if ctx.guild is None:
        return
    items = [it for it in await db.shop_roles(ctx.guild.id) if it["active"]]
    owned = {p["role_id"]: p["expires_at"] for p in await db.role_purchases_of(ctx.guild.id, ctx.author.id)}
    await ctx.send(embed=shop_embed(ctx.guild, items, owned), view=ShopView(ctx.author, items) if items else None)


@client.command(aliases=["내역할"])
async def my_shop_roles(ctx):
    if ctx.guild is None:
        return
    lines = []
    for p in await db.role_purchases_of(ctx.guild.id, ctx.author.id):
        role = ctx.guild.get_role(p["role_id"])
        if role is None:
            continue
        until = "영구" if p["expires_at"] is None else f"<t:{int(p['expires_at'].timestamp())}:R> 끝"
        lines.append(f"{role.mention} · {until}")
    await ctx.send(embed=discord.Embed(
        title=f"🎽 {ctx.author.display_name}님이 산 역할",
        description="\n".join(lines) or "아직 산 역할이 없어요. `%역할상점`에서 둘러보세요!",
        color=discord.Color.gold(),
    ))


# ───────────── 관리자 패널 ─────────────

def admin_embed(guild, items):
    lines = []
    for it in items:
        role = guild.get_role(it["role_id"])
        name = role.mention if role else f"~~(지워진 역할 {it['role_id']})~~"
        state = "▶️ 판매 중" if it["active"] else "⏸️ 판매 중지"
        warn = ""
        if role is not None and role_problem(guild, role):
            warn = f"\n> ⚠️ {role_problem(guild, role)}"
        lines.append(f"{name} — {num(it['price'])} byte · {period_text(it['days'])} · {state}{warn}")
    embed = discord.Embed(title="🛠️ 역할 상점 관리", color=discord.Color.dark_gold())
    embed.description = "\n".join(lines) or "아직 올린 역할이 없어요. 아래 메뉴에서 역할을 골라 가격을 붙이세요."
    embed.set_footer(text=f"역할은 디스코드에서 먼저 만들어주세요 · 최대 {MAX_ROLES}개 · 봇 역할보다 아래 · 위험한 권한 없는 역할만")
    return embed


class AdminView(View):
    def __init__(self, guild, user_id):
        super().__init__(timeout=900)
        self.guild = guild
        self.user_id = user_id
        self.message = None
        pick = RoleSelect(placeholder="➕ 올리거나 고칠 역할 고르기", min_values=1, max_values=1)
        pick.callback = self.on_role
        self.add_item(pick)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await respond.reply(interaction, "❌ `%상점관리`를 연 관리자만 쓸 수 있어요.", ephemeral=True)
            return False
        return True

    async def refresh(self):
        if self.message:
            try:
                await self.message.edit(embed=admin_embed(self.guild, await db.shop_roles(self.guild.id)), view=self)
            except discord.HTTPException:
                pass

    async def on_role(self, interaction):
        role = self.guild.get_role(int(interaction.data["values"][0]))
        if role is None:
            await respond.reply(interaction, "❌ 역할을 찾지 못했어요.", ephemeral=True)
            return
        problem = role_problem(self.guild, role)
        if problem:
            await respond.reply(interaction, f"❌ {role.mention}: {problem}", ephemeral=True)
            return
        item = await db.get_shop_role(self.guild.id, role.id)
        if item is None:
            if len(await db.shop_roles(self.guild.id)) >= MAX_ROLES:
                await respond.reply(interaction, f"❌ 상점에는 {MAX_ROLES}개까지 올릴 수 있어요.", ephemeral=True)
                return
            await interaction.response.send_modal(RoleModal(self, role, None))
            return
        await respond.reply(interaction, f"{role.mention} — {num(item['price'])} byte · {period_text(item['days'])}",
                            view=RoleItemView(self, role, item), ephemeral=True)


class RoleItemView(View):
    """이미 올린 역할 하나: 수정 / 판매 중지 · 재개 / 빼기"""
    def __init__(self, panel, role, item):
        super().__init__(timeout=300)
        self.panel, self.role, self.item = panel, role, item
        for label, emoji, style, callback in (
            ("가격 · 기간 · 설명 수정", "✏️", discord.ButtonStyle.primary, self.on_edit),
            ("판매 다시 하기" if not item["active"] else "판매 중지", "▶️" if not item["active"] else "⏸️",
             discord.ButtonStyle.secondary, self.on_toggle),
            ("상점에서 빼기", "🗑️", discord.ButtonStyle.danger, self.on_remove),
        ):
            button = Button(label=label, emoji=emoji, style=style)
            button.callback = callback
            self.add_item(button)

    async def on_edit(self, interaction):
        await interaction.response.send_modal(RoleModal(self.panel, self.role, self.item))

    async def on_toggle(self, interaction):
        await respond.defer(interaction)
        await db.set_shop_role_active(self.panel.guild.id, self.role.id, not self.item["active"])
        await respond.edit(interaction, content=f"{self.role.mention} {'판매를 다시 시작했어요.' if not self.item['active'] else '판매를 멈췄어요.'}", view=None)
        await self.panel.refresh()

    async def on_remove(self, interaction):
        await respond.defer(interaction)
        await db.delete_shop_role(self.panel.guild.id, self.role.id)
        await respond.edit(interaction, content=f"🗑️ {self.role.mention}을(를) 상점에서 뺐어요. (이미 산 사람의 역할은 그대로예요)", view=None)
        await self.panel.refresh()


class RoleModal(Modal):
    def __init__(self, panel, role, item):
        super().__init__(title=f"🏷️ {role.name}"[:45])
        self.panel, self.role = panel, role
        self.price = TextInput(label="가격 (byte)", placeholder="예: 500000, 50만", default=str(int(item["price"])) if item else None)
        self.days = TextInput(label="기간 (일, 0 = 영구)", placeholder="예: 7", default=str(item["days"]) if item else "0", max_length=4)
        self.description = TextInput(label="설명 (선택)", required=False, max_length=80,
                                     default=item["description"] if item else None, placeholder="예: 닉네임이 금색이 돼요")
        for field in (self.price, self.days, self.description):
            self.add_item(field)

    async def on_submit(self, interaction):
        await respond.defer(interaction)
        from features.market import parse_price
        price = parse_price(self.price.value)
        days = self.days.value.strip()
        if price is None or not 0 < price <= PRICE_MAX:
            await respond.reply(interaction, "❌ 가격은 1 이상 숫자로 써주세요. (예: 500000, 50만)", ephemeral=True)
            return
        if not days.isdigit() or int(days) > 3650:
            await respond.reply(interaction, "❌ 기간은 0~3650 사이 숫자로 써주세요. (0 = 영구)", ephemeral=True)
            return
        await db.upsert_shop_role(self.panel.guild.id, self.role.id, price, int(days), self.description.value.strip() or None)
        await respond.reply(interaction, f"✅ {self.role.mention} — **{num(price)} byte** · {period_text(int(days))}", ephemeral=True)
        await self.panel.refresh()


@client.command(aliases=["상점관리"])
@commands.has_permissions(administrator=True)
async def role_shop_admin(ctx):
    if ctx.guild is None:
        return
    view = AdminView(ctx.guild, ctx.author.id)
    view.message = await ctx.send(embed=admin_embed(ctx.guild, await db.shop_roles(ctx.guild.id)), view=view)
