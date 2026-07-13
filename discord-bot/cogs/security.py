import re
import time
import datetime
import collections

import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import is_admin, is_manage_guild
from utils.backup import upload_backup

INVITE_RE = re.compile(r"(discord\.gg/|discord(?:app)?\.com/invite/)[a-zA-Z0-9-]+", re.IGNORECASE)

# よく使われるフィッシング/詐欺サイトの典型的なドメインパターン(なりすまし目的の偽ドメイン)
PHISHING_RE = re.compile(
    r"(discocl|dlscord|discrod|dicsord|discordn[il]tro|discord-nitro\.|steamcommunlty|steancommunity|"
    r"discord-gift|free-nitro|nitro-generator|steamgift[s]?\.(ru|xyz|top|club)|"
    r"bit\.ly|tinyurl\.com|cutt\.ly|is\.gd|shorturl\.at|rb\.gy)",
    re.IGNORECASE,
)

URL_RE = re.compile(r"https?://([^\s/]+)", re.IGNORECASE)
ZALGO_RE = re.compile(r"[\u0300-\u036f\u1ab0-\u1aff\u1dc0-\u1dff\u20d0-\u20ff]")
CUSTOM_EMOJI_RE = re.compile(r"<a?:\w+:\d+>")
UNICODE_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")


