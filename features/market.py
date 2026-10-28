"""암시장: 유저끼리 강화 아이템(능력 슬롯 포함)을 사고판다.

    %강화 암시장     목록 보기 (페이지) / 구매 / 판매 등록 / 내 판매 관리

- 판매 등록하면 아이템은 내 목록에서 빠져 암시장에 맡겨진다. (그동안 강화 / 판매 / 능력 효과 X)
  팔리면 구매자에게 가고, 등록을 취소하거나 24시간이 지나면 나에게 돌아온다.
- 팔리면 수수료 10% 를 떼고 받는다. 송금 수수료와 같게 해서, 송금 대신 암시장으로 돈을 옮겨도 이득이 없게 했다.
- 가격은 1,000 byte ~ 봇 판매가의 20배. (+1 아이템을 엄청 비싸게 올려서 돈을 옮기는 것 방지)
- 예상 가격: 같은 레벨 최근 거래 평균. 거래가 없으면 봇 판매가 × (1 + 켜진 슬롯 하나당 30%).
- 구매자가 같은 이름의 아이템을 갖고 있으면 '칼#12' 처럼 등록 번호를 붙여서 받는다.
- 토큰도 묶음으로 사고판다. (v1.3.2) 개당 100 ~ 10만 byte, 수수료와 등록 수 제한은 아이템과 같다.
  예상 가격: 최근 토큰 거래의 개당 평균, 없으면 판매자가 지금 토큰을 사는 가격.
"""
import datetime

import discord
from discord.ext import commands
from discord.ui import Button, Modal, Select, TextInput, View

import database as db
import respond
from features import abilities, enhance, tokens as token_shop
from fmt import debt_line, num

# ───────────── 밸런스 설정 ─────────────
PAGE_SIZE = 5
FEE = 0.10                 # 판매 수수료 (판매자가 받는 돈에서 뗀다)
LISTING_HOURS = 24         # 등록 유지 시간
MAX_LISTINGS = 3           # 1인 동시 등록 수
MIN_PRICE = 1000
PRICE_CAP_MULT = 20        # 최대 가격 = 봇 판매가 × 20
SLOT_PREMIUM = 0.3         # 거래 기록이 없을 때 예상 가격: 켜진 슬롯 하나당 +30%
TOKEN_UNIT_PRICE = (100, 100_000)   # 토큰 개당 가격 범위
TOKEN_VALUE = "__token__"           # 판매 메뉴에서 '토큰'을 고른 값


# ───────────── 계산 ─────────────

def is_token(listing):
    return listing.get("tokens", 0) > 0


def title_of(listing):
    """'칼 +9' / '🪙 토큰 5개'"""
    if is_token(listing):
        return f"🪙 토큰 {listing['tokens']}개"
    return f"{listing['item_name']} +{listing['level']}"


def listing_summary(listing, limit=95):
    """목록에 보여줄 한 줄 설명: 아이템은 능력, 토큰은 개당 가격"""
    if is_token(listing):
        return f"개당 {num(listing['price'] / listing['tokens'])} byte"
    return short_summary(listing["level"], listing["abilities"], limit)

def active_rows(level, rows):
    """켜진 슬롯만 (레벨이 슬롯 레벨 이상)"""
    return [r for r in rows if level >= abilities.slot_level(r["slot"])]


def short_summary(level, rows, limit=95):
    """'🛡️파괴 방지 6% · 💥대성공 3%' (선택 메뉴 설명은 100자까지라 자른다)"""
    parts = []
    for r in active_rows(level, rows):
        info = abilities.ABILITIES.get(r["ability"])
        if info:
            parts.append(f"{info['emoji']}{info['name']} {abilities.format_value(r['ability'], r['value'])}")
    text = " · ".join(parts) or "능력 없음"
    return text if len(text) <= limit else text[: limit - 1] + "…"


def price_cap(level):
    return enhance.SELL_PRICE[level] * PRICE_CAP_MULT


async def expected_price(level, rows):
    """같은 레벨 최근 거래 평균, 없으면 봇 판매가 × (1 + 켜진 슬롯 × 30%)"""
    recent = await db.recent_trade_prices(level)
    if recent:
        guess = sum(recent) / len(recent)
    else:
        guess = enhance.SELL_PRICE[level] * (1 + SLOT_PREMIUM * len(active_rows(level, rows)))
    return max(MIN_PRICE, min(round(guess), price_cap(level)))


