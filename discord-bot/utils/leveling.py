import discord


async def apply_level_change(bot, guild: discord.Guild, member: discord.Member, delta: int) -> int:
    """指定メンバーのレベルを delta だけ増減させ、新しいレベルを返す。
    レベルアップ時は levelup_config のチャンネルへ通知し、
    level_rewards に設定されたロールを自動付与する。
    """
    current = await bot.db.get_level(guild.id, member.id)
    new_level = max(0, current + delta)
    await bot.db.set_level(guild.id, member.id, new_level)

    if delta > 0 and new_level > current:
        await _handle_level_up(bot, guild, member, new_level)

    return new_level


async def _handle_level_up(bot, guild: discord.Guild, member: discord.Member, new_level: int):
    # レベル報酬ロールの付与(new_level 以下で最も高いレベルの報酬ロールを付与)
    rewards = await bot.db.get_level_rewards(guild.id)
    role_to_grant = None
    for row in rewards:
        if row["level"] <= new_level:
            role_to_grant = row["role_id"]

    if role_to_grant:
        role = guild.get_role(role_to_grant)
        if role and role not in member.roles:
            try:
                await member.add_roles(role, reason=f"レベル {new_level} 到達による自動付与")
            except discord.HTTPException:
                pass

    # レベルアップ通知
    channel_id = await bot.db.get_levelup_channel(guild.id)
    if channel_id:
        channel = guild.get_channel(channel_id)
        if channel:
            embed = discord.Embed(
                title="🎉 レベルアップ!",
                description=f"{member.mention} がレベル **{new_level}** になりました!",
                color=discord.Color.gold(),
            )
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass
