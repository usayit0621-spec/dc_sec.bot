import datetime

import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import is_manage_guild

DELETE_COLOR = discord.Color.red()
EDIT_COLOR = discord.Color.orange()
JOIN_COLOR = discord.Color.green()
LEAVE_COLOR = discord.Color.dark_grey()
MOD_COLOR = discord.Color.dark_red()
CHANNEL_COLOR = discord.Color.blue()
ROLE_COLOR = discord.Color.purple()
INVITE_COLOR = discord.Color.teal()
VOICE_COLOR = discord.Color.gold()


def ts(dt: datetime.datetime | None = None) -> str:
    dt = dt or datetime.datetime.now(datetime.timezone.utc)
    return f"<t:{int(dt.timestamp())}:F>"


class LoggingCog(commands.Cog):
    """従来のDiscord監査ログを強化した詳細ログ機能"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log_channels: dict[int, int] = {}
        self.invite_cache: dict[int, dict[str, int]] = {}  # guild_id -> {invite_code: uses}

    async def cog_load(self):
        rows = await self.bot.db.get_all_log_channels()
        for row in rows:
            self.log_channels[row["guild_id"]] = row["channel_id"]

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self._cache_invites(guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self._cache_invites(guild)

    async def _cache_invites(self, guild: discord.Guild):
        try:
            invites = await guild.invites()
            self.invite_cache[guild.id] = {inv.code: inv.uses or 0 for inv in invites}
        except discord.Forbidden:
            self.invite_cache[guild.id] = {}

    def get_log_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        cid = self.log_channels.get(guild.id)
        if not cid:
            return None
        return guild.get_channel(cid)

    async def send_log(self, guild: discord.Guild, embed: discord.Embed):
        channel = self.get_log_channel(guild)
        if channel is None:
            return
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    async def find_audit_actor(self, guild: discord.Guild, action: discord.AuditLogAction, target_id: int | None = None):
        """監査ログから直近の実行者を特定する（取得できない場合はNone）"""
        try:
            async for entry in guild.audit_logs(action=action, limit=5):
                if target_id is None or (entry.target and getattr(entry.target, "id", None) == target_id):
                    delta = datetime.datetime.now(datetime.timezone.utc) - entry.created_at
                    if delta.total_seconds() < 15:
                        return entry
        except discord.Forbidden:
            return None
        return None

    # ---------------- setup command ----------------
    @app_commands.command(name="log", description="監査ログ・メッセージ削除/編集などを記録するチャンネルを設定します")
    @app_commands.describe(ch="ログを記録するチャンネル")
    @is_manage_guild()
    async def log_setup(self, interaction: discord.Interaction, ch: discord.TextChannel):
        await self.bot.db.set_log_channel(interaction.guild_id, ch.id)
        self.log_channels[interaction.guild_id] = ch.id
        embed = discord.Embed(
            title="✅ ログチャンネルを設定しました",
            description=f"今後、このサーバーのログは {ch.mention} に送信されます。",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ---------------- message events ----------------
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild:
            return
        embed = discord.Embed(title="🗑️ メッセージが削除されました", color=DELETE_COLOR, timestamp=datetime.datetime.now(datetime.timezone.utc))
        embed.add_field(name="投稿者", value=f"{message.author.mention} (`{message.author.id}`)", inline=False)
        embed.add_field(name="チャンネル", value=message.channel.mention, inline=False)
        content = message.content or "(テキストなし / embedのみ)"
        embed.add_field(name="元のメッセージ内容", value=content[:1024], inline=False)
        if message.attachments:
            files = "\n".join(a.url for a in message.attachments[:5])
            embed.add_field(name="添付ファイル", value=files[:1024], inline=False)

        actor = await self.find_audit_actor(message.guild, discord.AuditLogAction.message_delete)
        if actor and actor.user:
            embed.add_field(name="削除実行者(推定)", value=f"{actor.user.mention}", inline=False)

        await self.send_log(message.guild, embed)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]):
        if not messages or not messages[0].guild:
            return
        guild = messages[0].guild
        channel = messages[0].channel
        embed = discord.Embed(
            title="🗑️ メッセージが一括削除されました",
            description=f"{channel.mention} で {len(messages)} 件のメッセージが削除されました。",
            color=DELETE_COLOR,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        await self.send_log(guild, embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not before.guild or before.author.bot:
            return
        if before.content == after.content:
            return
        embed = discord.Embed(title="✏️ メッセージが編集されました", color=EDIT_COLOR, timestamp=datetime.datetime.now(datetime.timezone.utc))
        embed.add_field(name="投稿者", value=f"{before.author.mention} (`{before.author.id}`)", inline=False)
        embed.add_field(name="チャンネル", value=before.channel.mention, inline=False)
        embed.add_field(name="編集前", value=(before.content or "(なし)")[:1024], inline=False)
        embed.add_field(name="編集後", value=(after.content or "(なし)")[:1024], inline=False)
        embed.add_field(name="ジャンプ", value=f"[メッセージへ移動]({after.jump_url})", inline=False)
        await self.send_log(before.guild, embed)

    # ---------------- member events ----------------
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        used_invite = None
        try:
            new_invites = await guild.invites()
            new_map = {inv.code: inv.uses or 0 for inv in new_invites}
            old_map = self.invite_cache.get(guild.id, {})
            for inv in new_invites:
                if new_map.get(inv.code, 0) > old_map.get(inv.code, 0):
                    used_invite = inv
                    break
            self.invite_cache[guild.id] = new_map
        except discord.Forbidden:
            pass

        embed = discord.Embed(title="📥 メンバーが参加しました", color=JOIN_COLOR, timestamp=datetime.datetime.now(datetime.timezone.utc))
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="ユーザー", value=f"{member.mention} (`{member.id}`)", inline=False)
        embed.add_field(name="アカウント作成日", value=ts(member.created_at), inline=False)
        embed.add_field(name="現在のメンバー数", value=str(guild.member_count), inline=False)
        if used_invite:
            inviter = used_invite.inviter.mention if used_invite.inviter else "不明"
            embed.add_field(
                name="使用された招待リンク",
                value=f"コード: `{used_invite.code}` / 招待者: {inviter} / 使用回数: {used_invite.uses}",
                inline=False,
            )
        else:
            embed.add_field(name="使用された招待リンク", value="特定できませんでした", inline=False)

        account_age = datetime.datetime.now(datetime.timezone.utc) - member.created_at
        if account_age.days < 7:
            embed.add_field(name="⚠️ 注意", value=f"アカウント作成から {account_age.days} 日と新しいアカウントです。", inline=False)
            embed.color = discord.Color.yellow()

        await self.send_log(guild, embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild = member.guild
        roles = [r.mention for r in member.roles if r != guild.default_role]
        embed = discord.Embed(title="📤 メンバーが退出しました", color=LEAVE_COLOR, timestamp=datetime.datetime.now(datetime.timezone.utc))
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="ユーザー", value=f"{member} (`{member.id}`)", inline=False)
        if member.joined_at:
            embed.add_field(name="参加日時", value=ts(member.joined_at), inline=False)
        embed.add_field(name="保持していたロール", value=", ".join(roles) if roles else "なし", inline=False)

        kick_entry = await self.find_audit_actor(guild, discord.AuditLogAction.kick, member.id)
        if kick_entry:
            embed.add_field(name="キックされた可能性", value=f"実行者: {kick_entry.user.mention} / 理由: {kick_entry.reason or 'なし'}", inline=False)
            embed.color = MOD_COLOR

        await self.send_log(guild, embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.abc.User):
        embed = discord.Embed(title="🔨 メンバーがBANされました", color=MOD_COLOR, timestamp=datetime.datetime.now(datetime.timezone.utc))
        embed.add_field(name="ユーザー", value=f"{user} (`{user.id}`)", inline=False)
        entry = await self.find_audit_actor(guild, discord.AuditLogAction.ban, user.id)
        if entry:
            embed.add_field(name="実行者", value=entry.user.mention, inline=False)
            embed.add_field(name="理由", value=entry.reason or "なし", inline=False)
        await self.send_log(guild, embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.abc.User):
        embed = discord.Embed(title="🕊️ BANが解除されました", color=discord.Color.green(), timestamp=datetime.datetime.now(datetime.timezone.utc))
        embed.add_field(name="ユーザー", value=f"{user} (`{user.id}`)", inline=False)
        entry = await self.find_audit_actor(guild, discord.AuditLogAction.unban, user.id)
        if entry:
            embed.add_field(name="実行者", value=entry.user.mention, inline=False)
        await self.send_log(guild, embed)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        guild = after.guild
        changes = []

        if before.nick != after.nick:
            changes.append(f"ニックネーム: `{before.nick}` → `{after.nick}`")

        before_roles = set(before.roles)
        after_roles = set(after.roles)
        added = after_roles - before_roles
        removed = before_roles - after_roles
        if added:
            changes.append("追加されたロール: " + ", ".join(r.mention for r in added))
        if removed:
            changes.append("削除されたロール: " + ", ".join(r.mention for r in removed))

        if before.timed_out_until != after.timed_out_until:
            if after.timed_out_until:
                changes.append(f"タイムアウト設定: {ts(after.timed_out_until)} まで")
            else:
                changes.append("タイムアウトが解除されました")

        if not changes:
            return

        embed = discord.Embed(title="🔧 メンバー情報が更新されました", color=discord.Color.blue(), timestamp=datetime.datetime.now(datetime.timezone.utc))
        embed.add_field(name="ユーザー", value=f"{after.mention} (`{after.id}`)", inline=False)
        embed.add_field(name="変更内容", value="\n".join(changes)[:1024], inline=False)

        entry = await self.find_audit_actor(guild, discord.AuditLogAction.member_role_update, after.id)
        if entry:
            embed.add_field(name="実行者", value=entry.user.mention, inline=False)

        await self.send_log(guild, embed)

    # ---------------- channel / role events ----------------
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        embed = discord.Embed(title="📁 チャンネルが作成されました", color=CHANNEL_COLOR, timestamp=datetime.datetime.now(datetime.timezone.utc))
        embed.add_field(name="チャンネル", value=f"{channel.mention if hasattr(channel, 'mention') else channel.name} (`{channel.id}`)", inline=False)
        entry = await self.find_audit_actor(channel.guild, discord.AuditLogAction.channel_create, channel.id)
        if entry:
            embed.add_field(name="実行者", value=entry.user.mention, inline=False)
        await self.send_log(channel.guild, embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        embed = discord.Embed(title="🗑️ チャンネルが削除されました", color=DELETE_COLOR, timestamp=datetime.datetime.now(datetime.timezone.utc))
        embed.add_field(name="チャンネル名", value=f"{channel.name} (`{channel.id}`)", inline=False)
        entry = await self.find_audit_actor(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
        if entry:
            embed.add_field(name="実行者", value=entry.user.mention, inline=False)
        await self.send_log(channel.guild, embed)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        changes = []
        if before.name != after.name:
            changes.append(f"名前: `{before.name}` → `{after.name}`")
        if isinstance(before, discord.TextChannel) and isinstance(after, discord.TextChannel):
            if before.topic != after.topic:
                changes.append(f"トピック変更")
            if before.slowmode_delay != after.slowmode_delay:
                changes.append(f"スロー モード: {before.slowmode_delay}秒 → {after.slowmode_delay}秒")
        if not changes:
            return
        embed = discord.Embed(title="🔧 チャンネルが更新されました", color=CHANNEL_COLOR, timestamp=datetime.datetime.now(datetime.timezone.utc))
        embed.add_field(name="チャンネル", value=after.mention if hasattr(after, "mention") else after.name, inline=False)
        embed.add_field(name="変更内容", value="\n".join(changes), inline=False)
        await self.send_log(after.guild, embed)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        embed = discord.Embed(title="✨ ロールが作成されました", color=ROLE_COLOR, timestamp=datetime.datetime.now(datetime.timezone.utc))
        embed.add_field(name="ロール", value=f"{role.mention} (`{role.id}`)", inline=False)
        await self.send_log(role.guild, embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        embed = discord.Embed(title="🗑️ ロールが削除されました", color=DELETE_COLOR, timestamp=datetime.datetime.now(datetime.timezone.utc))
        embed.add_field(name="ロール名", value=f"{role.name} (`{role.id}`)", inline=False)
        entry = await self.find_audit_actor(role.guild, discord.AuditLogAction.role_delete, role.id)
        if entry:
            embed.add_field(name="実行者", value=entry.user.mention, inline=False)
        await self.send_log(role.guild, embed)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        changes = []
        if before.name != after.name:
            changes.append(f"名前: `{before.name}` → `{after.name}`")
        if before.permissions != after.permissions:
            changes.append("権限が変更されました")
        if before.color != after.color:
            changes.append("色が変更されました")
        if not changes:
            return
        embed = discord.Embed(title="🔧 ロールが更新されました", color=ROLE_COLOR, timestamp=datetime.datetime.now(datetime.timezone.utc))
        embed.add_field(name="ロール", value=after.mention, inline=False)
        embed.add_field(name="変更内容", value="\n".join(changes), inline=False)
        await self.send_log(after.guild, embed)

    # ---------------- invite events ----------------
    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        embed = discord.Embed(title="🔗 招待リンクが作成されました", color=INVITE_COLOR, timestamp=datetime.datetime.now(datetime.timezone.utc))
        embed.add_field(name="コード", value=f"`{invite.code}`", inline=True)
        embed.add_field(name="作成者", value=invite.inviter.mention if invite.inviter else "不明", inline=True)
        embed.add_field(name="チャンネル", value=invite.channel.mention if invite.channel else "不明", inline=True)
        max_uses = invite.max_uses if invite.max_uses else "無制限"
        max_age = f"{invite.max_age}秒" if invite.max_age else "無期限"
        embed.add_field(name="最大使用回数", value=str(max_uses), inline=True)
        embed.add_field(name="有効期限", value=max_age, inline=True)
        if invite.guild:
            self.invite_cache.setdefault(invite.guild.id, {})[invite.code] = invite.uses or 0
            await self.send_log(invite.guild, embed)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        if not invite.guild:
            return
        embed = discord.Embed(title="🔗 招待リンクが削除されました", color=DELETE_COLOR, timestamp=datetime.datetime.now(datetime.timezone.utc))
        embed.add_field(name="コード", value=f"`{invite.code}`", inline=False)
        await self.send_log(invite.guild, embed)

    # ---------------- voice events ----------------
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        guild = member.guild
        if before.channel is None and after.channel is not None:
            embed = discord.Embed(title="🔊 ボイスチャンネルに参加", color=VOICE_COLOR, timestamp=datetime.datetime.now(datetime.timezone.utc))
            embed.description = f"{member.mention} が {after.channel.mention} に参加しました。"
            await self.send_log(guild, embed)
        elif before.channel is not None and after.channel is None:
            embed = discord.Embed(title="🔇 ボイスチャンネルから退出", color=VOICE_COLOR, timestamp=datetime.datetime.now(datetime.timezone.utc))
            embed.description = f"{member.mention} が {before.channel.mention} から退出しました。"
            await self.send_log(guild, embed)
        elif before.channel != after.channel and after.channel is not None:
            embed = discord.Embed(title="🔀 ボイスチャンネルを移動", color=VOICE_COLOR, timestamp=datetime.datetime.now(datetime.timezone.utc))
            embed.description = f"{member.mention} が {before.channel.mention} → {after.channel.mention} に移動しました。"
            await self.send_log(guild, embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(LoggingCog(bot))
