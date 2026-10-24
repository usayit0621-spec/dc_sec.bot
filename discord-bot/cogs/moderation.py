import datetime

import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import can_assign_role, command_access_list, ensure_mod_access, ensure_owner_access, has_mod_access, has_owner_access


class Moderation(commands.Cog):
    """kick/ban/timeout/warn/purge と bot 権限設定"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _help_list(self, guild: discord.Guild, user: discord.Member):
        access = await command_access_list(self.bot, guild, user)
        lines = [
            "Dc_Sec Bot ヘルプ",
            "- d?help / d!help: ヘルプ",
            "- d?ban / d?b: BAN",
            "- d?mute / d?m: タイムアウト",
            "- d?kick / d?k: キック",
        ]
        if "mod" in access:
            lines.append("- モデレーション権限あり: /kick /ban /timeout /warn /purge")
        if "owner" in access:
            lines.append("- オーナー権限あり: /mod role /owner role")
        return "\n".join(lines)

    @app_commands.group(name="mod", description="モデレーターロールの設定")
    async def mod_group(self, interaction: discord.Interaction):
        pass

    @mod_group.command(name="role", description="モデレーターロールを設定します")
    @app_commands.describe(role="モデレーターとして扱うロール")
    async def mod_role(self, interaction: discord.Interaction, role: discord.Role):
        await ensure_owner_access(interaction)
        access = await self.bot.db.get_guild_access(interaction.guild_id)
        if access and access["owner_role_id"] and access["owner_role_locked"] and interaction.user.id != access["created_by_user_id"]:
            await interaction.response.send_message("オーナーロールが既に固定されているため、追加者本人のみ変更できます。", ephemeral=True)
            return
        ok = await self.bot.db.set_mod_role(interaction.guild_id, role.id, interaction.user.id)
        if not ok:
            await interaction.response.send_message("モデレーターロール設定は追加者本人しか変更できません。", ephemeral=True)
            return
        await interaction.response.send_message(f"✅ モデレーターロールを {role.mention} に設定しました。", ephemeral=True)

    @app_commands.group(name="owner", description="オーナーロールの設定")
    async def owner_group(self, interaction: discord.Interaction):
        pass

    @owner_group.command(name="role", description="オーナーロールを設定します。設定後は追加者本人だけ変更可能です。")
    @app_commands.describe(role="オーナーとして扱うロール")
    async def owner_role(self, interaction: discord.Interaction, role: discord.Role):
        await ensure_owner_access(interaction)
        access = await self.bot.db.get_guild_access(interaction.guild_id)
        if access and access["owner_role_id"] and access["owner_role_locked"] and interaction.user.id != access["created_by_user_id"]:
            await interaction.response.send_message("オーナーロールは既に固定済みです。追加者本人のみ変更できます。", ephemeral=True)
            return
        ok = await self.bot.db.set_owner_role(interaction.guild_id, role.id, interaction.user.id)
        if not ok:
            await interaction.response.send_message("オーナーロールの再設定は追加者本人のみ可能です。", ephemeral=True)
            return
        await interaction.response.send_message(f"✅ オーナーロールを {role.mention} に設定しました。設定後は追加者本人のみ変更可能です。", ephemeral=True)

    @app_commands.command(name="help", description="このBotで使えるコマンド一覧を表示します")
    async def help_cmd(self, interaction: discord.Interaction):
        lines = await self._help_list(interaction.guild, interaction.user)
        await interaction.response.send_message(f"```\n{lines}\n```", ephemeral=True)

    @app_commands.command(name="kick", description="メンバーをキックします")
    @app_commands.describe(member="キックするメンバー", reason="理由")
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "理由なし"):
        if not await has_mod_access(self.bot, interaction.guild, interaction.user):
            raise app_commands.MissingPermissions(["mod_role_or_owner"])
        await member.kick(reason=f"{interaction.user} により実行: {reason}")
        embed = discord.Embed(title="👢 キックしました", color=discord.Color.orange())
        embed.add_field(name="対象", value=str(member), inline=True)
        embed.add_field(name="理由", value=reason, inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="ban", description="メンバーをBANします")
    @app_commands.describe(member="BANするメンバー", reason="理由", delete_days="遡って削除するメッセージの日数(0-7)")
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "理由なし", delete_days: app_commands.Range[int, 0, 7] = 0):
        if not await has_mod_access(self.bot, interaction.guild, interaction.user):
            raise app_commands.MissingPermissions(["mod_role_or_owner"])
        await member.ban(reason=f"{interaction.user} により実行: {reason}", delete_message_days=delete_days)
        embed = discord.Embed(title="🔨 BANしました", color=discord.Color.red())
        embed.add_field(name="対象", value=str(member), inline=True)
        embed.add_field(name="理由", value=reason, inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="unban", description="ユーザーIDを指定してBANを解除します")
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "理由なし"):
        if not await has_mod_access(self.bot, interaction.guild, interaction.user):
            raise app_commands.MissingPermissions(["mod_role_or_owner"])
        try:
            user = discord.Object(id=int(user_id))
            await interaction.guild.unban(user, reason=f"{interaction.user} により実行: {reason}")
            await interaction.response.send_message(f"✅ ID `{user_id}` のBANを解除しました。")
        except (ValueError, discord.NotFound):
            await interaction.response.send_message("そのユーザーIDのBANは見つかりませんでした。", ephemeral=True)

    @app_commands.command(name="timeout", description="メンバーを一時的にタイムアウトします")
    @app_commands.describe(member="対象メンバー", minutes="タイムアウトする分数", reason="理由")
    async def timeout_cmd(self, interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 40320], reason: str = "理由なし"):
        if not await has_mod_access(self.bot, interaction.guild, interaction.user):
            raise app_commands.MissingPermissions(["mod_role_or_owner"])
        until = discord.utils.utcnow() + datetime.timedelta(minutes=minutes)
        await member.timeout(until, reason=f"{interaction.user} により実行: {reason}")
        embed = discord.Embed(title="⏳ タイムアウトしました", color=discord.Color.orange())
        embed.add_field(name="対象", value=str(member), inline=True)
        embed.add_field(name="時間", value=f"{minutes}分", inline=True)
        embed.add_field(name="理由", value=reason, inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="untimeout", description="メンバーのタイムアウトを解除します")
    async def untimeout_cmd(self, interaction: discord.Interaction, member: discord.Member):
        if not await has_mod_access(self.bot, interaction.guild, interaction.user):
            raise app_commands.MissingPermissions(["mod_role_or_owner"])
        await member.timeout(None, reason=f"{interaction.user} により解除")
        await interaction.response.send_message(f"✅ {member.mention} のタイムアウトを解除しました。")

    @app_commands.command(name="warn", description="メンバーに警告を発行します")
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        if not await has_mod_access(self.bot, interaction.guild, interaction.user):
            raise app_commands.MissingPermissions(["mod_role_or_owner"])
        await self.bot.db.add_warning(interaction.guild_id, member.id, interaction.user.id, reason)
        rows = await self.bot.db.get_warnings(interaction.guild_id, member.id)
        embed = discord.Embed(title="⚠️ 警告を発行しました", color=discord.Color.yellow())
        embed.add_field(name="対象", value=str(member), inline=True)
        embed.add_field(name="累計警告数", value=str(len(rows)), inline=True)
        embed.add_field(name="理由", value=reason, inline=False)
        await interaction.response.send_message(embed=embed)
        try:
            await member.send(f"{interaction.guild.name} で警告を受けました。理由: {reason}")
        except discord.HTTPException:
            pass

    @app_commands.command(name="warnings", description="メンバーの警告履歴を表示します")
    async def warnings_cmd(self, interaction: discord.Interaction, member: discord.Member):
        if not await has_mod_access(self.bot, interaction.guild, interaction.user):
            raise app_commands.MissingPermissions(["mod_role_or_owner"])
        rows = await self.bot.db.get_warnings(interaction.guild_id, member.id)
        if not rows:
            await interaction.response.send_message("このメンバーに警告履歴はありません。", ephemeral=True)
            return
        embed = discord.Embed(title=f"⚠️ {member} の警告履歴", color=discord.Color.yellow())
        for row in rows[:15]:
            dt = datetime.datetime.fromtimestamp(row["timestamp"])
            embed.add_field(
                name=f"#{row['id']} - {dt.strftime('%Y-%m-%d %H:%M')}",
                value=f"理由: {row['reason']}\n実行者: <@{row['moderator_id']}>",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="clearwarnings", description="メンバーの警告履歴を全て削除します")
    async def clearwarnings(self, interaction: discord.Interaction, member: discord.Member):
        if not await has_mod_access(self.bot, interaction.guild, interaction.user):
            raise app_commands.MissingPermissions(["mod_role_or_owner"])
        await self.bot.db.clear_warnings(interaction.guild_id, member.id)
        await interaction.response.send_message(f"✅ {member.mention} の警告履歴を削除しました。", ephemeral=True)

    @app_commands.command(name="purge", description="指定件数のメッセージを一括削除します")
    @app_commands.describe(count="削除する件数(1-100)")
    async def purge(self, interaction: discord.Interaction, count: app_commands.Range[int, 1, 100]):
        if not await has_mod_access(self.bot, interaction.guild, interaction.user):
            raise app_commands.MissingPermissions(["mod_role_or_owner"])
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=count)
        await interaction.followup.send(f"✅ {len(deleted)} 件のメッセージを削除しました。", ephemeral=True)

    @app_commands.command(name="slowmode", description="このチャンネルのスローモードを設定します")
    @app_commands.describe(seconds="秒数(0で解除)")
    async def slowmode(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]):
        if not await has_mod_access(self.bot, interaction.guild, interaction.user):
            raise app_commands.MissingPermissions(["mod_role_or_owner"])
        await interaction.channel.edit(slowmode_delay=seconds)
        if seconds == 0:
            await interaction.response.send_message("✅ スローモードを解除しました。")
        else:
            await interaction.response.send_message(f"✅ スローモードを {seconds} 秒に設定しました。")

    @commands.command(name="help", aliases=["h"]) 
    async def prefix_help(self, ctx: commands.Context):
        access = await command_access_list(self.bot, ctx.guild, ctx.author)
        lines = [
            "Dc_Sec Bot ヘルプ",
            "- d?help / d!help: ヘルプ",
            "- d?ban / d?b: BAN",
            "- d?mute / d?m: タイムアウト",
            "- d?kick / d?k: キック",
        ]
        if "mod" in access:
            lines.append("- モデレーション権限あり: /kick /ban /timeout /warn /purge")
        if "owner" in access:
            lines.append("- オーナー権限あり: /mod role /owner role")
        await ctx.send("\n".join(lines))

    @commands.command(name="ban", aliases=["b"]) 
    async def prefix_ban(self, ctx: commands.Context, member: discord.Member, *, reason: str = "理由なし"):
        if not await has_mod_access(self.bot, ctx.guild, ctx.author):
            await ctx.send("このコマンドはモデレーターロールまたはオーナー権限が必要です。")
            return
        await member.ban(reason=f"{ctx.author} により実行: {reason}")
        await ctx.send(f"✅ {member.mention} をBANしました。理由: {reason}")

    @commands.command(name="mute", aliases=["m"]) 
    async def prefix_mute(self, ctx: commands.Context, member: discord.Member, minutes: int = 10, *, reason: str = "理由なし"):
        if not await has_mod_access(self.bot, ctx.guild, ctx.author):
            await ctx.send("このコマンドはモデレーターロールまたはオーナー権限が必要です。")
            return
        until = discord.utils.utcnow() + datetime.timedelta(minutes=minutes)
        await member.timeout(until, reason=f"{ctx.author} により実行: {reason}")
        await ctx.send(f"✅ {member.mention} を {minutes} 分タイムアウトしました。理由: {reason}")

    @commands.command(name="kick", aliases=["k"]) 
    async def prefix_kick(self, ctx: commands.Context, member: discord.Member, *, reason: str = "理由なし"):
        if not await has_mod_access(self.bot, ctx.guild, ctx.author):
            await ctx.send("このコマンドはモデレーターロールまたはオーナー権限が必要です。")
            return
        await member.kick(reason=f"{ctx.author} により実行: {reason}")
        await ctx.send(f"✅ {member.mention} をキックしました。理由: {reason}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
