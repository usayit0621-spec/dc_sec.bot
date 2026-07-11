import discord
from discord import app_commands

JST_EMBED_COLOR = discord.Color.blurple()
SUCCESS_COLOR = discord.Color.green()
WARN_COLOR = discord.Color.orange()
DANGER_COLOR = discord.Color.red()


def is_manage_guild():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.manage_guild:
            return True
        raise app_commands.MissingPermissions(["manage_guild"])
    return app_commands.check(predicate)


def is_manage_messages():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.manage_messages:
            return True
        raise app_commands.MissingPermissions(["manage_messages"])
    return app_commands.check(predicate)


def is_moderator():
    async def predicate(interaction: discord.Interaction) -> bool:
        perms = interaction.user.guild_permissions
        if perms.kick_members or perms.ban_members or perms.moderate_members:
            return True
        raise app_commands.MissingPermissions(["moderate_members"])
    return app_commands.check(predicate)


def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        raise app_commands.MissingPermissions(["administrator"])
    return app_commands.check(predicate)
