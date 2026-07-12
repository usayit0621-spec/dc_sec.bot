import re
import time
import datetime
import collections

import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import is_admin, is_manage_guild

INVITE_RE = re.compile(r"(discord\.gg/|discord(?:app)?\.com/invite/)[a-zA-Z0-9-]+", re.IGNORECASE)

# よく使われるフィッシング/詐欺サイトの典型的なドメインパターン(なりすまし目的の偽ドメイン)
PHISHING_RE = re.compile(
    r"(discocl|dlscord|discrod|dicsord|discordn[il]tro|discord-nitro\.|steamcommunlty|steancommunity|"
    r"discord-gift|free-nitro|nitro-generator|steamgift[s]?\.(ru|xyz|top|club))",
    re.IGNORECASE,
)


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
        anti_alt="作成されたばかりのアカウント(捨てアカウント)の参加を制限するか",
        min_account_age_hours="参加を許可する最低アカウント作成経過時間(時間)",
        word_filter="NGワードフィルターを有効にするか",
        anti_phishing="既知のフィッシング/詐欺リンクパターンを自動削除するか",
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
        anti_alt: bool = False,
        min_account_age_hours: app_commands.Range[int, 0, 720] = 24,
        word_filter: bool = False,
        anti_phishing: bool = True,
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
            anti_alt_enabled=int(anti_alt),
            min_account_age_hours=min_account_age_hours,
            word_filter_enabled=int(word_filter),
            anti_phishing_enabled=int(anti_phishing),
        )
        embed = discord.Embed(title="✅ セキュリティ設定を更新しました", color=discord.Color.green())
        embed.add_field(name="anti-mention-spam", value=str(anti_mention), inline=True)
        embed.add_field(name="mention上限", value=str(mention_limit), inline=True)
        embed.add_field(name="anti-invite", value=str(anti_invite), inline=True)
        embed.add_field(name="anti-spam(連投)", value=str(anti_spam), inline=True)
        embed.add_field(name="anti-raid", value=str(anti_raid), inline=True)
        embed.add_field(name="anti-nuke", value=str(anti_nuke), inline=True)
        embed.add_field(name="タイムアウト時間", value=f"{timeout_minutes}分", inline=True)
        embed.add_field(name="anti-alt(捨てアカ制限)", value=str(anti_alt), inline=True)
        embed.add_field(name="最低アカウント経過時間", value=f"{min_account_age_hours}時間", inline=True)
        embed.add_field(name="NGワードフィルター", value=str(word_filter), inline=True)
        embed.add_field(name="anti-phishing", value=str(anti_phishing), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @security.command(name="addword", description="NGワードフィルターに単語を追加します")
    @is_manage_guild()
    async def add_word(self, interaction: discord.Interaction, word: str):
        await self.bot.db.add_blacklist_word(interaction.guild_id, word)
        await interaction.response.send_message(f"✅ NGワードに `{word}` を追加しました。", ephemeral=True)

    @security.command(name="removeword", description="NGワードフィルターから単語を削除します")
    @is_manage_guild()
    async def remove_word(self, interaction: discord.Interaction, word: str):
        await self.bot.db.remove_blacklist_word(interaction.guild_id, word)
        await interaction.response.send_message(f"✅ NGワードから `{word}` を削除しました。", ephemeral=True)

    @security.command(name="wordlist", description="現在のNGワード一覧を表示します")
    @is_manage_guild()
    async def word_list(self, interaction: discord.Interaction):
        words = await self.bot.db.get_blacklist_words(interaction.guild_id)
        await interaction.response.send_message(
            "NGワード一覧: " + (", ".join(f"`{w}`" for w in words) if words else "なし"), ephemeral=True
        )

    @app_commands.command(name="lockdown", description="このチャンネルで@everyoneの発言を禁止します")
    @is_manage_guild()
    async def lockdown(self, interaction: discord.Interaction):
        channel = interaction.channel
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=f"{interaction.user} によるロックダウン")
        embed = discord.Embed(title="🔒 チャンネルをロックダウンしました", description=f"{channel.mention} での発言を一時的に禁止しました。", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="unlock", description="このチャンネルのロックダウンを解除します")
    @is_manage_guild()
    async def unlock(self, interaction: discord.Interaction):
        channel = interaction.channel
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = None
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=f"{interaction.user} によるロック解除")
        embed = discord.Embed(title="🔓 ロックダウンを解除しました", description=f"{channel.mention} での発言を再度許可しました。", color=discord.Color.green())
        await interaction.response.send_message(embed=embed)

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

        # --- anti phishing ---
        if config["anti_phishing_enabled"] and PHISHING_RE.search(message.content):
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            embed = discord.Embed(
                title="🎣 フィッシングリンクの疑いがあるメッセージを削除しました",
                description=f"{member.mention} が送信したメッセージに既知の詐欺サイトパターンが含まれていました。",
                color=discord.Color.red(),
            )
            await self.alert(message.guild, embed)
            return

        # --- NGワードフィルター ---
        if config["word_filter_enabled"]:
            words = await self.bot.db.get_blacklist_words(message.guild.id)
            lowered = message.content.lower()
            if any(w in lowered for w in words):
                try:
                    await message.delete()
                except discord.HTTPException:
                    pass
                embed = discord.Embed(
                    title="🚫 NGワードを検知して削除しました",
                    description=f"{member.mention} のメッセージにNGワードが含まれていました。",
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

    # ---------------- anti raid / anti alt ----------------
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        config = await self.get_config(member.guild.id)

        # --- anti alt(捨てアカウント制限) ---
        if config["anti_alt_enabled"]:
            age = discord.utils.utcnow() - member.created_at
            min_age = datetime.timedelta(hours=config["min_account_age_hours"])
            if age < min_age:
                try:
                    await member.kick(reason=f"anti-alt: アカウント作成から{config['min_account_age_hours']}時間未満")
                except discord.HTTPException:
                    pass
                embed = discord.Embed(
                    title="🚫 anti-alt: 新規アカウントの参加を拒否しました",
                    description=f"{member} (`{member.id}`) は作成から {age} しか経過していないためキックしました。",
                    color=discord.Color.red(),
                )
                await self.alert(member.guild, embed)
                return

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

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.abc.GuildChannel):
        await self._track_nuke_action(channel.guild, discord.AuditLogAction.webhook_create, None)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        await self._track_nuke_action(role.guild, discord.AuditLogAction.role_create, None)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        await self._track_nuke_action(channel.guild, discord.AuditLogAction.channel_create, None)


async def setup(bot: commands.Bot):
    await bot.add_cog(Security(bot))
