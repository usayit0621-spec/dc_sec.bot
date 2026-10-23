import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import can_assign_role, ensure_owner_access, has_mod_access, has_owner_access


class ReactionRoles(commands.Cog):
    """リアクションロールとロール付与制限"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    rr_group = app_commands.Group(name="reactionrole", description="リアクションロールの設定")
    rolepanel_group = app_commands.Group(name="rolepanel", description="ロールパネルの設定")

    @rr_group.command(name="add", description="指定メッセージに絵文字リアクションでロールを付与する設定を追加します")
    @app_commands.describe(message_id="対象メッセージのID(メッセージを右クリック→IDをコピー)", emoji="使用する絵文字", role="付与するロール")
    async def rr_add(self, interaction: discord.Interaction, message_id: str, emoji: str, role: discord.Role):
        if not await has_mod_access(self.bot, interaction.guild, interaction.user):
            raise app_commands.MissingPermissions(["mod_role_or_owner"])
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("メッセージIDは数字で入力してください。", ephemeral=True)
            return

        if not await can_assign_role(self.bot, interaction.guild, interaction.user, role):
            await interaction.response.send_message("自分より上位のロールやBotより上位のロールは付与できません。", ephemeral=True)
            return

        target_message = None
        for channel in interaction.guild.text_channels:
            try:
                target_message = await channel.fetch_message(mid)
                break
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                continue

        if target_message is None:
            await interaction.response.send_message("指定したメッセージが見つかりませんでした。", ephemeral=True)
            return

        try:
            await target_message.add_reaction(emoji)
        except discord.HTTPException:
            await interaction.response.send_message("その絵文字はリアクションとして使用できません。", ephemeral=True)
            return

        await self.bot.db.add_reaction_role(interaction.guild_id, mid, emoji, role.id)
        await interaction.response.send_message(
            f"✅ メッセージ `{mid}` の {emoji} リアクションで {role.mention} を付与するよう設定しました。", ephemeral=True
        )

    @rolepanel_group.command(name="add", description="ロールパネルの設定を追加します")
    @app_commands.describe(message_id="対象メッセージのID", emoji="使用する絵文字", role="付与するロール")
    async def rolepanel_add(self, interaction: discord.Interaction, message_id: str, emoji: str, role: discord.Role):
        await self.rr_add(interaction, message_id, emoji, role)

    @rr_group.command(name="remove", description="リアクションロールの設定を削除します")
    @app_commands.describe(message_id="対象メッセージのID", emoji="対象の絵文字")
    async def rr_remove(self, interaction: discord.Interaction, message_id: str, emoji: str):
        if not await has_mod_access(self.bot, interaction.guild, interaction.user):
            raise app_commands.MissingPermissions(["mod_role_or_owner"])
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("メッセージIDは数字で入力してください。", ephemeral=True)
            return
        await self.bot.db.remove_reaction_role(mid, emoji)
        await interaction.response.send_message("✅ リアクションロールの設定を削除しました。", ephemeral=True)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.member is None or payload.member.bot:
            return
        row = await self.bot.db.get_reaction_role(payload.message_id, str(payload.emoji))
        if not row:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        role = guild.get_role(row["role_id"])
        if not role:
            return
        if not await can_assign_role(self.bot, guild, payload.member, role):
            try:
                await payload.member.send("そのロールは付与できません。自分より上位のロールやBotより上位のロールは付与できません。")
            except discord.HTTPException:
                pass
            try:
                await payload.member.remove_roles(role, reason="権限制限による拒否")
            except discord.HTTPException:
                pass
            try:
                await payload.message.remove_reaction(payload.emoji, payload.member)
            except discord.HTTPException:
                pass
            return
        try:
            await payload.member.add_roles(role, reason="リアクションロール")
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        row = await self.bot.db.get_reaction_role(payload.message_id, str(payload.emoji))
        if not row:
            return
        member = guild.get_member(payload.user_id)
        if not member or member.bot:
            return
        role = guild.get_role(row["role_id"])
        if role:
            try:
                await member.remove_roles(role, reason="リアクションロール解除")
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(ReactionRoles(bot))


async def teardown(bot: commands.Bot):
    pass
