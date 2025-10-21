import discord
from discord.ext import commands
from discord import app_commands, Interaction
import json
import os
import random
import asyncio

# -------------------------------
# CONFIGURATION
# -------------------------------

TOKEN = os.environ['DISCORD_TOKEN']
GUILD_ID = 1094757085360685067  # Remplace par l'ID de ton serveur Discord
SETS = ["Set 1", "Set 2", "Set 3", "Set 4"]
ARENAS = [
    "Lagoon of Whispers",
    "Lookout Point",
    "Barnacle Cay",
    "Blind Man Lagoon",
    "Picaroon Palms"
]
CAPITAINS_PER_SET = 3
VOTES_FILE = "votes.json"

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# -------------------------------
# UTILITAIRES
# -------------------------------

def load_votes():
    if os.path.exists(VOTES_FILE):
        with open(VOTES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    # initialisation
    votes = {}
    for s in SETS:
        votes[s] = {
            "votes": {},
            "coefficients": {arena: 1 for arena in ARENAS},
            "open": False
        }
    return votes

def save_votes(data):
    with open(VOTES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

votes_data = load_votes()

async def send_temp_message(channel, content, delay=5):
    msg = await channel.send(content)
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except:
        pass

# -------------------------------
# INTERACTIONS DE VOTE
# -------------------------------

class VoteView(discord.ui.View):
    def __init__(self, set_name, captain_name):
        super().__init__(timeout=None)
        self.set_name = set_name
        self.captain_name = captain_name
        self.favoris = []
        self.bannis = []
        self.stage = "favoris"  # ou "bannis"

        for arena in ARENAS:
            self.add_item(discord.ui.Button(label=arena, style=discord.ButtonStyle.secondary, custom_id=arena))

        self.add_item(discord.ui.Button(label="Confirmer", style=discord.ButtonStyle.green, custom_id="confirmer"))

    @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.green)
    async def confirmer(self, interaction: Interaction, button: discord.ui.Button):
        set_votes = votes_data[self.set_name]["votes"]
        if self.captain_name in set_votes:
            await interaction.response.send_message("❌ Vous avez déjà voté.", ephemeral=True)
            return

        if len(self.favoris) != 2 or len(self.bannis) != 2:
            await interaction.response.send_message("❌ Vous devez sélectionner 2 favoris et 2 bannis.", ephemeral=True)
            return

        # Mise à jour des coefficients
        for arena in self.favoris:
            votes_data[self.set_name]["coefficients"][arena] += 1
        for arena in self.bannis:
            votes_data[self.set_name]["coefficients"][arena] -= 1

        # Sauvegarde du vote
        set_votes[self.captain_name] = {"favoris": self.favoris, "bannis": self.bannis}
        save_votes(votes_data)

        await interaction.response.send_message(f"✅ Vote confirmé pour {self.set_name} !", ephemeral=True)

        # Tirage si tous les votes du set sont faits
        if len(set_votes) >= CAPITAINS_PER_SET:
            await tirage_set(self.set_name, interaction.channel)

    @discord.ui.button(label="Favoris / Bannis", style=discord.ButtonStyle.blurple)
    async def toggle_stage(self, interaction: Interaction, button: discord.ui.Button):
        # Change le stage entre favoris et bannis
        self.stage = "bannis" if self.stage == "favoris" else "favoris"
        await interaction.response.send_message(f"Stage changé : maintenant `{self.stage}`", ephemeral=True)

    async def interaction_check(self, interaction: Interaction) -> bool:
        return interaction.user.name == self.captain_name

# Tirage pondéré
async def tirage_set(set_name, channel):
    coeffs = votes_data[set_name]["coefficients"]
    arenas = list(coeffs.keys())
    weights = list(coeffs.values())
    tirage = random.choices(arenas, weights=weights, k=1)[0]
    await channel.send(f"🎯 **Carte tirée au sort pour {set_name} : {tirage} !**")

# -------------------------------
# COMMANDES SLASH
# -------------------------------

@bot.event
async def on_ready():
    guild = discord.Object(id=GUILD_ID)
    await bot.tree.sync(guild=guild)
    print(f"✅ Connecté en tant que {bot.user}")

def is_admin(interaction: Interaction):
    admin_role = discord.utils.get(interaction.guild.roles, name="ADMIN")
    return admin_role in interaction.user.roles

@bot.tree.command(name="ouvrir_votes", description="Ouvre la phase de vote")
@app_commands.check(is_admin)
async def ouvrir_votes(interaction: Interaction):
    for s in SETS:
        votes_data[s]["open"] = True
    save_votes(votes_data)
    await interaction.response.send_message("✅ Votes ouverts !\n💬 Ce message va s’auto-détruire dans 5 secondes.", ephemeral=False)
    await send_temp_message(interaction.channel, "Message de confirmation supprimé", delay=5)

@bot.tree.command(name="fermer_votes", description="Ferme la phase de vote")
@app_commands.check(is_admin)
async def fermer_votes(interaction: Interaction):
    for s in SETS:
        votes_data[s]["open"] = False
    save_votes(votes_data)
    await interaction.response.send_message("🚫 Votes fermés !\n💬 Ce message va s’auto-détruire dans 5 secondes.", ephemeral=False)
    await send_temp_message(interaction.channel, "Message de confirmation supprimé", delay=5)

@bot.tree.command(name="reset_votes", description="Réinitialise tous les votes")
@app_commands.check(is_admin)
async def reset_votes(interaction: Interaction):
    global votes_data
    votes_data = load_votes()
    save_votes(votes_data)
    await interaction.response.send_message("♻️ Votes réinitialisés !\n💬 Ce message va s’auto-détruire dans 5 secondes.", ephemeral=False)
    await send_temp_message(interaction.channel, "Message de confirmation supprimé", delay=5)

@bot.tree.command(name="verifier_votes", description="Vérifie qui a voté dans un set")
@app_commands.describe(set_num="Numéro du set (1-4)")
@app_commands.check(is_admin)
async def verifier_votes(interaction: Interaction, set_num: int):
    if set_num < 1 or set_num > 4:
        await interaction.response.send_message("❌ Numéro de set invalide", ephemeral=True)
        return
    set_name = SETS[set_num-1]
    set_votes = votes_data[set_name]["votes"]
    votants = ", ".join(set_votes.keys()) if set_votes else "Aucun"
    await interaction.response.send_message(f"✅ Capitaines ayant voté pour {set_name} : {votants}", ephemeral=True)

# -------------------------------
# RUN BOT
# -------------------------------

bot.run(TOKEN)
