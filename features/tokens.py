"""토큰: 토큰 구매/확인/최대교환, 관리자 토큰 추가/제거/구매가, 상점 드롭다운"""


import discord
from discord import ButtonStyle, SelectOption
from discord.ext import commands
from discord.ui import Button, Select, View

import database as db
from bot import client


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
        user_id = interaction.user.id
        price = item["price"]

        async with db.user_tx(user_id) as conn:
            # ✅ 토큰 가져오기
            user_token = (await db.get_user(user_id, conn))["tokens"]

            if user_token >= price:
                await db.update_user(user_id, conn, tokens=user_token - price)
                await db.add_inventory_item(user_id, selected_name, 1, conn)

        if user_token < price:
            await interaction.response.send_message(
                f"❌ `{selected_name}` 구매에 필요한 **{price - user_token} 토큰**이 부족합니다!",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"✅ `{selected_name}` 아이템을 **{price} 토큰**에 구매했습니다!",
            ephemeral=True
        )


async def purchase_tokens(user_id, count, price, total_cost):
    """토큰 count 개 구매. 확인 창을 띄운 뒤 가격이 바뀌었거나 잔액이 부족하면 None,
    성공하면 {"money", "tokens", "price"} (구매 후 값)."""
    async with db.user_tx(user_id) as conn:
        user = await db.get_user(user_id, conn)
        if user["token_price"] != price or user["money"] < total_cost:
            return None

        result = {
            "money": user["money"] - total_cost,
            "tokens": user["tokens"] + count,
            "price": price * (2 ** count),
        }
        await db.update_user(
            user_id, conn,
            money=result["money"],
            tokens=result["tokens"],
            token_price=result["price"],
        )
        return result


@client.command(aliases=["토큰구매", "토큰교환"])
async def buy_token(ctx, amount: int = 1):
    await ctx.message.delete()
    user_id = ctx.author.id

    if amount <= 0:
        await ctx.send("❌ 1 이상의 수량을 입력해주세요.")
        return

    user = await db.get_user(user_id)
    price = user["token_price"]
    total_cost = sum([price * (2 ** i) for i in range(amount)])

    if user["money"] < total_cost:
        shortfall = total_cost - user["money"]
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
        user_tokens = await purchase_tokens(user_id, amount, price, total_cost)
        if user_tokens is None:
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="❌ 구매 실패",
                    description="잔액 또는 토큰 가격이 변경되었습니다. 명령어를 다시 실행해주세요.",
                    color=discord.Color.red()
                ),
                view=None
            )
            return

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
    data = await db.get_user(member.id)

    embed = discord.Embed(
        title="🎫 토큰 현황",
        description=f"{member.display_name}님의 토큰 정보입니다.",
        color=discord.Color.purple()
    )
    embed.add_field(name="보유 토큰", value=f"{data['tokens']} 개", inline=True)
    embed.add_field(name="다음 구매 가격", value=f"{data['token_price']} byte", inline=True)

    await ctx.send(embed=embed)

@client.command(aliases=["토큰최대교환"])
async def buy_token_max(ctx):
    await ctx.message.delete()
    user_id = ctx.author.id

    user = await db.get_user(user_id)
    current_money = user["money"]

    start_price = user["token_price"]
    price = start_price
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
        user_tokens = await purchase_tokens(user_id, max_tokens, start_price, total_cost)
        if user_tokens is None:
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="❌ 교환 실패",
                    description="잔액 또는 토큰 가격이 변경되었습니다. 명령어를 다시 실행해주세요.",
                    color=discord.Color.red()
                ),
                view=None
            )
            return

        result = discord.Embed(
            title="✅ 최대 토큰 교환 완료",
            description=f"{max_tokens}개의 토큰을 교환했습니다!",
            color=discord.Color.green()
        )
        result.add_field(name="남은 금액", value=f"{user_tokens['money']:.2f} byte", inline=True)
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

    user_id = member.id

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

        tokens = await db.add_tokens(user_id, amount)

        result = discord.Embed(
            title="✅ 토큰 추가 완료",
            description=f"{member.display_name}님에게 **{amount}개**의 토큰을 지급했습니다.",
            color=discord.Color.green()
        )
        result.add_field(name="총 보유 토큰", value=f"{tokens} 개", inline=False)
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

    user_id = member.id

    if (await db.get_user(user_id))["tokens"] < amount:
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

        tokens = await db.add_tokens(user_id, -amount)
        if tokens is None:
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="❌ 토큰 제거 실패",
                    description="해당 유저의 토큰 수가 부족합니다.",
                    color=discord.Color.red()
                ),
                view=None
            )
            return

        result = discord.Embed(
            title="🗑️ 토큰 제거 완료",
            description=f"{member.display_name}님에게서 **{amount}개**의 토큰을 제거했습니다.",
            color=discord.Color.red()
        )
        result.add_field(name="남은 토큰", value=f"{tokens} 개", inline=False)
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

    user_id = member.id
    old_price = (await db.get_user(user_id))["token_price"]

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

        await db.update_user(user_id, token_price=new_price)

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
