import re
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.checks import is_manage_guild
from utils.leveling import apply_level_change
from utils.backup import upload_backup

CYCLE_SECONDS = 120 * 60  # 2時間

BUMP_COMMAND_MENTION = "</bump:947088344167366698>"
UP_COMMAND_MENTION = "</up:1363739182672904354>"

MENTION_RE = re.compile(r"<@!?\d+>")
CHANNEL_RE = re.compile(r"<#\d+>")
ROLE_MENTION_RE = re.compile(r"<@&\d+>")
DIGIT_RE = re.compile(r"\d+")


def normalize(text: str) -> str:
    """メンション・チャンネル・数字(カウントダウン等)を正規化し、メッセージの"指紋"を作る"""
    text = MENTION_RE.sub("@U", text)
    text = ROLE_MENTION_RE.sub("@R", text)
    text = CHANNEL_RE.sub("#C", text)
    text = DIGIT_RE.sub("#", text)
    return text.strip()


def build_template_text(message: discord.Message) -> str:
    parts = [message.content or ""]
    for embed in message.embeds:
        if embed.title:
            parts.append(embed.title)
        if embed.description:
            parts.append(embed.description)
        for field in embed.fields:
            parts.append(field.name or "")
            parts.append(field.value or "")
    joined = "\n".join(p for p in parts if p)
    return normalize(joined)