async def expected_token_price(user_id):
    """토큰 개당 예상 가격: 최근 토큰 거래 평균, 없으면 이 사람이 지금 토큰을 사는 가격"""
    recent = await db.recent_token_prices()
    if recent:
        guess = sum(recent) / len(recent)
    else:
        guess, _ = await token_shop.price_of(user_id)
    low, high = TOKEN_UNIT_PRICE
    return max(low, min(round(guess), high))


def parse_price(text):
    """'1,200,000' / '120만' / '1.5억' → 정수. 못 읽으면 None"""
    text = text.replace(",", "").replace(" ", "").replace("byte", "")
    unit = 1
    for word, mult in (("억", 100_000_000), ("만", 10_000), ("천", 1_000)):
        if text.endswith(word):
            text, unit = text[: -len(word)], mult
            break
    try:
        return int(float(text) * unit)
    except ValueError:
        return None


async def give_item(user_id, item_name, level, rows, conn, tag):
    """아이템과 능력을 user_id 에게 넣는다. 같은 이름이 있으면 '이름#태그'. 실제로 들어간 이름을 돌려준다."""
    owned = await db.get_enhance_items(user_id, conn)
    name = item_name if item_name not in owned else f"{item_name}#{tag}"
    await db.set_enhance_level(user_id, name, level, conn)
    for r in rows:
        await db.set_ability(user_id, name, r["slot"], r["ability"], r["tier"], r["value"], conn)
        if r.get("locked"):
            await db.set_ability_lock(user_id, name, r["slot"], True, conn)
    await abilities.sync_slots(user_id, name, level, conn)   # 등록한 뒤 슬롯 규칙이 바뀌었으면 빈 칸 채우기
    return name


async def hand_over(user_id, listing, conn):
    """등록된 물건을 user_id 에게 넘긴다. 받은 것의 이름('칼#12 +9' / '🪙 토큰 5개')을 돌려준다."""
    if is_token(listing):
        await db.add_tokens(user_id, listing["tokens"], conn)
        return title_of(listing)
    name = await give_item(user_id, listing["item_name"], listing["level"], listing["abilities"], conn, listing["id"])
    return f"{name} +{listing['level']}"


async def return_to_seller(listing_id, reason):
    """등록을 지우고 물건을 판매자에게 돌려준다. (만료 / 취소) 돌려준 것의 이름 또는 None"""
    listing = await db.get_listing(listing_id)
    if listing is None:
        return None
    async with db.user_tx(listing["seller_id"]) as conn:
        if await db.delete_listing(listing_id, conn) is None:
            return None
        name = await hand_over(listing["seller_id"], listing, conn)
        if reason:
            await db.add_notice(listing["seller_id"], f"🕶️ 암시장 #{listing_id} {reason}: `{name}`이(가) 돌아왔어요.", conn)
    return name


async def expire_old():
    """24시간 지난 등록을 판매자에게 돌려준다. (암시장을 열 때마다 확인)"""
    for listing_id in await db.expired_listing_ids(db.now()):
        await return_to_seller(listing_id, "등록 기간 만료")


# ───────────── 거래 ─────────────

async def list_item(user_id, item_name, price):
    """판매 등록. 실패하면 안내(str), 성공하면 등록 dict"""
    async with db.user_tx(user_id) as conn:
        level = (await db.get_enhance_items(user_id, conn)).get(item_name)
        if level is None:
            return "❌ 아이템이 없습니다."
        if len(await db.seller_listings(user_id, conn)) >= MAX_LISTINGS:
            return f"❌ 암시장에는 한 번에 {MAX_LISTINGS}개까지 올릴 수 있어요. (`📦 내 판매`에서 정리)"
        if not MIN_PRICE <= price <= price_cap(level):
            return f"❌ +{level} 아이템은 {num(MIN_PRICE)} ~ {num(price_cap(level))} byte 사이로 올릴 수 있어요."
        rows = [r for r in await db.get_abilities(user_id, conn) if r["item_name"] == item_name]
        await db.delete_enhance_item(user_id, item_name, conn)   # 능력도 같이 빠진다 (등록에 보관)
        expires = db.now() + datetime.timedelta(hours=LISTING_HOURS)
        snapshot = [{k: r[k] for k in ("slot", "ability", "tier", "value", "locked")} for r in rows]
        listing_id = await db.add_listing(user_id, item_name, level, snapshot, price, expires, conn)
    return {"id": listing_id, "item_name": item_name, "level": level, "price": price, "abilities": snapshot,
            "expires_at": expires}


