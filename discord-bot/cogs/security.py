import re
import time
import datetime
import collections

import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import is_admin, is_manage_guild

INVITE_RE = re.compile(r"(discord\.gg/|discord(?:app)?\.com/invite/)[a-zA-Z0-9-]+", re.IGNORECASE)


class Security(commands.Cog):
    """anti-mention-spam / anti-invite / anti-spam(flood) / anti-raid / anti-nuke などのセキュリティ機能"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.msg_history: dict[int, collections.deque] = collections.defaultdict(lambda: collections.deque(maxlen=20))
        self.join_history: dict[int, collections.deque] = collections.defaultdict(lambda: collections.deque(maxlen=50))
        self.nuke_history: dict[int, collections.deque] = collections.defaultdict(lambda: collections.deque(maxlen=20))
        self._config_cache: dict[int, dict] = {}

    async def get_config(self, guild_id: int):
        row = await self.bot.db.get_automod(guild_id)
        return row

    async def get_log_channel(self, guild: discord.Guild):
        logging_cog = self.bot.get_cog("LoggingCog")
        if logging_cog:
            return logging_cog.get_log_channel(guild)
        return None

    async def alert(self, guild: discord.Guild, embed: discord.Embed):
        channel = await self.get_log_channel(guild)
        if channel:
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass

    # ---------------- setup / config commands ----------------
    security = app_commands.Group(name="security", description="セキュリティ機能の設定")

    @security.command(name="setup", description="セキュリティ機能をまとめて設定します")
    @app_commands.describe(
        anti_mention="メンションスパム対策を有効にするか",
        mention_limit="1メッセージあたりの許容メンション数",
        anti_invite="他サーバーへの招待リンク投稿を自動削除するか",
        anti_spam="連投(荒らし)対策を有効にするか",
        anti_raid="大量参加(荒らし)対策を有効にするか",
        anti_nuke="チャンネル/ロール大量削除対策を有効にするか",
        timeout_minutes="違反時にタイムアウトする分数",
    )
    @is_admin()
    async def security_setup(
        self,
        interaction: discord.Interaction,
        anti_mention: bool = True,
        mention_limit: app_commands.Range[int, 1, 30] = 5,
        anti_invite: bool = False,
        anti_spam: bool = True,
        anti_raid: bool = True,
        anti_nuke: bool = True,
        timeout_minutes: app_commands.Range[int, 1, 1440] = 10,
    ):
        await self.bot.db.update_automod(
            interaction.guild_id,
            anti_mention_enabled=int(anti_mention),
            mention_limit=mention_limit,
            anti_invite_enabled=int(anti_invite),
            anti_spam_enabled=int(anti_spam),
            anti_raid_enabled=int(anti_raid),
            anti_nuke_enabled=int(anti_nuke),
            timeout_minutes=timeout_minutes,
        )
        embed = discord.Embed(title="✅ セキュリティ設定を更新しました", color=discord.Color.green())
        embed.add_field(name="anti-mention-spam", value=str(anti_mention), inline=True)
        embed.add_field(name="mention上限", value=str(mention_limit), inline=True)
        embed.add_field(name="anti-invite", value=str(anti_invite), inline=True)
        embed.add_field(name="anti-spam(連投)", value=str(anti_spam), inline=True)
        embed.add_field(name="anti-raid", value=str(anti_raid), inline=True)
        embed.add_field(name="anti-nuke", value=str(anti_nuke), inline=True)
        embed.add_field(name="タイムアウト時間", value=f"{timeout_minutes}分", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @security.command(name="whitelist-add", description="anti-nuke対策の対象外にするユーザーを追加します")
    @is_admin()
    async def whitelist_add(self, interaction: discord.Interaction, user: discord.Member):
        await self.bot.db.add_whitelist(interaction.guild_id, user.id)
        await interaction.response.send_message(f"✅ {user.mention} をホワイトリストに追加しました。", ephemeral=True)

    @security.command(name="whitelist-remove", description="anti-nuke対策のホワイトリストからユーザーを削除します")
    @is_admin()
    async def whitelist_remove(self, interaction: discord.Interaction, user: discord.Member):
        await self.bot.db.remove_whitelist(interaction.guild_id, user.id)
        await interaction.response.send_message(f"✅ {user.mention} をホワイトリストから削除しました。", ephemeral=True)

    # ---------------- message-based protections ----------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        member = message.author
        if isinstance(member, discord.Member) and member.guild_permissions.administrator:
            return

        config = await self.get_config(message.guild.id)

        # --- anti mention spam ---
        if config["anti_mention_enabled"]:
            mention_count = len(message.mentions) + len(message.role_mentions)
            if mention_count >= config["mention_limit"]:
                await self._punish(message, "メンションスパムを検知しました", config["timeout_minutes"])
                return

        # --- anti invite link ---
        if config["anti_invite_enabled"] and INVITE_RE.search(message.content):
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            embed = discord.Embed(
                title="🚫 招待リンクを検知して削除しました",
                description=f"{member.mention} が招待リンクを投稿しました。",
                color=discord.Color.red(),
            )
            await self.alert(message.guild, embed)
            return

        # --- anti spam (flood) ---
        if config["anti_spam_enabled"]:
            dq = self.msg_history[member.id]
            dq.append(time.time())
            window_start = time.time() - config["spam_seconds"]
            recent = [t for t in dq if t >= window_start]
            if len(recent) >= config["spam_count"]:
                await self._punish(message, "メッセージ連投(スパム)を検知しました", config["timeout_minutes"])
                dq.clear()
                return

    async def _punish(self, message: discord.Message, reason: str, timeout_minutes: int):
        member = message.author
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        try:
            until = discord.utils.utcnow() + datetime.timedelta(minutes=timeout_minutes)
            await member.timeout(until, reason=reason)
        except discord.HTTPException:
            pass

        embed = discord.Embed(title="🛡️ 自動モデレーション", description=reason, color=discord.Color.red())
        embed.add_field(name="対象ユーザー", value=f"{member.mention} (`{member.id}`)", inline=False)
        embed.add_field(name="処置", value=f"{timeout_minutes}分間のタイムアウト", inline=False)
        await self.alert(message.guild, embed)

    # ---------------- anti raid ----------------
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        config = await self.get_config(member.guild.id)
        if not config["anti_raid_enabled"]:
            return

        dq = self.join_history[member.guild.id]
        dq.append(time.time())
        window_start = time.time() - config["raid_seconds"]
        recent = [t for t in dq if t >= window_start]

        if len(recent) >= config["raid_join_count"]:
            embed = discord.Embed(
                title="🚨 大量参加(レイド)を検知しました",
                description=(
                    f"直近 {config['raid_seconds']} 秒間に {len(recent)} 人が参加しました。\n"
                    "サーバーの認証レベルを一時的に引き上げることを検討してください。"
                ),
                color=discord.Color.dark_red(),
            )
            await self.alert(member.guild, embed)
            try:
                if member.guild.verification_level != discord.VerificationLevel.high:
                    await member.guild.edit(verification_level=discord.VerificationLevel.high, reason="anti-raid自動発動")
            except discord.HTTPException:
                pass

    # ---------------- anti nuke ----------------
    async def _track_nuke_action(self, guild: discord.Guild, action: discord.AuditLogAction, actor_target_check):
        config = await self.get_config(guild.id)
        if not config["anti_nuke_enabled"]:
            return
        try:
            async for entry in guild.audit_logs(action=action, limit=1):
                delta = datetime.datetime.now(datetime.timezone.utc) - entry.created_at
                if delta.total_seconds() > 10:
                    return
                actor = entry.user
                if actor is None or actor.id == guild.owner_id or actor.bot:
                    return
                if await self.bot.db.is_whitelisted(guild.id, actor.id):
                    return

                dq = self.nuke_history[actor.id]
                dq.append(time.time())
                recent = [t for t in dq if t >= time.time() - 60]

                if len(recent) >= config["nuke_threshold"]:
                    member = guild.get_member(actor.id)
                    embed = discord.Embed(
                        title="🚨 anti-nuke作動",
                        description=f"{actor.mention} が短時間に破壊的操作を繰り返したため、対処しました。",
                        color=discord.Color.dark_red(),
                    )
                    await self.alert(guild, embed)
                    if member:
                        try:
                            await guild.ban(member, reason="anti-nuke: 短時間に大量の破壊的操作を検知")
                        except discord.HTTPException:
                            try:
                                roles_to_remove = [r for r in member.roles if r != guild.default_role]
                                await member.remove_roles(*roles_to_remove, reason="anti-nuke")
                            except discord.HTTPException:
                                pass
        except discord.Forbidden:
            return

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        await self._track_nuke_action(channel.guild, discord.AuditLogAction.channel_delete, None)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        await self._track_nuke_action(role.guild, discord.AuditLogAction.role_delete, None)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.abc.User):
        await self._track_nuke_action(guild, discord.AuditLogAction.ban, None)


async def setup(bot: commands.Bot):
    await bot.add_cog(Security(bot))
