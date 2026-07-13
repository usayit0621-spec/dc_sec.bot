import random
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.checks import is_manage_guild

GIVEAWAY_EMOJI = "🎉"


class Giveaway(commands.Cog):
    """/giveaway でリアクション抽選のギブアウェイを開催する機能"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.checker.start()

    def cog_unload(self):
        self.checker.cancel()

    @app_commands.command(name="giveaway", description="ギブアウェイ(景品抽選)を開催します")
    @app_commands.describe(prize="景品の内容", minutes="何分後に抽選するか", winners="当選者数")
    @is_manage_guild()
    async def giveaway(self, interaction: discord.Interaction, prize: str, minutes: app_commands.Range[int, 1, 10080], winners: app_commands.Range[int, 1, 20] = 1):
        end_time = time.time() + minutes * 60
        embed = discord.Embed(
            title="🎉 ギブアウェイ開催中！",
            description=f"**景品:** {prize}\n**当選者数:** {winners}人\n**終了:** <t:{int(end_time)}:R>\n\n{GIVEAWAY_EMOJI} のリアクションで応募できます！",
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"主催: {interaction.user}")
        await interaction.response.send_message(embed=embed)
        sent = await interaction.original_response()
        await sent.add_reaction(GIVEAWAY_EMOJI)

        giveaway_id = await self.bot.db.create_giveaway(
            interaction.guild_id, interaction.channel_id, prize, winners, interaction.user.id, end_time
        )
        await self.bot.db.set_giveaway_message(giveaway_id, sent.id)

    @app_commands.command(name="giveaway-end", description="ギブアウェイを今すぐ終了して抽選します")
    @app_commands.describe(message_id="ギブアウェイメッセージのID")
    @is_manage_guild()
    async def giveaway_end(self, interaction: discord.Interaction, message_id: str):
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("メッセージIDは数字で入力してください。", ephemeral=True)
            return
        row = await self.bot.db.get_giveaway_by_message(mid)
        if not row:
            await interaction.response.send_message("対象のギブアウェイが見つかりませんでした。", ephemeral=True)
            return
        await self._draw(row)
        await self.bot.db.mark_giveaway_ended(row["id"])
        await interaction.response.send_message("✅ ギブアウェイを終了し、抽選しました。", ephemeral=True)

    @tasks.loop(seconds=30)
    async def checker(self):
        rows = await self.bot.db.get_due_giveaways(time.time())
        for row in rows:
            await self._draw(row)
            await self.bot.db.mark_giveaway_ended(row["id"])

    @checker.before_loop
    async def before_checker(self):
        await self.bot.wait_until_ready()

    async def _draw(self, row):
        guild = self.bot.get_guild(row["guild_id"])
        if not guild:
            return
        channel = guild.get_channel(row["channel_id"])
        if not channel or not row["message_id"]:
            return
        try:
            message = await channel.fetch_message(row["message_id"])
        except discord.HTTPException:
            return

        entrants = []
        for reaction in message.reactions:
            if str(reaction.emoji) == GIVEAWAY_EMOJI:
                async for user in reaction.users():
                    if not user.bot:
                        entrants.append(user)
                break

        if not entrants:
            result_embed = discord.Embed(title="🎉 ギブアウェイ終了", description="応募者がいなかったため、当選者はいません。", color=discord.Color.dark_grey())
            await channel.send(embed=result_embed)
            return

        winners_count = min(row["winners_count"], len(entrants))
        winners = random.sample(entrants, winners_count)
        mentions = ", ".join(w.mention for w in winners)

        result_embed = discord.Embed(
            title="🎉 ギブアウェイ終了！",
            description=f"**景品:** {row['prize']}\n**当選者:** {mentions}",
            color=discord.Color.gold(),
        )
        await channel.send(content=mentions, embed=result_embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Giveaway(bot))
