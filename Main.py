# main.py
"""
Bot Discord — Vote d'arènes pondéré (discord.py 2.x)
Fonctionnalités :
- 4 sets, jusqu'à 3 capitaines par set
- 5 arènes, coefficients initiaux = 1
- Interface via discord.ui (sélecteurs + bouton confirmer)
- Sauvegarde persistante dans votes.json
- Commandes slash admin: ouvrir_votes, fermer_votes, reset_votes, verifier_votes
- Messages de confirmation auto-supprimés (5s)
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import asyncio
import random
from typing import Dict

# ---------- CONFIG ----------
TOKEN_ENV = "DISCORD_TOKEN"  # sur Replit : ajoute en Secrets
ADMIN_ROLE_NAME = "ADMIN"
CAPTAIN_ROLE_NAME = "Capitaine"  # rôle qui permet de voter (il faut aussi le rôle Set X)
SET_ROLE_NAMES = {
    "1": "Set 1",
    "2": "Set 2",
    "3": "Set 3",
    "4": "Set 4"
}
ARENAS = [
    "Lagoon of Whispers",
    "Lookout Point",
    "Barnacle Cay",
    "Blind Man Lagoon",
    "Picaroon Palms"
]
DATA_FILE = "votes.json"

intents = discord.Intents.default()
intents.members = True  # nécessaire pour vérifier rôles et membres
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- Utilities: load/save ----------
def ensure_data():
    if not os.path.exists(DATA_FILE):
        data = {
            "active": False,
            "channel_id": None,
            "sets": {}
        }
        for i in range(1,5):
            data["sets"][str(i)] = {
                "votes": {},   # user_id -> {"favors": [...], "bans":[...]}
                "coeffs": {arena: 1 for arena in ARENAS}
            }
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    else:
        # check keys present
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except Exception:
                # recreate if corrupt
                os.remove(DATA_FILE)
                ensure_data()
                return
        changed = False
        if "sets" not in data:
            changed = True
            data["sets"] = {}
        for i in range(1,5):
            if str(i) not in data["sets"]:
                changed = True
                data["sets"][str(i)] = {"votes": {}, "coeffs": {arena:1 for arena in ARENAS}}
            else:
                # ensure coeffs keys
                for arena in ARENAS:
                    if arena not in data["sets"][str(i)]["coeffs"]:
                        data["sets"][str(i)]["coeffs"][arena] = 1
        if changed:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

def load_data() -> Dict:
    ensure_data()
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data: Dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ---------- Helper checks ----------
def is_admin(member: discord.Member) -> bool:
    return any(role.name == ADMIN_ROLE_NAME for role in member.roles)

def has_set_role(member: discord.Member, set_number: str) -> bool:
    target = SET_ROLE_NAMES.get(set_number)
    if target is None:
        return False
    return any(role.name == target for role in member.roles)

def is_captain(member: discord.Member) -> bool:
    return any(role.name == CAPTAIN_ROLE_NAME for role in member.roles)

# ---------- UI: Vote View ----------
class VoteView(discord.ui.View):
    def __init__(self, set_number: str, author: discord.Member = None):
        super().__init__(timeout=None)  # stays alive while process runs
        self.set_number = set_number
        self.author = author  # optional: to tie view to one user; we'll allow all captains with proper roles
        # store temp selections per user in-memory to handle flow before confirm
        # Format: user_id -> {"favors": [], "bans": []}
        self.temp: Dict[int, Dict[str, list]] = {}

    # Favor select (max 2)
    @discord.ui.select(
        placeholder="Choisis 2 arènes à favoriser (max 2)",
        min_values=0,
        max_values=2,
        options=[discord.SelectOption(label=a) for a in ARENAS],
        custom_id=lambda self: f"favor_select_set{self.set_number}"
    )
    async def favor_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        user = interaction.user
        # role checks
        if not is_captain(user) or not has_set_role(user, self.set_number):
            await interaction.response.send_message("❌ Tu n'as pas le rôle requis pour voter pour ce set.", ephemeral=True)
            return

        uid = user.id
        self.temp.setdefault(uid, {"favors": [], "bans": []})
        self.temp[uid]["favors"] = select.values
        await interaction.response.send_message(f"✅ Favoris enregistrés : {', '.join(select.values) if select.values else '—'}", ephemeral=True)

    # Ban select (max 2)
    @discord.ui.select(
        placeholder="Choisis 2 arènes à bannir (max 2)",
        min_values=0,
        max_values=2,
        options=[discord.SelectOption(label=a) for a in ARENAS],
        custom_id=lambda self: f"ban_select_set{self.set_number}"
    )
    async def ban_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        user = interaction.user
        if not is_captain(user) or not has_set_role(user, self.set_number):
            await interaction.response.send_message("❌ Tu n'as pas le rôle requis pour voter pour ce set.", ephemeral=True)
            return

        uid = user.id
        self.temp.setdefault(uid, {"favors": [], "bans": []})
        self.temp[uid]["bans"] = select.values
        await interaction.response.send_message(f"✅ Bans enregistrés : {', '.join(select.values) if select.values else '—'}", ephemeral=True)

    # Confirm button
    @discord.ui.button(label="Confirmer mon vote", style=discord.ButtonStyle.green, custom_id=lambda self: f"confirm_vote_set{self.set_number}")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if not is_captain(user) or not has_set_role(user, self.set_number):
            await interaction.response.send_message("❌ Tu n'as pas le rôle requis pour voter pour ce set.", ephemeral=True)
            return

        uid = str(user.id)
        data = load_data()
        setdata = data["sets"][self.set_number]

        # check if already voted in this session
        if uid in setdata["votes"]:
            await interaction.response.send_message("❌ Tu as déjà voté pour ce set lors de cette session.", ephemeral=True)
            return

        # retrieve temporary selections
        t = self.temp.get(user.id, {"favors": [], "bans": []})
        favors = t.get("favors", [])
        bans = t.get("bans", [])

        # validation
        if len(favors) != 2 or len(bans) != 2:
            await interaction.response.send_message("❌ Tu dois choisir exactement 2 arènes à favoriser ET 2 arènes à bannir avant de confirmer.", ephemeral=True)
            return

        # apply to coeffs
        for a in favors:
            if a in setdata["coeffs"]:
                setdata["coeffs"][a] += 1
        for a in bans:
            if a in setdata["coeffs"]:
                setdata["coeffs"][a] -= 1

        # save vote
        setdata["votes"][uid] = {
            "user": user.name,
            "favors": favors,
            "bans": bans
        }
        save_data(data)

        # lock this user's temp
        if user.id in self.temp:
            del self.temp[user.id]

        await interaction.response.send_message("✅ Vote confirmé. Merci !", ephemeral=True)

        # if reached 3 votes for this set => compute and announce
        if len(setdata["votes"]) >= 3:
            # compute weights (non-negative)
            coeffs = setdata["coeffs"]
            weights = []
            arenas = []
            for arena, w in coeffs.items():
                weight = max(0, w)  # negative -> 0
                arenas.append(arena)
                weights.append(weight)
            # if all zero, fallback to equal weights
            if sum(weights) == 0:
                weights = [1]*len(arenas)
            chosen = random.choices(arenas, weights=weights, k=1)[0]
            channel = interaction.channel
            await channel.send(f"🎯 **Carte tirée au sort pour le Set {self.set_number} : {chosen} !**")
            # optionally mark set as closed so no more votes accepted (but here we keep session active; admin can close)
            # (we won't auto-reset; admin can /reset_votes)
# ---------- Slash commands & helpers ----------

async def send_ephemeral_cleanup(interaction: discord.Interaction, content: str):
    """
    Envoie un message public de confirmation suivi d'une phrase 'va s'auto-detruire dans 5s',
    attend 5s, puis supprime les messages pour nettoyer le salon.
    """
    # réponse principale
    await interaction.response.send_message(content)
    # récupère la première réponse (le bot)
    msg = await interaction.original_response()
    # second message (sous le premier)
    note = await interaction.followup.send("💬 Ce message va s’auto-détruire dans 5 secondes.")
    # attend 5 secondes puis supprime les deux messages
    await asyncio.sleep(5)
    try:
        await msg.delete()
    except Exception:
        pass
    try:
        await note.delete()
    except Exception:
        pass

@bot.event
async def on_ready():
    print(f"Connecté en tant que {bot.user} (id: {bot.user.id})")
    ensure_data()
    # nothing else needed; interactive Views created when /ouvrir_votes executed
    # NOTE: Views are non-persistent across restarts in this implementation.

# --- /ouvrir_votes (ADMIN)
@bot.tree.command(name="ouvrir_votes", description="Ouvre la phase de vote (ADMIN seulement)")
async def open_votes(interaction: discord.Interaction):
    member = interaction.user
    if not isinstance(member, discord.Member):
        await interaction.response.send_message("❌ Erreur de contexte.", ephemeral=True)
        return
    if not is_admin(member):
        await interaction.response.send_message("❌ Tu dois avoir le rôle ADMIN pour utiliser cette commande.", ephemeral=True)
        return

    data = load_data()
    if data.get("active", False):
        await send_ephemeral_cleanup(interaction, "⚠️ Les votes sont déjà ouverts.")
        return

    data["active"] = True
    data["channel_id"] = interaction.channel.id
    # reset votes but keep coefficients? We'll reset votes only; keep coeffs initial unless admin wants reset
    for i in range(1,5):
        data["sets"][str(i)]["votes"] = {}
        data["sets"][str(i)]["coeffs"] = {arena: 1 for arena in ARENAS}
    save_data(data)

    # send one message per set with interactive view
    sent_messages = []
    for i in range(1,5):
        view = VoteView(str(i))
        embed = discord.Embed(title=f"Vote — Set {i}", description=(
            "Capitaines : sélectionnez **2 arènes à favoriser** et **2 arènes à bannir**.\n"
            "Cliquez ensuite sur **Confirmer mon vote**. Chaque capitaine ne peut voter qu'une fois par session.\n"
            "Rôle requis : 'Capitaine' + rôle du set correspondant (ex: 'Set 1')."
        ), color=discord.Color.blue())
        msg = await interaction.channel.send(embed=embed, view=view)
        sent_messages.append(msg.id)

    # store message IDs optionally (not required here)
    data["last_messages"] = sent_messages
    save_data(data)

    await send_ephemeral_cleanup(interaction, "✅ Votes ouverts ! Les interfaces ont été postées dans ce canal.")

# --- /fermer_votes (ADMIN)
@bot.tree.command(name="fermer_votes", description="Ferme la phase de vote (ADMIN seulement)")
async def close_votes(interaction: discord.Interaction):
    member = interaction.user
    if not is_admin(member):
        await interaction.response.send_message("❌ Tu dois avoir le rôle ADMIN pour utiliser cette commande.", ephemeral=True)
        return
    data = load_data()
    if not data.get("active", False):
        await send_ephemeral_cleanup(interaction, "⚠️ Les votes ne sont pas ouverts.")
        return
    data["active"] = False
    save_data(data)
    await send_ephemeral_cleanup(interaction, "✅ Votes fermés.")

# --- /reset_votes (ADMIN)
@bot.tree.command(name="reset_votes", description="Réinitialise tous les votes et coefficients (ADMIN seulement)")
async def reset_votes(interaction: discord.Interaction):
    member = interaction.user
    if not is_admin(member):
        await interaction.response.send_message("❌ Tu dois avoir le rôle ADMIN pour utiliser cette commande.", ephemeral=True)
        return
    data = load_data()
    for i in range(1,5):
        data["sets"][str(i)]["votes"] = {}
        data["sets"][str(i)]["coeffs"] = {arena: 1 for arena in ARENAS}
    data["active"] = False
    data["last_messages"] = []
    save_data(data)
    await send_ephemeral_cleanup(interaction, "✅ Votes et coefficients réinitialisés.")

# --- /verifier_votes (ADMIN)
@bot.tree.command(name="verifier_votes", description="Affiche la liste des capitaines ayant déjà voté pour le set indiqué (ADMIN seulement)")
@app_commands.describe(set_number="Numéro du set (1-4)")
async def verify_votes(interaction: discord.Interaction, set_number: str):
    member = interaction.user
    if not is_admin(member):
        await interaction.response.send_message("❌ Tu dois avoir le rôle ADMIN pour utiliser cette commande.", ephemeral=True)
        return
    if set_number not in {"1","2","3","4"}:
        await interaction.response.send_message("❌ set doit être 1, 2, 3 ou 4.", ephemeral=True)
        return
    data = load_data()
    votes = data["sets"][set_number]["votes"]
    if not votes:
        await send_ephemeral_cleanup(interaction, f"ℹ️ Aucun capitaine n'a encore voté pour le set {set_number}.")
        return
    lines = []
    for uid, info in votes.items():
        lines.append(f"- {info.get('user','<inconnu>')} (favoris: {', '.join(info.get('favors',[]))} ; bans: {', '.join(info.get('bans',[]))})")
    message = "Capitaines ayant voté pour le set {} :\n{}".format(set_number, "\n".join(lines))
    # si long, on pourra envoyer en plusieurs messages, mais normalement <=3
    await send_ephemeral_cleanup(interaction, message)

# ---------- Start bot ----------
if __name__ == "__main__":
    token = os.environ.get(TOKEN_ENV)
    if not token:
        print("Erreur: token manquant. Ajoute le token dans la variable d'environnement DISCORD_TOKEN.")
    else:
        # sync commands to guild(s) quickly during testing (optional)
        # Pour tests en solo : tu peux remplacer None par guild=discord.Object(id=GUILD_ID) pour déployer plus vite
        async def setup():
            await bot.wait_until_ready()
            try:
                await bot.tree.sync()
                print("Commands synced.")
            except Exception as e:
                print("Erreur sync:", e)
        bot.loop.create_task(setup())
        bot.run(token)
