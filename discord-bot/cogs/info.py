import discord
from discord import app_commands
from discord.ext import commands

STATUS_LABEL = {
    discord.Status.online: "🟢 オンライン",
    discord.Status.idle: "🌙 退席中",
    discord.Status.dnd: "⛔ 取り込み中",
    discord.Status.offline: "⚫ オフライン",
    discord.Status.invisible: "⚫ オフライン",
}

DEVICE_LABEL = {
    discord.Status.online: "🟢 オンライン",
    discord.Status.idle: "🌙 退席中",
    discord.Status.dnd: "⛔ 取り込み中",
    discord.Status.offline: "⚫ 未使用",
}


class Info(commands.Cog):
    """/info user でユーザーのオンライン状況・デバイス種別などの詳細情報を表示する機能"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    info_group = app_commands.Group(name="info", description="詳細情報を表示します")

    @info_group.command(name="user", description="指定したユーザーの詳細情報(オンライン状況・デバイス等)を表示します")
    @app_commands.describe(user="詳細を見たいユーザー")
    async def info_user(self, interaction: discord.Interaction, user: discord.Member):
        embed = discord.Embed(
            title=f"🔎 {user} の詳細情報",
            color=user.color if user.color.value else discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=user.display_avatar.url)

        # 基本情報
        embed.add_field(name="ユーザー名", value=str(user), inline=True)
        embed.add_field(name="ID", value=str(user.id), inline=True)
        embed.add_field(name="Bot", value="はい" if user.bot else "いいえ", inline=True)
        embed.add_field(name="ニックネーム", value=user.nick or "なし", inline=True)
        embed.add_field(name="アカウント作成日", value=f"<t:{int(user.created_at.timestamp())}:F>", inline=False)
        if user.joined_at:
            embed.add_field(name="サーバー参加日", value=f"<t:{int(user.joined_at.timestamp())}:F>", inline=False)

        # オンライン状況・デバイス
        embed.add_field(name="全体ステータス", value=STATUS_LABEL.get(user.status, "不明"), inline=True)
        embed.add_field(name="💻 デスクトップ", value=DEVICE_LABEL.get(user.desktop_status, "🟢 オンライン" if user.desktop_status != discord.Status.offline else "⚫ 未使用"), inline=True)
        embed.add_field(name="📱 モバイル", value=DEVICE_LABEL.get(user.mobile_status, "🟢 オンライン" if user.mobile_status != discord.Status.offline else "⚫ 未使用"), inline=True)
        embed.add_field(name="🌐 Web/ブラウザ", value=DEVICE_LABEL.get(user.web_status, "🟢 オンライン" if user.web_status != discord.Status.offline else "⚫ 未使用"), inline=True)

        # アクティビティ(ゲーム・カスタムステータス・Spotify等)
        if user.activities:
            act_lines = []
            for act in user.activities:
                if isinstance(act, discord.Spotify):
                    act_lines.append(f"🎵 Spotifyで再生中: {act.title} - {act.artist}")
                elif isinstance(act, discord.CustomActivity):
                    text = act.name or ""
                    emoji = str(act.emoji) if act.emoji else ""
                    if text or emoji:
                        act_lines.append(f"💬 カスタムステータス: {emoji} {text}".strip())
                elif isinstance(act, discord.Game):
                    act_lines.append(f"🎮 プレイ中: {act.name}")
                elif isinstance(act, discord.Streaming):
                    act_lines.append(f"📡 配信中: {act.name}")
                elif isinstance(act, discord.Activity):
                    label = {
                        discord.ActivityType.playing: "🎮 プレイ中",
                        discord.ActivityType.watching: "📺 視聴中",
                        discord.ActivityType.listening: "🎧 視聴中",
                        discord.ActivityType.competing: "🏆 参加中",
                    }.get(act.type, "ステータス")
                    act_lines.append(f"{label}: {act.name}")
            if act_lines:
                embed.add_field(name="アクティビティ", value="\n".join(act_lines)[:1024], inline=False)

        # ボイス状態
        if user.voice:
            vs = user.voice
            voice_info = f"参加中: {vs.channel.mention}"
            flags = []
            if vs.self_mute:
                flags.append("マイクミュート")
            if vs.self_deaf:
                flags.append("スピーカーミュート")
            if vs.mute:
                flags.append("サーバーミュート")
            if vs.deaf:
                flags.append("サーバースピーカーミュート")
            if vs.self_stream:
                flags.append("画面共有中")
            if vs.self_video:
                flags.append("カメラON")
            if flags:
                voice_info += " (" + ", ".join(flags) + ")"
            embed.add_field(name="🔊 ボイスチャンネル", value=voice_info, inline=False)
        else:
            embed.add_field(name="🔊 ボイスチャンネル", value="未接続", inline=False)

        # 権限・その他
        embed.add_field(name="サーバー内最上位ロール", value=user.top_role.mention, inline=True)
        embed.add_field(name="管理者権限", value="はい" if user.guild_permissions.administrator else "いいえ", inline=True)
        if user.premium_since:
            embed.add_field(name="ブースト開始日", value=f"<t:{int(user.premium_since.timestamp())}:F>", inline=True)
        if user.timed_out_until:
            embed.add_field(name="タイムアウト中", value=f"<t:{int(user.timed_out_until.timestamp())}:F> まで", inline=True)
        if user.pending:
            embed.add_field(name="メンバーシップ審査", value="未完了(スクリーニング待ち)", inline=True)

        roles = [r.mention for r in user.roles if r != interaction.guild.default_role]
        embed.add_field(name=f"ロール ({len(roles)})", value=", ".join(roles)[:1024] if roles else "なし", inline=False)

        embed.set_footer(text=f"{interaction.user} がリクエスト")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Info(bot))
