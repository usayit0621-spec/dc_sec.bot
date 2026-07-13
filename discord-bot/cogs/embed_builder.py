import datetime

import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import is_manage_messages

COLOR_PRESETS = {
    "red": discord.Color.red(),
    "blue": discord.Color.blue(),
    "green": discord.Color.green(),
    "yellow": discord.Color.gold(),
    "purple": discord.Color.purple(),
    "orange": discord.Color.orange(),
    "teal": discord.Color.teal(),
    "blurple": discord.Color.blurple(),
    "dark_red": discord.Color.dark_red(),
    "random": None,
}


def parse_color(value: str) -> discord.Color:
    if not value:
        return discord.Color.blurple()
    v = value.strip().lower()
    if v in COLOR_PRESETS:
        return COLOR_PRESETS[v] if COLOR_PRESETS[v] is not None else discord.Color.random()
    hex_part = v.lstrip("#")
    try:
        return discord.Color(int(hex_part, 16))
    except ValueError:
        return discord.Color.blurple()


class EmbedBuilder(commands.Cog):
    """/embed でタイトル・本文・画像・色を指定してカスタムEmbedを送信する機能"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="embed", description="タイトル・本文・画像・色を指定してEmbedメッセージを送信します")
    @app_commands.describe(
        title="Embedのタイトル",
        discussion="Embedの本文",
        image="添付する画像ファイル(任意)",
        color="Embedの色。プリセット名(red/blue/green等)か #RRGGBB のカラーコード",
        footer="フッターに表示するテキスト(任意)",
        thumbnail="右上に表示するサムネイル画像(任意)",
    )
    @is_manage_messages()
    async def embed(
        self,
        interaction: discord.Interaction,
        title: str,
        discussion: str,
        image: discord.Attachment = None,
        color: str = "blurple",
        footer: str = None,
        thumbnail: discord.Attachment = None,
    ):
        if image is not None and not (image.content_type or "").startswith("image"):
            await interaction.response.send_message("画像ファイルを選択してください。", ephemeral=True)
            return
        if thumbnail is not None and not (thumbnail.content_type or "").startswith("image"):
            await interaction.response.send_message("サムネイルには画像ファイルを選択してください。", ephemeral=True)
            return

        embed = discord.Embed(
            title=title,
            description=discussion,
            color=parse_color(color),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        if image is not None:
            embed.set_image(url=image.url)
        if thumbnail is not None:
            embed.set_thumbnail(url=thumbnail.url)
        if footer:
            embed.set_footer(text=footer, icon_url=interaction.user.display_avatar.url)
        embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)

        await interaction.response.send_message(embed=embed)

    @embed.autocomplete("color")
    async def color_autocomplete(self, interaction: discord.Interaction, current: str):
        matches = [name for name in COLOR_PRESETS if current.lower() in name]
        return [app_commands.Choice(name=name, value=name) for name in matches[:25]]


async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedBuilder(bot))
