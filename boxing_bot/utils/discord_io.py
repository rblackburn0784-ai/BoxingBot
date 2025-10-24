import discord


async def respond(interaction: discord.Interaction, *args, **kwargs):
    try:
        if not interaction.response.is_done():
            return await interaction.response.send_message(*args, **kwargs)
        else:
            return await interaction.followup.send(*args, **kwargs)
    except discord.NotFound:
        return await interaction.followup.send(*args, **kwargs)