async def list_tokens(user_id, count, unit_price):
    """토큰 묶음 판매 등록. 실패하면 안내(str), 성공하면 등록 dict"""
    low, high = TOKEN_UNIT_PRICE
    if count <= 0:
        return "❌ 1개 이상 올려주세요."
    if not low <= unit_price <= high:
        return f"❌ 토큰은 개당 {num(low)} ~ {num(high)} byte 사이로 올릴 수 있어요."
    async with db.user_tx(user_id) as conn:
        if len(await db.seller_listings(user_id, conn)) >= MAX_LISTINGS:
            return f"❌ 암시장에는 한 번에 {MAX_LISTINGS}개까지 올릴 수 있어요. (`📦 내 판매`에서 정리)"
        if await db.add_tokens(user_id, -count, conn) is None:
            return "❌ 토큰이 부족해요."
        price = unit_price * count
        expires = db.now() + datetime.timedelta(hours=LISTING_HOURS)
        listing_id = await db.add_listing(user_id, "토큰", 0, [], price, expires, conn, tokens=count)
    return {"id": listing_id, "tokens": count, "price": price, "expires_at": expires}


async def buy(buyer_id, listing_id):
    """구매. 실패하면 안내(str), 성공하면 {"listing", "name"(받은 것), "balance"}"""
    listing = await db.get_listing(listing_id)
    if listing is None or listing["expires_at"] <= db.now():
        return "❌ 이미 팔렸거나 내려간 물건이에요."
    seller_id = listing["seller_id"]
    if seller_id == buyer_id:
        return "❌ 내가 올린 물건은 살 수 없어요. (`📦 내 판매`에서 취소할 수 있어요)"

    async with db.user_tx(buyer_id, seller_id) as conn:
        listing = await db.get_listing(listing_id, conn, lock=True)
        if listing is None:
            return "❌ 방금 다른 사람이 샀어요."
        price = listing["price"]
        money = await db.get_money(buyer_id, conn)
        if money < price:
            return f"💸 돈이 부족합니다. (필요: {num(price)} byte / 보유: {num(money)} byte)"
        if not is_token(listing) and len(await db.get_enhance_items(buyer_id, conn)) >= enhance.MAX_ITEMS:
            return f"❌ 강화 아이템은 최대 {enhance.MAX_ITEMS}개까지 가질 수 있어요. (`%강화 판매`로 정리)"

        await db.delete_listing(listing_id, conn)
        fee = price * FEE
        await db.update_user(buyer_id, conn, money=money - price)
        await db.receive(seller_id, price - fee, conn)
        name = await hand_over(buyer_id, listing, conn)
        slots = len(listing["abilities"])
        await db.add_trade(seller_id, buyer_id, listing["item_name"], listing["level"], slots, price, conn,
                           tokens=listing.get("tokens", 0))
        memo = f"#{listing_id} {title_of(listing)}"
        await db.log_money(buyer_id, "market_buy", -price, memo, conn)
        await db.log_money(seller_id, "market_sell", price - fee, memo, conn)
        await db.log_money(seller_id, "market_fee", -fee, memo, conn)
        await db.add_notice(
            seller_id,
            f"🕶️ 암시장 #{listing_id} `{title_of(listing)}`이(가) {num(price)} byte에 팔렸어요! "
            f"(수수료 {int(FEE * 100)}% 빼고 {num(price - fee)} byte 입금)",
            conn,
        )
    return {"listing": listing, "name": name, "balance": money - price}


async def cancel(user_id, listing_id):
    listing = await db.get_listing(listing_id)
    if listing is None or listing["seller_id"] != user_id:
        return "❌ 내 등록이 아니거나 이미 정리됐어요."
    name = await return_to_seller(listing_id, None)
    return f"↩️ #{listing_id} 등록을 취소했어요. `{name}`이(가) 돌아왔어요." if name else "❌ 이미 정리됐어요."


# ───────────── 화면 ─────────────