class BumpReminder(commands.Cog):
    """メッセージを右クリック→アプリ から成功メッセージの形式をBotに覚えさせ、
    以後は同じ形式のメッセージが送信されたタイミングを基準にリマインド通知・RTA計測・レベル付与を行う機能"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.checker.start()

    def cog_unload(self):
        self.checker.cancel()

    # NOTE: context menus cannot be defined inside a Cog class (discord.py restriction).
    # The actual context-menu callbacks are implemented as module-level commands below
    # which delegate to this cog's _register_template method.

    async def _register_template(self, interaction: discord.Interaction, message: discord.Message, type_: str, label: str):
        if not message.guild:
            await interaction.response.send_message("サーバー内のメッセージのみ登録できます。", ephemeral=True)
            return
        if not message.author.bot:
            await interaction.response.send_message("Bot(Disboard/ディス速等)が送信したメッセージを右クリックして登録してください。", ephemeral=True)
            return

        template = build_template_text(message)
        if not template:
            await interaction.response.send_message("このメッセージにはテキスト内容がなく、テンプレートとして登録できません。", ephemeral=True)
            return

        await self.bot.db.set_bump_template(interaction.guild_id, type_, message.author.id, template)
        await self.bot.db.ensure_reminder_config(interaction.guild_id, type_, message.channel.id)

        embed = discord.Embed(
            title=f"✅ {label}成功メッセージを登録しました",
            description=(
                f"今後 {message.author.mention} から同じ形式のメッセージが送信されると、自動的に検知して\n"
                f"・2時間後のクールダウンタイマー開始\n"
                "・RTAタイム計測\n"
                "・実行者へのレベル付与\n"
                "を行います。通知ロール/通知チャンネルは `/bump-mantion` `/up-mantion` で別途設定してください。"
            ),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await upload_backup(self.bot)

    # ---------------- リマインダー設定コマンド(形式は変更なし) ----------------
    @app_commands.command(name="bump-mantion", description="登録済みのBump成功メッセージが検知される前に通知するリマインダーを設定します")
    @app_commands.describe(min="何分前に通知するか", m="通知したいロールをメンション")
    @is_manage_guild()
    async def bump_mantion(self, interaction: discord.Interaction, min: app_commands.Range[int, 0, 119], m: discord.Role):
        await self.bot.db.set_reminder_config(interaction.guild_id, "bump", interaction.channel_id, m.id, min)
        embed = discord.Embed(
            title="✅ bumpリマインダーを設定しました",
            description=(
                f"このチャンネルで {m.mention} に、次回bump可能時刻の **{min}分前** に通知します。\n"
                "先に対象メッセージを右クリック→アプリ→「Bumpメッセージに設定」で登録しておいてください（未登録でも設定は保存されます）[...]"
            ),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await upload_backup(self.bot)

    @app_commands.command(name="up-mantion", description="登録済みのUp成功メッセージが検知される前に通知するリマインダーを設定します")
    @app_commands.describe(min="何分前に通知するか", m="通知したいロールをメンション")
    @is_manage_guild()
    async def up_mantion(self, interaction: discord.Interaction, min: app_commands.Range[int, 0, 119], m: discord.Role):
        await self.bot.db.set_reminder_config(interaction.guild_id, "up", interaction.channel_id, m.id, min)
        embed = discord.Embed(
            title="✅ upリマインダーを設定しました",
            description=(
                f"このチャンネルで {m.mention} に、次回up可能時刻の **{min}分前** に通知します。\n"
                "先に対象メッセージを右クリック→アプリ→「Upメッセージに設定」で登録しておいてください（未登録でも設定は保存されます）��[...]"
            ),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await upload_backup(self.bot)

    # ---------------- 実行者の特定(外部アプリ/インタラクション経由) ----------------
    def _get_interaction_user(self, message: discord.Message):
        meta = getattr(message, "interaction_metadata", None)
        if meta is not None and getattr(meta, "user", None):
            return message.guild.get_member(meta.user.id) or meta.user
        legacy = getattr(message, "interaction", None)
        if legacy is not None and getattr(legacy, "user", None):
            return message.guild.get_member(legacy.user.id) or legacy.user
        return None

    # ---------------- テンプレート照合 ----------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or not message.author.bot:
            return

        for type_ in ("bump", "up"):
            row = await self.bot.db.get_bump_template(message.guild.id, type_)
            if not row or row["author_id"] != message.author.id:
                continue
            candidate = build_template_text(message)
            if candidate and candidate == row["template"]:
                await self._handle_success(message, type_)
                break

    async def _handle_success(self, message: discord.Message, type_: str):
        guild = message.guild
        now_ts = message.created_at.timestamp()

        await self.bot.db.ensure_reminder_config(guild.id, type_, message.channel.id)
        reminder_config = await self.bot.db.get_reminder_config(guild.id, type_)
        prev_next_time = reminder_config["next_time"] if reminder_config else None

        # レベル付与対象の特定
        target_user = None
        if type_ == "bump" and message.mentions:
            target_user = message.mentions[0]
        if target_user is None:
            target_user = self._get_interaction_user(message)

        # RTA計測(前回クールダウンが明けた時刻からの経過秒数)
        if prev_next_time:
            elapsed = now_ts - prev_next_time
            if elapsed >= 0:
                await self._send_rta(message, type_, elapsed, target_user)

        # 次回利用可能時刻を更新(2時間後)
        new_next_time = now_ts + CYCLE_SECONDS
        await self.bot.db.set_reminder_next_time(guild.id, type_, new_next_time)

        # レベルアップ
        if target_user is not None and not target_user.bot:
            await apply_level_change(self.bot, guild, target_user, 1)

    async def _send_rta(self, message: discord.Message, type_: str, elapsed: float, target_user):
        label = "/bump" if type_ == "bump" else "/up"
        mention = target_user.mention if target_user else ""
        try:
            await message.channel.send(
                f"{mention} 🏁 **{label} RTA: {elapsed:.6f}秒**",
                allowed_mentions=discord.AllowedMentions(users=True),
            )
        except discord.HTTPException:
            pass

    # ---------------- background loop(リマインド通知) ----------------
    @tasks.loop(seconds=20)
    async def checker(self):
        now = time.time()
        rows = await self.bot.db.get_all_reminders()
        for row in rows:
            if row["next_time"] is None or row["notified"] or not row["role_id"]:
                continue
            minutes_before = row["minutes_before"] or 0
            fire_at = row["next_time"] - minutes_before * 60
            if now >= fire_at:
                await self._notify(row)
                await self.bot.db.mark_reminder_notified(row["guild_id"], row["type"])

    @checker.before_loop
    async def before_checker(self):
        await self.bot.wait_until_ready()

    async def _notify(self, row):
        guild = self.bot.get_guild(row["guild_id"])
        if not guild:
            return
        channel = guild.get_channel(row["channel_id"])
        if not channel:
            return
        role = guild.get_role(row["role_id"]) if row["role_id"] else None
        if not role:
            return

        mention = BUMP_COMMAND_MENTION if row["type"] == "bump" else UP_COMMAND_MENTION
        label = "bump" if row["type"] == "bump" else "up"

        embed = discord.Embed(
            title=f"⏰ もうすぐ /{label} が使用可能です",
            description=f"# {role.mention}\n{mention} が使用可能です。",
            color=discord.Color.gold(),
        )
        try:
            await channel.send(content=role.mention, embed=embed, allowed_mentions=discord.AllowedMentions(roles=True))
        except discord.HTTPException:
            pass


# ---------------- Module-level context menu callbacks ----------------
# Context menus cannot be declared inside a Cog class; create module-level callbacks
# that delegate to the cog instance's implementation.

async def _bump_context_callback(interaction: discord.Interaction, message: discord.Message):
    cog = interaction.client.get_cog("BumpReminder")
    if cog is None:
        await interaction.response.send_message("Internal error: BumpReminder cog not loaded.", ephemeral=True)
        return
    await cog._register_template(interaction, message, "bump", "Bump")


async def _up_context_callback(interaction: discord.Interaction, message: discord.Message):
    cog = interaction.client.get_cog("BumpReminder")
    if cog is None:
        await interaction.response.send_message("Internal error: BumpReminder cog not loaded.", ephemeral=True)
        return
    await cog._register_template(interaction, message, "up", "Up")


_bump_context = app_commands.ContextMenu(name="Bumpメッセージに設定", callback=_bump_context_callback)
_up_context = app_commands.ContextMenu(name="Upメッセージに設定", callback=_up_context_callback)


async def setup(bot: commands.Bot):
    # Register module-level context menus on the bot's command tree
    try:
        bot.tree.add_command(_bump_context)
        bot.tree.add_command(_up_context)
    except Exception:
        # ignore if already added
        pass

    await bot.add_cog(BumpReminder(bot))