class Security(commands.Cog):
    """anti-mention-spam / anti-invite / anti-spam(flood) / anti-raid / anti-nuke /
    anti-alt / anti-phishing / URL遮断 / 外部アプリ(User Install App含む)スパム対策 /
    NGワード / Zalgo対策 / 絵文字スパム / 権限昇格監視 / ストライク(累積タイムアウト→警告DM→BAN) など
    このBotひとつでサーバー運営のセキュリティ管理を完結させることを目指した総合防御機能"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.msg_history: dict[int, collections.deque] = collections.defaultdict(lambda: collections.deque(maxlen=20))
        self.app_msg_history: dict[int, collections.deque] = collections.defaultdict(lambda: collections.deque(maxlen=20))
        self.join_history: dict[int, collections.deque] = collections.defaultdict(lambda: collections.deque(maxlen=50))
        self.nuke_history: dict[int, collections.deque] = collections.defaultdict(lambda: collections.deque(maxlen=20))
        self.recent_content: dict[int, collections.deque] = collections.defaultdict(lambda: collections.deque(maxlen=6))

    # ---------------- 共通ヘルパー ----------------
    async def get_config(self, guild_id: int):
        return await self.bot.db.get_automod(guild_id)

    def get_log_channel(self, guild: discord.Guild):
        logging_cog = self.bot.get_cog("LoggingCog")
        if logging_cog:
            return logging_cog.get_log_channel(guild)
        return None

    async def alert(self, guild: discord.Guild, embed: discord.Embed):
        channel = self.get_log_channel(guild)
        if channel:
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass

    async def dm_owner(self, guild: discord.Guild, embed: discord.Embed):
        config = await self.get_config(guild.id)
        if not config["owner_dm_alerts"]:
            return
        owner = guild.owner
        if owner is None:
            try:
                owner = await guild.fetch_owner()
            except discord.HTTPException:
                return
        try:
            await owner.send(embed=embed)
        except discord.HTTPException:
            pass

    async def find_actor(self, guild: discord.Guild, action: discord.AuditLogAction, target_id: int | None = None):
        try:
            async for entry in guild.audit_logs(action=action, limit=5):
                if target_id is None or (entry.target and getattr(entry.target, "id", None) == target_id):
                    delta = datetime.datetime.now(datetime.timezone.utc) - entry.created_at
                    if delta.total_seconds() < 15:
                        return entry
        except discord.Forbidden:
            return None
        return None

    def get_interaction_user(self, message: discord.Message):
        """外部アプリ/Bot/User Install Appを実際にインストール・実行した人を特定する"""
        meta = getattr(message, "interaction_metadata", None)
        if meta is not None and getattr(meta, "user", None):
            return message.guild.get_member(meta.user.id) or meta.user
        legacy = getattr(message, "interaction", None)
        if legacy is not None and getattr(legacy, "user", None):
            return message.guild.get_member(legacy.user.id) or legacy.user
        return None

    # ---------------- コンテンツ判定ヘルパー ----------------
    def _is_caps(self, content: str, threshold: int) -> bool:
        letters = [c for c in content if c.isalpha()]
        if len(letters) < 10:
            return False
        upper = sum(1 for c in letters if c.isupper())
        return (upper / len(letters)) * 100 >= threshold

    def _emoji_count(self, content: str) -> int:
        return len(CUSTOM_EMOJI_RE.findall(content)) + len(UNICODE_EMOJI_RE.findall(content))

    def _is_zalgo(self, content: str) -> bool:
        return len(ZALGO_RE.findall(content)) >= 15

    def _check_duplicate(self, author_id: int, content: str, threshold: int) -> bool:
        if not content or threshold < 2:
            return False
        dq = self.recent_content[author_id]
        dq.append(content)
        if len(dq) < threshold:
            return False
        last_n = list(dq)[-threshold:]
        return len(set(last_n)) == 1

    async def _has_blocked_url(self, message: discord.Message) -> bool:
        matches = URL_RE.findall(message.content)
        if not matches:
            return False
        whitelist = await self.bot.db.get_url_whitelist(message.guild.id)
        for domain in matches:
            domain_l = domain.lower()
            if any(w in domain_l for w in whitelist):
                continue
            return True
        return False

    # ---------------- setup / config commands ----------------
    security = app_commands.Group(name="security", description="セキュリティ機能の設定")

    @security.command(name="setup", description="基本的なセキュリティ機能をまとめて設定します")
    @app_commands.describe(
        anti_mention="メンションスパム対策を有効にするか",
        mention_limit="1メッセージあたりの許容メンション数",
        anti_invite="他サーバーへの招待リンク投稿を自動削除するか",
        anti_spam="連投(荒らし)対策を有効にするか",
        anti_raid="大量参加(荒らし)対策を有効にするか",
        anti_nuke="チャンネル/ロール大量作成・削除対策を有効にするか",
        timeout_minutes="違反時にタイムアウトする分数",
        anti_alt="作成されたばかりのアカウント(捨てアカウント)の参加を制限するか",
        min_account_age_hours="参加を許可する最低アカウント作成経過時間(時間)",
        word_filter="NGワードフィルターを有効にするか",
        anti_phishing="既知のフィッシング/詐欺リンク・短縮URLを自動削除するか",
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
        embed = discord.Embed(title="✅ 基本セキュリティ設定を更新しました", color=discord.Color.green())
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
        embed.set_footer(text="さらに詳細な設定は /security setup-content と /security setup-advanced で行えます")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await upload_backup(self.bot)

    @security.command(name="setup-content", description="メッセージ内容に対するフィルター系のセキュリティ機能を設定します")
    @app_commands.describe(
        block_urls="URLリンクの投稿自体を一律ブロックするか(ホワイトリスト除く)",
        anti_caps="過度な大文字メッセージ(叫び)を自動削除するか",
        caps_threshold="大文字判定するパーセンテージ(10文字以上のメッセージが対象)",
        anti_emoji="絵文字の過剰投稿を自動削除するか",
        emoji_limit="1メッセージあたりの許容絵文字数",
        anti_duplicate="同一内容メッセージの連続投稿(コピペ荒らし)対策を有効にするか",
        zalgo_filter="Zalgo(結合文字を悪用した崩し文字)を自動削除するか",
        everyone_abuse="権限保持者を含め@everyone/@hereの濫用を検知するか(乗っ取り対策)",
    )
    @is_admin()
    async def security_setup_content(
        self,
        interaction: discord.Interaction,
        block_urls: bool = False,
        anti_caps: bool = False,
        caps_threshold: app_commands.Range[int, 30, 100] = 70,
        anti_emoji: bool = False,
        emoji_limit: app_commands.Range[int, 1, 50] = 10,
        anti_duplicate: bool = True,
        zalgo_filter: bool = True,
        everyone_abuse: bool = True,
    ):
        await self.bot.db.update_automod(
            interaction.guild_id,
            block_urls_enabled=int(block_urls),
            anti_caps_enabled=int(anti_caps),
            caps_threshold=caps_threshold,
            anti_emoji_enabled=int(anti_emoji),
            emoji_limit=emoji_limit,
            anti_duplicate_enabled=int(anti_duplicate),
            zalgo_filter_enabled=int(zalgo_filter),
            everyone_abuse_enabled=int(everyone_abuse),
        )
        embed = discord.Embed(title="✅ コンテンツフィルター設定を更新しました", color=discord.Color.green())
        embed.add_field(name="URL一律ブロック", value=str(block_urls), inline=True)
        embed.add_field(name="anti-caps", value=f"{anti_caps} ({caps_threshold}%)", inline=True)
        embed.add_field(name="anti-emoji", value=f"{anti_emoji} (上限{emoji_limit})", inline=True)
        embed.add_field(name="anti-duplicate", value=str(anti_duplicate), inline=True)
        embed.add_field(name="Zalgoフィルター", value=str(zalgo_filter), inline=True)
        embed.add_field(name="@everyone濫用検知(権限者含む)", value=str(everyone_abuse), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await upload_backup(self.bot)

    @security.command(name="setup-advanced", description="外部アプリ対策・権限昇格監視・ストライク制などの高度な設定を行います")
    @app_commands.describe(
        anti_perm_escalation="ロールへの管理者権限の不正付与を監視し自動で取り消すか",
        owner_dm_alerts="重大なセキュリティイベント発生時にサーバーオーナーへDM通知するか",
        app_spam="外部アプリ/Bot(User Install App含む)の連投スパムを検知するか",
        app_spam_count="外部アプリ/Botの連投とみなすメッセージ数",
        app_spam_seconds="↑を計測する秒数",
        strike_warn_threshold="スパム系タイムアウトが何回累積したら警告DMを送るか",
        strike_ban_threshold="スパム系タイムアウトが何回累積したら自動BANするか",
    )
    @is_admin()
    async def security_setup_advanced(
        self,
        interaction: discord.Interaction,
        anti_perm_escalation: bool = True,
        owner_dm_alerts: bool = True,
        app_spam: bool = True,
        app_spam_count: app_commands.Range[int, 2, 30] = 6,
        app_spam_seconds: app_commands.Range[int, 2, 60] = 8,
        strike_warn_threshold: app_commands.Range[int, 2, 50] = 9,
        strike_ban_threshold: app_commands.Range[int, 3, 50] = 10,
    ):
        await self.bot.db.update_automod(
            interaction.guild_id,
            anti_perm_escalation=int(anti_perm_escalation),
            owner_dm_alerts=int(owner_dm_alerts),
            app_spam_enabled=int(app_spam),
            app_spam_count=app_spam_count,
            app_spam_seconds=app_spam_seconds,
            strike_warn_threshold=strike_warn_threshold,
            strike_ban_threshold=strike_ban_threshold,
        )
        embed = discord.Embed(title="✅ 高度なセキュリティ設定を更新しました", color=discord.Color.green())
        embed.add_field(name="権限昇格自動監視", value=str(anti_perm_escalation), inline=True)
        embed.add_field(name="オーナーDM通知", value=str(owner_dm_alerts), inline=True)
        embed.add_field(name="外部アプリ/Botスパム対策", value=f"{app_spam} ({app_spam_count}件/{app_spam_seconds}秒)", inline=True)
        embed.add_field(name="警告DMを送るストライク数", value=str(strike_warn_threshold), inline=True)
        embed.add_field(name="自動BANするストライク数", value=str(strike_ban_threshold), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await upload_backup(self.bot)

    @security.command(name="addword", description="NGワードフィルターに単語を追加します")
    @is_manage_guild()
    async def add_word(self, interaction: discord.Interaction, word: str):
        await self.bot.db.add_blacklist_word(interaction.guild_id, word)
        await interaction.response.send_message(f"✅ NGワードに `{word}` を追加しました。", ephemeral=True)
        await upload_backup(self.bot)

    @security.command(name="removeword", description="NGワードフィルターから単語を削除します")
    @is_manage_guild()
    async def remove_word(self, interaction: discord.Interaction, word: str):
        await self.bot.db.remove_blacklist_word(interaction.guild_id, word)
        await interaction.response.send_message(f"✅ NGワードから `{word}` を削除しました。", ephemeral=True)
        await upload_backup(self.bot)

    @security.command(name="wordlist", description="現在のNGワード一覧を表示します")
    @is_manage_guild()
    async def word_list(self, interaction: discord.Interaction):
        words = await self.bot.db.get_blacklist_words(interaction.guild_id)
        await interaction.response.send_message(
            "NGワード一覧: " + (", ".join(f"`{w}`" for w in words) if words else "なし"), ephemeral=True
        )

    @security.command(name="urlwhitelist-add", description="URLブロックの対象外にするドメインを追加します")
    @app_commands.describe(domain="許可するドメイン(例: youtube.com)")
    @is_manage_guild()
    async def url_whitelist_add(self, interaction: discord.Interaction, domain: str):
        await self.bot.db.add_url_whitelist(interaction.guild_id, domain)
        await interaction.response.send_message(f"✅ `{domain}` をURLホワイトリストに追加しました。", ephemeral=True)
        await upload_backup(self.bot)

    @security.command(name="urlwhitelist-remove", description="URLブロックのホワイトリストからドメインを削除します")
    @is_manage_guild()
    async def url_whitelist_remove(self, interaction: discord.Interaction, domain: str):
        await self.bot.db.remove_url_whitelist(interaction.guild_id, domain)
        await interaction.response.send_message(f"✅ `{domain}` をURLホワイトリストから削除しました。", ephemeral=True)
        await upload_backup(self.bot)

    @security.command(name="strikes", description="指定ユーザーの累積スパムストライク数を確認します")
    @is_manage_guild()
    async def strikes(self, interaction: discord.Interaction, user: discord.Member):
        count = await self.bot.db.get_strikes(interaction.guild_id, user.id)
        await interaction.response.send_message(f"{user.mention} の累積ストライク: **{count}**", ephemeral=True)

    @security.command(name="strikes-reset", description="指定ユーザーの累積スパムストライクをリセットします")
    @is_manage_guild()
    async def strikes_reset(self, interaction: discord.Interaction, user: discord.Member):
        await self.bot.db.reset_strikes(interaction.guild_id, user.id)
        await interaction.response.send_message(f"✅ {user.mention} のストライクをリセットしました。", ephemeral=True)
        await upload_backup(self.bot)

    @security.command(name="whitelist-add", description="anti-nuke対策の対象外にするユーザーを追加します")
    @is_admin()
    async def whitelist_add(self, interaction: discord.Interaction, user: discord.Member):
        await self.bot.db.add_whitelist(interaction.guild_id, user.id)
        await interaction.response.send_message(f"✅ {user.mention} をホワイトリストに追加しました。", ephemeral=True)
        await upload_backup(self.bot)

    @security.command(name="whitelist-remove", description="anti-nuke対策のホワイトリストからユーザーを削除します")
    @is_admin()
    async def whitelist_remove(self, interaction: discord.Interaction, user: discord.Member):
        await self.bot.db.remove_whitelist(interaction.guild_id, user.id)
        await interaction.response.send_message(f"✅ {user.mention} をホワイトリストから削除しました。", ephemeral=True)
        await upload_backup(self.bot)

    @app_commands.command(name="bot-whitelist", description="指定Botを監視対象から除外します(リンク投稿・自由な入退室を許可)")
    @app_commands.describe(bot="監視対象から除外するBot")
    @is_admin()
    async def cmd_bot_whitelist(self, interaction: discord.Interaction, bot: discord.Member):
        if not bot.bot:
            await interaction.response.send_message("Botのみ指定できます。", ephemeral=True)
            return
        await self.bot.db.add_bot_whitelist(interaction.guild_id, bot.id)
        embed = discord.Embed(
            title="✅ Botを監視対象から除外しました",
            description=(
                f"{bot.mention} はNGワード・URL/招待リンク制限などの自動モデレーションの対象外になります。\n"
                "ただし全ての制限が解除されるわけではなく、大量投稿などの不自然な挙動を検知した場合は"
                "自動的にキックされます。"
            ),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await upload_backup(self.bot)

    @app_commands.command(name="bot-whitelist-remove", description="Botを監視除外リストから削除します")
    @app_commands.describe(bot="監視除外を解除するBot")
    @is_admin()
    async def cmd_bot_whitelist_remove(self, interaction: discord.Interaction, bot: discord.Member):
        await self.bot.db.remove_bot_whitelist(interaction.guild_id, bot.id)
        await interaction.response.send_message(f"✅ {bot.mention} の監視除外を解除しました。", ephemeral=True)
        await upload_backup(self.bot)

    @app_commands.command(name="channel-allowed", description="実行したチャンネルのリンク/URL監視をオフ・オンに切り替えます")
    @is_manage_guild()
    async def channel_allowed(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        channel_id = interaction.channel_id
        if await self.bot.db.is_channel_allowed(guild_id, channel_id):
            await self.bot.db.remove_channel_allowed(guild_id, channel_id)
            msg = f"✅ {interaction.channel.mention} のリンク監視を再度有効にしました。"
        else:
            await self.bot.db.add_channel_allowed(guild_id, channel_id)
            msg = f"✅ {interaction.channel.mention} ではリンク投稿などのURL関連監視をオフにしました(NGワード等の他フィルターは引き続き有効です)。"
        await interaction.response.send_message(msg, ephemeral=True)
        await upload_backup(self.bot)

    @app_commands.command(name="lockdown", description="このチャンネルで@everyoneの発言を禁止します")
    @is_manage_guild()
    async def lockdown(self, interaction: discord.Interaction):
        channel = interaction.channel
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=f"{interaction.user} によるロックダウン")
        embed = discord.Embed(title="🔒 チャンネルをロックダウンしました", description=f"{channel.mention} での発言を一時的に禁止しました。", color=discord.Color.dark_grey())
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

    @app_commands.command(name="lockdown-all", description="サーバー全体のテキストチャンネルをロックダウンします")
    @is_admin()
    async def lockdown_all(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        count = 0
        for ch in interaction.guild.text_channels:
            try:
                overwrite = ch.overwrites_for(interaction.guild.default_role)
                overwrite.send_messages = False
                await ch.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=f"{interaction.user} による緊急ロックダウン")
                count += 1
            except discord.HTTPException:
                continue
        await interaction.followup.send(f"🔒 {count} 個のチャンネルをロックダウンしました。", ephemeral=True)

    # ---------------- message-based protections ----------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.id == self.bot.user.id:
            return

        member = message.author
        is_app = member.bot
        config = await self.get_config(message.guild.id)
        is_privileged = isinstance(member, discord.Member) and member.guild_permissions.administrator
        is_bot_whitelisted = is_app and await self.bot.db.is_bot_whitelisted(message.guild.id, member.id)
        is_channel_allowed = await self.bot.db.is_channel_allowed(message.guild.id, message.channel.id)

        # --- @everyone/@here 濫用検知(権限保持者=乗っ取りアカウントも例外なく対象。監視除外Botのみ免除) ---
        if config["everyone_abuse_enabled"] and message.mention_everyone and not is_bot_whitelisted:
            await self._punish(message, "@everyone / @here の濫用を検知しました(権限保持アカウントの乗っ取りの可能性)", config["timeout_minutes"])
            return

        # --- メンションスパム(権限保持者も対象。乗っ取り対策。監視除外Botのみ免除) ---
        if config["anti_mention_enabled"] and not is_bot_whitelisted:
            mention_count = len(message.mentions) + len(message.role_mentions)
            if mention_count >= config["mention_limit"]:
                await self._punish(message, "メンションスパムを検知しました", config["timeout_minutes"])
                return

        # 以降のコンテンツフィルター(NGワード・URL系等)は
        # 管理者権限保持者 / 監視除外設定済みBot では免除する(誤検知防止)。
        # ただし監視除外Botであっても連投(フラッド)などの不自然な挙動の検知は継続し、
        # 検知した場合はキックする(下部の連投スパムチェックを参照)。
        if not (is_privileged or is_bot_whitelisted):
            # --- 招待リンク ---
            if config["anti_invite_enabled"] and not is_channel_allowed and INVITE_RE.search(message.content):
                await self._punish(message, "他サーバーへの招待リンク投稿を検知しました", config["timeout_minutes"])
                return

            # --- URL一律ブロック ---
            if config["block_urls_enabled"] and not is_channel_allowed and await self._has_blocked_url(message):
                await self._punish(message, "許可されていないURLリンクの投稿を検知しました", config["timeout_minutes"])
                return

            # --- フィッシング/詐欺サイト・短縮URL(これは常に検知、channel-allowedでも免除しない) ---
            if config["anti_phishing_enabled"] and PHISHING_RE.search(message.content):
                await self._punish(message, "フィッシング/詐欺サイトの疑いがあるリンクを検知しました", config["timeout_minutes"])
                return

            # --- Zalgo(崩し文字) ---
            if config["zalgo_filter_enabled"] and self._is_zalgo(message.content):
                await self._punish(message, "Zalgo(崩し文字)による荒らしを検知しました", config["timeout_minutes"])
                return

            # --- NGワード ---
            if config["word_filter_enabled"]:
                words = await self.bot.db.get_blacklist_words(message.guild.id)
                lowered = message.content.lower()
                if any(w in lowered for w in words):
                    await self._punish(message, "NGワードを検知しました", config["timeout_minutes"])
                    return

            # --- 大文字連打(叫び) ---
            if config["anti_caps_enabled"] and self._is_caps(message.content, config["caps_threshold"]):
                await self._punish(message, "過度な大文字メッセージを検知しました", config["timeout_minutes"])
                return

            # --- 絵文字スパム ---
            if config["anti_emoji_enabled"] and self._emoji_count(message.content) >= config["emoji_limit"]:
                await self._punish(message, "絵文字の過剰投稿を検知しました", config["timeout_minutes"])
                return

            # --- 同一内容の連続投稿(コピペ荒らし) ---
            if config["anti_duplicate_enabled"] and self._check_duplicate(member.id, message.content, 4):
                await self._punish(message, "同一内容メッセージの連続投稿(コピペ荒らし)を検知しました", config["timeout_minutes"])
                return

        # --- 連投(フラッド)スパム。人間と外部アプリ/Botで閾値を分ける。
        # 監視除外Botであってもこの異常挙動検知だけは免除しない(不自然な挙動を検知した場合は自動キック) ---
        if is_app:
            if config["app_spam_enabled"]:
                dq = self.app_msg_history[member.id]
                dq.append(time.time())
                window_start = time.time() - config["app_spam_seconds"]
                recent = [t for t in dq if t >= window_start]
                if len(recent) >= config["app_spam_count"]:
                    await self._punish(message, "外部アプリ/Bot(User Install App含む)によるスパム投稿を検知しました", config["timeout_minutes"])
                    dq.clear()
                    return
        else:
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
        guild = message.guild
        member = message.author
        invoking_user = self.get_interaction_user(message)

        try:
            await message.delete()
        except discord.HTTPException:
            pass

        # 処罰対象: 外部アプリ/Bot自身はタイムアウト不可のため、
        # インタラクション実行者(User Install App等)が判明していればそちらを処罰する
        target = invoking_user if (member.bot and invoking_user is not None) else member
        action_desc = "不明"

        if isinstance(target, discord.Member) and not target.bot:
            try:
                until = discord.utils.utcnow() + datetime.timedelta(minutes=timeout_minutes)
                await target.timeout(until, reason=reason)
                action_desc = f"{timeout_minutes}分間のタイムアウト"
            except discord.HTTPException:
                action_desc = "タイムアウトに失敗しました(権限不足の可能性)"
        elif member.bot:
            try:
                await guild.kick(member, reason=reason)
                action_desc = "外部アプリ/Botをサーバーからキック"
            except discord.HTTPException:
                action_desc = "キックに失敗しました(権限不足の可能性)"

        embed = discord.Embed(title="🛡️ 自動モデレーション", description=reason, color=discord.Color.red(), timestamp=discord.utils.utcnow())
        embed.add_field(name="対象アカウント", value=f"{member} (`{member.id}`)", inline=False)
        if invoking_user is not None:
            owner_display = invoking_user.mention if hasattr(invoking_user, "mention") else str(invoking_user)
            embed.add_field(name="実行した人(外部アプリ/インタラクション経由)", value=f"{owner_display} (`{invoking_user.id}`)", inline=False)
        embed.add_field(name="チャンネル", value=message.channel.mention, inline=False)
        embed.add_field(name="処置", value=action_desc, inline=False)
        await self.alert(guild, embed)

        # ---- ストライク制(スパム系タイムアウトの累積 → 警告DM → 自動BAN) ----
        if isinstance(target, discord.Member) and not target.bot:
            config = await self.get_config(guild.id)
            count = await self.bot.db.increment_strike(guild.id, target.id)

            if count >= config["strike_ban_threshold"]:
                try:
                    ban_embed = discord.Embed(
                        title="🔨 自動BAN",
                        description=(
                            f"スパム行為の疑いによるタイムアウトが {count} 回累積したため、"
                            "自動的にBANされました。"
                        ),
                        color=discord.Color.dark_red(),
                    )
                    try:
                        await target.send(embed=ban_embed)
                    except discord.HTTPException:
                        pass
                    await guild.ban(target, reason=f"anti-spam: スパム系タイムアウトが{count}回累積したため自動BAN")
                    await self.bot.db.reset_strikes(guild.id, target.id)

                    alert_embed = discord.Embed(
                        title="🔨 ストライク上限到達により自動BANしました",
                        description=f"{target.mention} (`{target.id}`) は累積ストライク {count} 回で自動BANされました。",
                        color=discord.Color.dark_red(),
                    )
                    await self.alert(guild, alert_embed)
                    await self.dm_owner(guild, alert_embed)
                except discord.HTTPException:
                    pass
            elif count == config["strike_warn_threshold"]:
                warn_embed = discord.Embed(
                    title="⚠️ 警告",
                    description=(
                        f"{guild.name} でスパム行為の疑いによるタイムアウトが **{count}回** 累積しました。\n"
                        "次に同様の行為が検知された場合、自動的にBANされます。"
                    ),
                    color=discord.Color.yellow(),
                )
                try:
                    await target.send(embed=warn_embed)
                except discord.HTTPException:
                    pass
                alert_embed = discord.Embed(
                    title="⚠️ ストライク警告DMを送信しました",
                    description=f"{target.mention} (`{target.id}`) の累積ストライクが {count} 回に達したため、次回BANの警告をDMしました。",
                    color=discord.Color.yellow(),
                )
                await self.alert(guild, alert_embed)

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
                    "サーバーの認証レベルを一時的に引き上げました。"
                ),
                color=discord.Color.dark_red(),
            )
            await self.alert(member.guild, embed)
            await self.dm_owner(member.guild, embed)
            try:
                if member.guild.verification_level != discord.VerificationLevel.high:
                    await member.guild.edit(verification_level=discord.VerificationLevel.high, reason="anti-raid自動発動")
            except discord.HTTPException:
                pass

    # ---------------- anti nuke ----------------
    async def _track_nuke_action(self, guild: discord.Guild, action: discord.AuditLogAction, target_id: int | None = None):
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
                    await self.dm_owner(guild, embed)
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
        await self._track_nuke_action(channel.guild, discord.AuditLogAction.channel_delete)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        await self._track_nuke_action(channel.guild, discord.AuditLogAction.channel_create)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        await self._track_nuke_action(role.guild, discord.AuditLogAction.role_delete)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        await self._track_nuke_action(role.guild, discord.AuditLogAction.role_create)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.abc.User):
        await self._track_nuke_action(guild, discord.AuditLogAction.ban)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        # キックによる退出のみ検知対象(通常の自主退出は監査ログに一致するエントリが無いため無視される)
        await self._track_nuke_action(member.guild, discord.AuditLogAction.kick)

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.abc.GuildChannel):
        await self._track_nuke_action(channel.guild, discord.AuditLogAction.webhook_create)

    # ---------------- 権限昇格の監視(乗っ取りされたモデレーターアカウント対策) ----------------
    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        config = await self.get_config(after.guild.id)
        if not config["anti_perm_escalation"]:
            return

        if not before.permissions.administrator and after.permissions.administrator:
            entry = await self.find_actor(after.guild, discord.AuditLogAction.role_update, after.id)
            actor = entry.user if entry else None
            if actor and (actor.id == after.guild.owner_id or await self.bot.db.is_whitelisted(after.guild.id, actor.id)):
                return

            try:
                await after.edit(permissions=before.permissions, reason="anti-perm-escalation: 不正な管理者権限付与を検知し取り消し")
            except discord.HTTPException:
                pass

            embed = discord.Embed(
                title="🚨 不正な管理者権限付与を検知し取り消しました",
                description=f"ロール {after.mention} に管理者権限が付与されたため、自動的に取り消しました。",
                color=discord.Color.dark_red(),
            )
            if actor:
                embed.add_field(name="実行者", value=f"{actor.mention} (`{actor.id}`)", inline=False)
            await self.alert(after.guild, embed)
            await self.dm_owner(after.guild, embed)

        await self._track_nuke_action(after.guild, discord.AuditLogAction.role_update, after.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(Security(bot))