class MarketView(View):
    """%강화 암시장 메인 화면: 페이지 넘기기, 물건 고르기, 구매, 판매 등록, 내 판매"""

    def __init__(self, user_id):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.page = 0
        self.selected = None
        self.listings = []
        self.notice = ""
        self.message = None

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await respond.reply(interaction, "❌ 명령어를 실행한 사람만 쓸 수 있어요. `%강화 암시장`으로 직접 열어보세요!", ephemeral=True)
            return False
        return True

    async def load(self):
        await expire_old()
        self.listings = await db.active_listings(db.now())
        pages = max(1, -(-len(self.listings) // PAGE_SIZE))
        self.page = min(self.page, pages - 1)
        if self.selected not in {l["id"] for l in self.listings}:
            self.selected = None

    def page_items(self):
        return self.listings[self.page * PAGE_SIZE:(self.page + 1) * PAGE_SIZE]

    def make_embed(self):
        pages = max(1, -(-len(self.listings) // PAGE_SIZE))
        embed = discord.Embed(
            title="🕶️ 암시장",
            description=self.notice or "강화 아이템과 🪙 토큰을 사고팔아요. 아래 메뉴에서 물건을 고르고 🛒 구매, 내 물건은 💰 판매로 올리세요.",
            color=0x2c2f33,
        )
        if not self.listings:
            embed.add_field(name="텅…", value="아직 올라온 물건이 없어요. 첫 판매자가 되어 보세요!", inline=False)
        for l in self.page_items():
            mark = "👉 " if l["id"] == self.selected else ""
            extra = "" if is_token(l) else f" · 봇 판매가 {num(enhance.SELL_PRICE[l['level']])}"
            embed.add_field(
                name=f"{mark}`#{l['id']}` {title_of(l)} — {num(l['price'])} byte",
                value=(
                    f"{'🪙' if is_token(l) else '✨'} {listing_summary(l, 200)}\n"
                    f"판매자 <@{l['seller_id']}>{extra} · <t:{int(l['expires_at'].timestamp())}:R> 만료"
                ),
                inline=False,
            )
        embed.set_footer(text=f"{self.page + 1}/{pages} 페이지 · 물건 {len(self.listings)}개 · 판매 수수료 {int(FEE * 100)}% · 등록 {LISTING_HOURS}시간")
        return embed

    def build(self):
        self.clear_items()
        items = self.page_items()
        if items:
            menu = Select(
                placeholder="살 물건을 골라 주세요",
                options=[
                    discord.SelectOption(
                        label=f"#{l['id']} {title_of(l)} — {num(l['price'])}"[:100],
                        description=listing_summary(l),
                        value=str(l["id"]),
                        default=l["id"] == self.selected,
                    )
                    for l in items
                ],
                row=0,
            )
            menu.callback = self.on_select
            self.add_item(menu)

        pages = max(1, -(-len(self.listings) // PAGE_SIZE))
        chosen = next((l for l in self.listings if l["id"] == self.selected), None)

        def add(label, emoji, style, callback, disabled=False):
            button = Button(label=label, emoji=emoji, style=style, disabled=disabled, row=1)
            button.callback = callback
            self.add_item(button)

        add("이전", "◀️", discord.ButtonStyle.secondary, self.on_prev, self.page == 0)
        add("다음", "▶️", discord.ButtonStyle.secondary, self.on_next, self.page >= pages - 1)
        add(f"#{chosen['id']} 구매 ({num(chosen['price'])})" if chosen else "구매", "🛒",
            discord.ButtonStyle.success, self.on_buy, chosen is None)
        add("판매", "💰", discord.ButtonStyle.primary, self.on_sell)
        add("내 판매", "📦", discord.ButtonStyle.secondary, self.on_mine)

    async def refresh(self, interaction=None, reload=True):
        """reload=False 면 DB 를 다시 읽지 않고 이미 불러온 목록으로 그린다 (페이지 넘기기 / 고르기).
        구매는 어차피 DB 에서 다시 확인하니까, 그사이 팔린 물건을 골라도 '이미 팔렸다'고 나온다."""
        if reload:
            await self.load()
        self.build()
        if interaction is not None:
            await respond.edit(interaction, embed=self.make_embed(), view=self)
        elif self.message:
            try:
                await self.message.edit(embed=self.make_embed(), view=self)
            except discord.HTTPException:
                pass

    async def on_select(self, interaction):
        await respond.defer(interaction)
        self.selected = int(interaction.data["values"][0])
        self.notice = ""
        await self.refresh(interaction, reload=False)

    async def on_prev(self, interaction):
        await respond.defer(interaction)
        self.page -= 1
        await self.refresh(interaction, reload=False)

    async def on_next(self, interaction):
        await respond.defer(interaction)
        self.page += 1
        await self.refresh(interaction, reload=False)

    async def on_buy(self, interaction):
        await respond.defer(interaction)
        result = await buy(self.user_id, self.selected)
        if isinstance(result, str):
            self.notice = result
        else:
            l = result["listing"]
            self.notice = (
                f"🛒 **{result['name']}**을(를) {num(l['price'])} byte에 샀어요! (남은 돈 {num(result['balance'])} byte)"
                + ("" if is_token(l) else f"\n`%강화 능력설정 {result['name'].rsplit(' +', 1)[0]}`으로 능력을 확인하세요.")
            )
            self.selected = None
        await self.refresh(interaction)

    async def on_sell(self, interaction):
        # 입력창(모달)은 아이템을 고르는 메뉴(새 상호작용)에서 띄우므로, 여기서는 먼저 defer 해도 된다
        await respond.defer(interaction)
        items = await db.get_enhance_items(self.user_id)
        token_count = (await db.get_user(self.user_id))["tokens"]
        if not items and token_count <= 0:
            await respond.reply(interaction, "❌ 팔 강화 아이템이나 토큰이 없어요. `%강화 <이름>`으로 만들어 보세요!", ephemeral=True)
            return
        view = SellPickView(self, items, await db.get_abilities(self.user_id), token_count)
        await view.prepare()
        await respond.reply(interaction, "💰 무엇을 올릴까요? 고르면 가격 입력창이 떠요.", view=view, ephemeral=True)

    async def on_mine(self, interaction):
        await respond.defer(interaction)
        mine = await db.seller_listings(self.user_id)
        if not mine:
            await respond.reply(interaction, "📦 올려 둔 물건이 없어요.", ephemeral=True)
            return
        lines = [
            f"`#{l['id']}` {title_of(l)} — {num(l['price'])} byte · <t:{int(l['expires_at'].timestamp())}:R> 만료"
            for l in mine
        ]
        await respond.reply(interaction, "📦 **내 판매**\n" + "\n".join(lines), view=MyListingsView(self, mine), ephemeral=True)

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


class SellPickView(View):
    """판매할 아이템 / 토큰 고르기 (누른 사람에게만 보임) → 가격 입력창"""

    def __init__(self, market, items, rows, token_count=0):
        super().__init__(timeout=120)
        self.market = market
        self.items = items
        self.rows = rows
        self.token_count = token_count
        self.expected = {}

    def rows_of(self, name):
        return [r for r in self.rows if r["item_name"] == name]

    async def prepare(self):
        options = []
        if self.token_count > 0:
            self.expected[TOKEN_VALUE] = await expected_token_price(self.market.user_id)
            options.append(discord.SelectOption(
                label=f"🪙 토큰 (보유 {self.token_count}개, 개당 예상 {num(self.expected[TOKEN_VALUE])})"[:100],
                description="개수와 개당 가격을 정해서 묶음으로 올려요",
                value=TOKEN_VALUE,
            ))
        for name, level in sorted(self.items.items(), key=lambda x: -x[1])[:24]:
            self.expected[name] = await expected_price(level, self.rows_of(name))
            options.append(discord.SelectOption(
                label=f"{name} +{level} (예상 {num(self.expected[name])})"[:100],
                description=short_summary(level, self.rows_of(name)),
                value=name,
            ))
        menu = Select(placeholder="올릴 아이템", options=options)
        menu.callback = self.on_pick
        self.add_item(menu)

    async def on_pick(self, interaction):
        name = interaction.data["values"][0]
        if name == TOKEN_VALUE:
            await interaction.response.send_modal(TokenModal(self.market, self.token_count, self.expected[name]))
            return
        level = self.items[name]
        await interaction.response.send_modal(PriceModal(self.market, name, level, self.expected[name]))


class TokenModal(Modal):
    """토큰 묶음 판매 입력창: 개수 + 개당 가격"""

    def __init__(self, market, owned, expected):
        super().__init__(title="🕶️ 🪙 토큰 판매 등록")
        self.market = market
        self.count = TextInput(label=f"올릴 개수 (보유 {owned}개)"[:45], default=str(owned), max_length=6)
        low, high = TOKEN_UNIT_PRICE
        self.unit = TextInput(
            label=f"개당 가격 (예상 {num(expected)} byte)"[:45],
            placeholder=f"{num(low)} ~ {num(high)} · 2천 / 1.5만 처럼 써도 돼요"[:100],
            default=str(int(expected)),
            max_length=20,
        )
        self.add_item(self.count)
        self.add_item(self.unit)

    async def on_submit(self, interaction):
        await respond.defer(interaction)
        count = parse_price(self.count.value)
        unit = parse_price(self.unit.value)
        if count is None or unit is None:
            await respond.reply(interaction, "❌ 개수와 가격을 숫자로 입력해주세요.", ephemeral=True)
            return
        result = await list_tokens(interaction.user.id, count, unit)
        if isinstance(result, str):
            await respond.reply(interaction, result, ephemeral=True)
            return
        await respond.reply(
            interaction,
            f"✅ 암시장 `#{result['id']}`에 **🪙 토큰 {count}개**를 개당 {num(unit)} byte (총 {num(result['price'])} byte)에 올렸어요!\n"
            f"팔리면 수수료 {int(FEE * 100)}%를 빼고 **{num(result['price'] * (1 - FEE))} byte**를 받아요. "
            f"{LISTING_HOURS}시간 안에 안 팔리면 돌아와요.",
            ephemeral=True,
        )
        self.market.notice = f"🆕 `#{result['id']}` 🪙 토큰 {count}개 등록 완료!"
        await self.market.refresh()


class PriceModal(Modal):
    """가격 입력창. 예상 가격이 미리 채워져 있다."""

    def __init__(self, market, item_name, level, expected):
        super().__init__(title=f"🕶️ {item_name} +{level} 판매 등록"[:45])
        self.market = market
        self.item_name = item_name
        self.level = level
        self.price = TextInput(
            label=f"판매 가격 (예상 {num(expected)} byte)"[:45],
            placeholder=f"{num(MIN_PRICE)} ~ {num(price_cap(level))} · 120만 / 1.5억 처럼 써도 돼요"[:100],
            default=str(int(expected)),
            max_length=20,
        )
        self.add_item(self.price)

    async def on_submit(self, interaction):
        await respond.defer(interaction)
        price = parse_price(self.price.value)
        if price is None:
            await respond.reply(interaction, "❌ 가격을 숫자로 입력해주세요. (예: 1200000, 120만)", ephemeral=True)
            return
        result = await list_item(interaction.user.id, self.item_name, price)
        if isinstance(result, str):
            await respond.reply(interaction, result, ephemeral=True)
            return
        await respond.reply(
            interaction,
            f"✅ 암시장 `#{result['id']}`에 **{self.item_name} +{self.level}**을(를) {num(price)} byte에 올렸어요!\n"
            f"팔리면 수수료 {int(FEE * 100)}%를 빼고 **{num(price * (1 - FEE))} byte**를 받아요. "
            f"{LISTING_HOURS}시간 안에 안 팔리면 돌아와요.",
            ephemeral=True,
        )
        self.market.notice = f"🆕 `#{result['id']}` {self.item_name} +{self.level} 등록 완료!"
        await self.market.refresh()


class MyListingsView(View):
    """내 판매: 골라서 등록 취소"""

    def __init__(self, market, mine):
        super().__init__(timeout=120)
        self.market = market
        menu = Select(
            placeholder="취소할 등록 고르기",
            options=[discord.SelectOption(label=f"#{l['id']} {title_of(l)} — {num(l['price'])}"[:100],
                                          value=str(l["id"])) for l in mine],
        )
        menu.callback = self.on_cancel
        self.add_item(menu)

    async def on_cancel(self, interaction):
        await respond.defer(interaction)
        text = await cancel(interaction.user.id, int(interaction.data["values"][0]))
        await respond.edit(interaction, content=text, view=None)
        await self.market.refresh()


@commands.command(name="암시장")
async def black_market(ctx):
    view = MarketView(ctx.author.id)
    await view.load()
    notices = await db.pop_notices(ctx.author.id)   # 팔림 / 만료 알림 (주식 알림도 같이 나온다)
    if notices:
        view.notice = "📬 " + "\n📬 ".join(notices[-5:])
    view.build()
    view.message = await ctx.send(embed=view.make_embed(), view=view)
