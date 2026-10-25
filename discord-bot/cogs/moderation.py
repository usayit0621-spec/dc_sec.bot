import datetime
import re

import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import (
    DANGER_COLOR,
    JST_EMBED_COLOR,
    SUCCESS_COLOR,
    WARN_COLOR,
    can_assign_role,
    can_manage_bot,
    can_manage_mods,
    ensure_mod_access,
    ensure_owner_access,
    has_mod_access,
    has_owner_access,
)


class Moderation(commands.Cog):
    """kick/ban/timeout/warn/purge と bot 権限設定"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _guild_cfg(self, guild: discord.Guild):
        return self.bot.guild_config.setdefault(str(guild.id), {})

    async def _can_target(self, executor: discord.Member, target: discord.Member):
        if executor.id == self.bot.user.id:
            return True
        if target.id == executor.guild.owner_id:
            return False
        if target.id == self.bot.user.id:
            return False
        if target.top_role >= executor.top_role and executor.id != executor.guild.owner_id:
            return False
        if target.top_role >= executor.guild.me.top_role and executor.id != executor.guild.owner_id:
            return False
        return True

    async def _can_manage_member(self, user: discord.Member, target: discord.Member, guild: discord.Guild):
        if user.id == guild.owner_id:
            return True
        if await has_owner_access(self.bot, guild, user):
            return True
        if await has_mod_access(self.bot, guild, user):
            if await self._can_target(user, target):
                return True
        return False

    async def _target_member(self, interaction: discord.Interaction, member: discord.Member):
        if not await self._can_manage_member(interaction.user, member, interaction.guild):
            raise app_commands.CheckFailure("このユーザーを管理できません。")
        return True

    @app_commands.group(name="mod")
    async def mod_group(self, interaction: discord.Interaction):
        """モデレーション関連コマンド"""
        pass

    @mod_group.command(name="role")
    @app_commands.describe(role="モデレーターロール")
    async def mod_role(self, interaction: discord.Interaction, role: discord.Role):
        """モデレーターロールを設定する"""
        await ensure_owner_access(interaction)
        guild_cfg = await self._guild_cfg(interaction.guild)
        if guild_cfg.get("owner_role_locked") and guild_cfg.get("owner_role_id"):
            if interaction.user.id != guild_cfg.get("owner_user_id"):
                await interaction.response.send_message("オーナーロールがロックされているため、モデレーターロールは変更できません。", ephemeral=True)
                return
        guild_cfg["mod_role_id"] = role.id
        await interaction.response.send_message(f"モデレーターロールを {role.mention} に設定しました。", ephemeral=True)

    @app_commands.group(name="owner")
    async def owner_group(self, interaction: discord.Interaction):
        """オーナー設定"""
        pass

    @owner_group.command(name="role")
    @app_commands.describe(role="オーナーロール")
    async def owner_role(self, interaction: discord.Interaction, role: discord.Role):
        """オーナーロールを設定する"""
        guild_cfg = await self._guild_cfg(interaction.guild)
        if guild_cfg.get("owner_role_id") and guild_cfg.get("owner_role_locked"):
            if interaction.user.id != guild_cfg.get("owner_user_id"):
                await interaction.response.send_message("オーナーロールはロックされているため、変更できません。", ephemeral=True)
                return
        if interaction.user.id != guild_cfg.get("owner_user_id") and interaction.user.id != interaction.guild.owner_id:
            if not await has_owner_access(interaction.client, interaction.guild, interaction.user):
                await interaction.response.send_message("オーナーロールを変更できるのは、ボット追加者またはサーバーオーナーのみです。", ephemeral=True)
                return
        guild_cfg["owner_role_id"] = role.id
        guild_cfg["owner_role_locked"] = True
        guild_cfg["owner_user_id"] = interaction.user.id
        await interaction.response.send_message(f"オーナーロールを {role.mention} に設定し、ロックしました。", ephemeral=True)

    @app_commands.command(name="help")
    async def slash_help(self, interaction: discord.Interaction):
        """利用可能なコマンドの一覧を表示"""
        await self._send_help(interaction)

    async def _send_help(self, interaction_or_ctx):
        guild = interaction_or_ctx.guild
        user = interaction_or_ctx.user if hasattr(interaction_or_ctx, "user") else interaction_or_ctx.author
        is_owner = await has_owner_access(self.bot, guild, user)
        is_mod = await has_mod_access(self.bot, guild, user)

        lines = [
            "`d?help` / `d?ban` / `d?mute` / `d?kick`",
            "`d?b` / `d?m` / `d?k` で省略コマンドも使えます",
            "`d!kick` / `d!k` でもキック可能です",
            "`/mod role` でモデレーターロール設定",
            "`/owner role` でオーナーロール設定",
            "`/rolepanel` でロールパネル設定",
            "`/reaction-role add` でリアクションロール設定",
        ]
        if is_owner or is_mod:
            lines.append("モデレーションコマンドが利用可能です。")
        else:
            lines.append("通常閲覧のみです。")

        content = "\n".join(lines)
        if hasattr(interaction_or_ctx, "response"):
            await interaction_or_ctx.response.send_message(content, ephemeral=True)
        else:
            await interaction_or_ctx.send(content)

    @app_commands.command(name="rolepanel")
    @app_commands.describe(message_id="対象メッセージID", emoji="絵文字", role="付与するロール")
    async def rolepanel(self, interaction: discord.Interaction, message_id: str, emoji: str, role: discord.Role):
        """リアクションロールのパネル候補を設定する"""
        await ensure_mod_access(interaction)
        if not await can_assign_role(interaction.client, interaction.guild, interaction.user, role):
            await interaction.response.send_message("そのロールは付与できません。対象ロールが自分より上位またはボットの上位ロールに近すぎます。", ephemeral=True)
            return
        cfg = await self._guild_cfg(interaction.guild)
        cfg.setdefault("rolepanels", {})
        cfg["rolepanels"][message_id] = {"emoji": emoji, "role_id": role.id}
        await interaction.response.send_message(f"メッセージ `{message_id}` に対して `{emoji}` で {role.mention} を付与する設定を保存しました。", ephemeral=True)

    @app_commands.command(name="ban")
    @app_commands.describe(member="対象ユーザー", reason="理由")
    async def slash_ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "理由なし"):
        """メンバーをBANする"""
        await ensure_mod_access(interaction)
        if not await self._can_manage_member(interaction.user, member, interaction.guild):
            await interaction.response.send_message("このユーザーをBANできません。", ephemeral=True)
            return
        await member.ban(reason=reason)
        await interaction.response.send_message(f"{member.mention} をBANしました。理由: {reason}", ephemeral=False)

    @app_commands.command(name="kick")
    @app_commands.describe(member="対象ユーザー", reason="理由")
    async def slash_kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "理由なし"):
        """メンバーをキックする"""
        await ensure_mod_access(interaction)
        if not await self._can_manage_member(interaction.user, member, interaction.guild):
            await interaction.response.send_message("このユーザーをキックできません。", ephemeral=True)
            return
        await member.kick(reason=reason)
        await interaction.response.send_message(f"{member.mention} をキックしました。理由: {reason}", ephemeral=False)

    @app_commands.command(name="mute")
    @app_commands.describe(member="対象ユーザー", minutes="ミュート時間（分）", reason="理由")
    async def slash_mute(self, interaction: discord.Interaction, member: discord.Member, minutes: int = 10, reason: str = "理由なし"):
        """メンバーをタイムアウトする"""
        await ensure_mod_access(interaction)
        if not await self._can_manage_member(interaction.user, member, interaction.guild):
            await interaction.response.send_message("このユーザーをミュートできません。", ephemeral=True)
            return
        timeout = datetime.timedelta(minutes=max(1, min(minutes, 40320)))
        await member.timeout(timeout, reason=reason)
        await interaction.response.send_message(f"{member.mention} を {minutes} 分タイムアウトしました。理由: {reason}", ephemeral=False)

    @commands.command(name="help", aliases=["h"])
    async def prefix_help(self, ctx: commands.Context):
        await self._send_help(ctx)

    @commands.command(name="ban", aliases=["b"])
    async def prefix_ban(self, ctx: commands.Context, member: discord.Member, *, reason: str = "理由なし"):
        if not await has_mod_access(self.bot, ctx.guild, ctx.author):
            await ctx.send("このコマンドを実行できる権限がありません。")
            return
        if not await self._can_manage_member(ctx.author, member, ctx.guild):
            await ctx.send("このユーザーをBANできません。")
            return
        await member.ban(reason=reason)
        await ctx.send(f"{member.mention} をBANしました。理由: {reason}")

    @commands.command(name="kick", aliases=["k"])
    async def prefix_kick(self, ctx: commands.Context, member: discord.Member, *, reason: str = "理由なし"):
        if not await has_mod_access(self.bot, ctx.guild, ctx.author):
            await ctx.send("このコマンドを実行できる権限がありません。")
            return
        if not await self._can_manage_member(ctx.author, member, ctx.guild):
            await ctx.send("このユーザーをキックできません。")
            return
        await member.kick(reason=reason)
        await ctx.send(f"{member.mention} をキックしました。理由: {reason}")

    @commands.command(name="mute", aliases=["m"])
    async def prefix_mute(self, ctx: commands.Context, member: discord.Member, minutes: int = 10, *, reason: str = "理由なし"):
        if not await has_mod_access(self.bot, ctx.guild, ctx.author):
            await ctx.send("このコマンドを実行できる権限がありません。")
            return
        if not await self._can_manage_member(ctx.author, member, ctx.guild):
            await ctx.send("このユーザーをミュートできません。")
            return
        timeout = datetime.timedelta(minutes=max(1, min(minutes, 40320)))
        await member.timeout(timeout, reason=reason)
        await ctx.send(f"{member.mention} を {minutes} 分タイムアウトしました。理由: {reason}")

    @commands.command(name="mute", aliases=["m"])
    async def prefix_mute_legacy(self, ctx: commands.Context, member: discord.Member, minutes: int = 10, *, reason: str = "理由なし"):
        await self.prefix_mute(ctx, member, minutes, reason)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
