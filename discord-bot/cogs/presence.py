import discord
from discord.ext import commands, tasks


class Presence(commands.Cog):
    """Botのステータス(アクティビティ)を10秒ごとに切り替えて表示する機能"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.index = 0
        self.rotator.start()

    def cog_unload(self):
        self.rotator.cancel()

    def _build_statuses(self) -> list[discord.Activity]:
        latency_ms = round(self.bot.latency * 1000)
        guild_count = len(self.bot.guilds)
        member_count = sum(g.member_count or 0 for g in self.bot.guilds)

        return [
            discord.Activity(type=discord.ActivityType.watching, name=f"Ping: {latency_ms}ms"),
            discord.Activity(type=discord.ActivityType.watching, name=f"{guild_count} サーバー"),
            discord.Activity(type=discord.ActivityType.watching, name=f"{member_count} 人のメンバー"),
            discord.Activity(type=discord.ActivityType.playing, name="/log /stick /security で設定"),
            discord.Activity(type=discord.ActivityType.watching, name="このサーバーを見守り中"),
        ]

    @tasks.loop(seconds=10)
    async def rotator(self):
        statuses = self._build_statuses()
        if not statuses:
            return
        activity = statuses[self.index % len(statuses)]
        self.index += 1
        try:
            await self.bot.change_presence(activity=activity)
        except discord.HTTPException:
            pass

    @rotator.before_loop
    async def before_rotator(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Presence(bot))
