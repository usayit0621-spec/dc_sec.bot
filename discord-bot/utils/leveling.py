import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import is_manage_guild
from utils.leveling import apply_level_change
from utils.backup import upload_backup


class Leveling(commands.Cog):
    """レベル制度: /level-set /level-add /level-minus /levelup-ch /level /level-ranking"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="level-set", description="指定レベルに到達した際に自動付与するロールを設定します")
    @app_commands.describe(level="対応するレベルの数", role="そのレベルに達したときに自動付与するロール")
    @is_manage_guild()
    async def level_set(self, interaction: discord.Interaction, level: app_commands.Range[int, 1, 100000], role: discord.Role):
        await self.bot.db.set_level_reward(interaction.guild_id, level, role.id)
        embed = discord.Embed(
            title="✅ レベル報酬ロールを設定しました",
            description=f"レベル **{level}** に到達したメンバーへ自動的に {role.mention} を付与します。",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await upload_backup(self.bot)

    @app_commands.command(name="level-add", description="指定ユーザーにレベルを付与します")
    @app_commands.describe(user="付与するユーザー", count="付与するレベル数")
    @is_manage_guild()
    async def level_add(self, interaction: discord.Interaction, user: discord.Member, count: app_commands.Range[int, 1, 100000]):
        new_level = await apply_level_change(self.bot, interaction.guild, user, count)
        embed = discord.Embed(
            title="✅ レベルを付与しました",
            description=f"{user.mention} に **{count}** レベル付与しました。(現在のレベル: **{new_level}**)",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)
        await upload_backup(self.bot)

    @app_commands.command(name="level-minus", description="指定ユーザーのレベルを差し引きます")
    @app_commands.describe(user="差し引くユーザー", level="差し引くレベル数")
    @is_manage_guild()
    async def level_minus(self, interaction: discord.Interaction, user: discord.Member, level: app_commands.Range[int, 1, 100000]):
        new_level = await apply_level_change(self.bot, interaction.guild, user, -level)
        embed = discord.Embed(
            title="✅ レベルを差し引きました",
            description=f"{user.mention} から **{level}** レベル差し引きました。(現在のレベル: **{new_level}**)",
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed)
        await upload_backup(self.bot)

    @app_commands.command(name="levelup-ch", description="レベルアップ通知を送信するチャンネルを設定します")
    @app_commands.describe(ch="レベルアップしたことを通知するチャンネル")
    @is_manage_guild()
    async def levelup_ch(self, interaction: discord.Interaction, ch: discord.TextChannel):
        await self.bot.db.set_levelup_channel(interaction.guild_id, ch.id)
        embed = discord.Embed(
            title="✅ レベルアップ通知チャンネルを設定しました",
            description=f"今後、レベルアップ通知は {ch.mention} に送信されます。",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await upload_backup(self.bot)

    @app_commands.command(name="level", description="自分または指定したユーザーのレベルを確認します")
    @app_commands.describe(user="レベルを確認したいユーザー(任意、未指定なら自分)")
    async def level(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user
        current_level = await self.bot.db.get_level(interaction.guild_id, target.id)
        embed = discord.Embed(
            title=f"📊 {target.display_name} のレベル",
            description=f"現在のレベル: **{current_level}**",
            color=target.color if target.color.value else discord.Color.blurple(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="level-ranking", description="現在のレベルランキング上位10名を表示します")
    async def level_ranking(self, interaction: discord.Interaction):
        rows = await self.bot.db.get_top_levels(interaction.guild_id, limit=10)
        if not rows:
            await interaction.response.send_message("まだレベルデータがありません。", ephemeral=False)
            return

        medal = ["🥇", "🥈", "🥉"]
        lines = []
        for i, row in enumerate(rows):
            rank_label = medal[i] if i < 3 else f"**{i + 1}位**"
            lines.append(f"{rank_label} <@{row['user_id']}> ー レベル **{row['level']}**")

        embed = discord.Embed(
            title="🏆 レベルランキング TOP10",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(
            embed=embed, allowed_mentions=discord.AllowedMentions.none()
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Leveling(bot))
