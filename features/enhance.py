"""아이템 강화: 강화, 강화목록, 강화판매"""
import math
from random import uniform

import discord

import database as db
from bot import client


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

    user_id = ctx.author.id
    user_items = await db.get_enhance_items(user_id)
    current_level = user_items.get(item_name, 0)
    balance = await db.get_money(user_id)

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

        attempts = 0
        successes = 0
        maintained = 0
        downgraded = 0
        destroyed = False
        total_cost = 0
        logs = []
        blocked_cost = None

        # 강화하는 동안 이 유저의 데이터를 잠가서, 버튼 연타로 두 번 처리되지 않게 한다.
        async with db.user_tx(user_id) as conn:
            # 최신 잔액 및 아이템 레벨 확인
            balance = await db.get_money(user_id, conn)
            level = (await db.get_enhance_items(user_id, conn)).get(item_name, 0)

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
                        blocked_cost = cost
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

            # 데이터 저장 (한 번이라도 시도했을 때만)
            if attempts > 0:
                await db.update_user(user_id, conn, money=balance)
                if destroyed:
                    await db.delete_enhance_item(user_id, item_name, conn)
                else:
                    await db.set_enhance_level(user_id, item_name, level, conn)

        if blocked_cost is not None:
            result = discord.Embed(
                title="💸 강화 불가",
                description=(
                    f"필요한 금액: {blocked_cost:,} byte\n"
                    f"보유 금액: {balance:,} byte"
                ),
                color=discord.Color.red()
            )
            await interaction.edit_original_response(
                embed=result,
                view=None
            )
            return

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
    user_items = await db.get_enhance_items(ctx.author.id)

    if not user_items:
        await ctx.send("😢 아직 강화한 아이템이 없어요!")
        return

    embed = discord.Embed(title=f"{ctx.author.display_name}님의 강화 아이템 목록", color=0x2ecc71)
    for item_name, level in user_items.items():
        embed.add_field(name=f"{item_name} (+{level})", value=" ", inline=True)

    await ctx.send(embed=embed)


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
    user_id = ctx.author.id

    # 아이템 삭제와 돈 지급을 한 번에 처리
    async with db.user_tx(user_id) as conn:
        level = await db.delete_enhance_item(user_id, item_name, conn)

        if level is not None:
            # 판매 가격: 100 * 2.25^강화 레벨
            earned = (int)(100 * (2.25 ** level))
            balance = await db.add_money(user_id, earned, conn)

    # 아이템이 없으면
    if level is None:
        await ctx.send(
            f"{ctx.author.mention} | ❌ `{item_name}` 아이템이 없습니다."
        )
        return

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
        value=f"**{balance:,} byte**",
        inline=False
    )

    embed.set_footer(text="판매가 완료되었습니다.")

    await ctx.send(embed=embed)
