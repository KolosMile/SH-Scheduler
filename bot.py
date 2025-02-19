import os
import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta, time
from collections import defaultdict
from dotenv import load_dotenv, find_dotenv
import asyncio
import json
from asyncio import Lock


# A régi load_dotenv() hívás helyett:
load_dotenv(dotenv_path=find_dotenv(), override=True)
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
print(f"Token betöltve a .env fájlból: {TOKEN[:10]}..." if TOKEN else "Token nem található!")
if TOKEN is None:
    raise ValueError("A DISCORD_BOT_TOKEN nincs beállítva a .env fájlban!")
SERVER = os.getenv('SERVER_NAME')
if SERVER is None:
    raise ValueError("A SERVER nincs beállítva a .env fájlban!")
# Fájl, ahová mentjük a missed_streak-et
STORAGE_FILES = {
    "Scheff": "server_data/missed_streak.json",
    "Test": "server_data/missed_streak_test.json"
}
STORAGE_FILE = STORAGE_FILES[SERVER]

def load_missed_streak():
    """Beolvassa a mulasztási adatokat a megfelelő STORAGE_FILE-ból."""
    storage_file = STORAGE_FILES[SERVER]
    if not os.path.exists(storage_file):
        return {}
    with open(storage_file, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            # JSON-ban string key-k lesznek, intté konvertáljuk
            # s = data.get("user_id_str")
            # Érték: int
            new_dict = {int(k): v for k, v in data.items()}
            return new_dict
        except:
            return {}
        
def save_missed_streak(missed_data):
    """Elmenti a mulasztási adatokat a megfelelő STORAGE_FILE-ba JSON-ben."""
    storage_file = STORAGE_FILES[SERVER]
    with open(storage_file, "w", encoding="utf-8") as f:
        json.dump(missed_data, f, ensure_ascii=False, indent=2)

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.reactions = True
intents.guilds = True
intents.members = True

class MyBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reaction_lock = None

    async def setup_hook(self):
        self.reaction_lock = asyncio.Lock()

bot = MyBot(command_prefix="!", intents=intents)

# Itt tároljuk a fontos adatokat (például reakciók, ki reagált, stb.)
# Később fájlba is mentheted (JSON), hogy ne vesszen el a leállítás után.
reaction_data = defaultdict(set)  # user_id -> {emoji1, emoji2, ...}
missed_streak = load_missed_streak() # user_id -> missed_count
daily_message_id = None  # Az utolsó kiküldött napi üzenet azonosítója

channel_ids = {
    "Scheff": 1339145626948075530, 
    "Test": 1336779385017073806
    }

role_ids = {
    "Scheff": 1337856047351595100,
    "Test": 1336764986344865895
    }

schedule_channel_id = channel_ids[SERVER]   # Az ütemezett üzenetek csatornája
role_id = role_ids[SERVER]  # Az SH rang ID-je
role_id_clan = 830498818113798215
user_lock = set()  # Azok a felhasználók, akik éppen reagálnak

message_time = {
    "send": time(hour=5, minute=0, second=0), 
    "reminder": time(hour=15, minute=45, second=0),
    "evaluate": time(hour=16, minute=45, second=0)
    }  # Az üzenet pontos időpontja

# Azok a reakciók, amelyek IDŐPONTOT jelölnek
TIME_EMOJIS = {"1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"}
NOT_EMOJI = "❌"

# Konfiguráció: milyen reakciókat használjunk, mit jelentenek
# Példa: 5 idősáv, + 1 "nem érek rá" reakció
REACTIONS = {
    "1️⃣": "18-19",
    "2️⃣": "19-20",
    "3️⃣": "20-22",
    "4️⃣": "21-22",
    "5️⃣": "22-től",
    "❌": "Nem érek rá"
}
REQUIRED_PLAYERS = 7  # minimum létszám

def increment_missed(user_id: int):
    """Megnöveli user mulasztási számlálóját, és azonnal menti."""
    if user_id not in missed_streak:
        missed_streak[user_id] = 0
    missed_streak[user_id] += 1
    save_missed_streak(missed_streak)  # Mentés fájlba

def reset_missed(user_id: int):
    """Lenullázza user mulasztási számlálóját, és elmenti."""
    if user_id in missed_streak and missed_streak[user_id] > 0:
        missed_streak[user_id] = 0
        save_missed_streak(missed_streak)


# Minden nap 9:00-kor küldi ki a bot az üzenetet
# Windows alatt (teszteléshez) manuálisan is meghívhatod ezt a függvényt parancsra, pl. !send
async def send_daily_message():
    """Napi SH üzenet kiküldése"""
    channel = bot.get_channel(schedule_channel_id)
    if channel is None:
        print("Hibás csatorna ID vagy nem található a csatorna.")
        return
        
    guild = channel.guild
    role = guild.get_role(role_id)
    role_mention = role.mention if role else "@SH"
    text = (
        f"{role_mention} **Ma ( {datetime.now().strftime('%Y-%m-%d')} ) "
        "mikor értek rá SH-ra? Reakciókkal jelöljétek!**\n\n"
        "1️⃣ - 18-19\n"
        "2️⃣ - 19-20\n"
        "3️⃣ - 20-21\n"
        "4️⃣ - 21-22\n"
        "5️⃣ - 22-től\n"
        "❌ - Nem érek rá\n\n"
        "Kérlek **legalább egy** reakciót tegyél!"
    )
    message = await channel.send(text)
    
    global daily_message_id
    daily_message_id = message.id
    
    global reaction_data
    reaction_data = {}
    
    for emoji in REACTIONS.keys():
        await message.add_reaction(emoji)

@bot.command()
async def send(ctx):
    """Manuális parancs a napi üzenet kiküldéséhez"""
    await send_daily_message()
    
@tasks.loop(time=message_time["send"])
async def scheduled_send():
    await send_daily_message()


@bot.event
async def on_raw_reaction_add(payload):
    if payload.message_id != daily_message_id:
        return
    if payload.user_id == bot.user.id:
        return

    user_id = payload.user_id
    emoji = str(payload.emoji.name)

    async with bot.reaction_lock:

        channel = bot.get_channel(payload.channel_id)   
        message = await channel.fetch_message(payload.message_id)
        user = await bot.fetch_user(user_id)
        guild = channel.guild
        member = guild.get_member(user_id)
        username = member.display_name if member else f"User_{user_id}"
        
        # Ha a reakció nincs a listában, töröljük
        if emoji not in REACTIONS and emoji not in TIME_EMOJIS:
            try:
                await message.remove_reaction(emoji, user)
            except Exception as e:
                print(f"[ERROR] Failed to remove reaction {emoji} from user {username}: {e}")
            return

        # Ha nincs még set, hozzunk létre
        if user_id not in reaction_data:
            reaction_data[user_id] = set()
        user_reactions = reaction_data[user_id]

        # Ha a user épp a ❌-et nyomta
        if emoji == NOT_EMOJI:
            # Töröljük a usernél az összes time-reakciót
            for e in list(user_reactions):
                if e in TIME_EMOJIS:
                    user_reactions.remove(e)
                    await message.remove_reaction(e, user)
            user_reactions.add(NOT_EMOJI)
            print(f"[ADD] {username} hozzáadta: ❌ . Set: {user_reactions}")

        # Ha a user time-reakciót nyom
        elif emoji in TIME_EMOJIS:
            if NOT_EMOJI in user_reactions:
                user_reactions.remove(NOT_EMOJI)
                await message.remove_reaction(NOT_EMOJI, user)
            user_reactions.add(emoji)
            print(f"[ADD] {username} hozzáadta: {emoji} . Set: {user_reactions}")


@bot.event
async def on_raw_reaction_remove(payload):
    """
    Akkor fut le, ha valaki levesz egy reakciót.
    """
    if payload.message_id != daily_message_id:
        return
    if payload.user_id == bot.user.id:
        return

    user_id = payload.user_id
    emoji = str(payload.emoji.name)

    async with bot.reaction_lock:
        channel = bot.get_channel(payload.channel_id)
        guild = channel.guild
        member = guild.get_member(user_id)
        username = member.display_name if member else f"User_{user_id}"
        
        # Ha a reaction az általunk figyelt halmazban van:
        if emoji in REACTIONS:
            if user_id in reaction_data and emoji in reaction_data[user_id]:    # ha mar a remove ciklusban toroljuk a reakciot, akkor nem kell ujra torolni
                reaction_data[user_id].remove(emoji)
                if not reaction_data[user_id]:
                    del reaction_data[user_id]
                print(f"[REMOVE] {username} eltávolította: {emoji} . Set: {reaction_data.get(user_id, set())}")


async def evaluate_daily():
    """Napi SH kiértékelése"""
    channel = bot.get_channel(schedule_channel_id)
    guild = channel.guild
    messages = []  # Itt gyűjtjük az üzeneteket

    # Nem reagálók kezelése
    role = guild.get_role(role_id)
    if role is None:
        messages.append("\nNem találom a SH-résztvevő rangot.")
        return await send_messages(channel, messages)

    not_responded = []
    for member in role.members:
        if not member.bot and member.id not in reaction_data:
            not_responded.append(member)

    # Missed streak kezelése
    modified = False
    for user_id in list(missed_streak.keys()):
        if user_id in reaction_data:
            del missed_streak[user_id]
            modified = True

    if not_responded:
        current_msg = f"\u200b\n## **Nem reagált ({len(not_responded)}/{len(role.members)}) SH-tag:**\n"
        current_msg += f"\n"
        names = ""
        lost_roles = []

        for mem in not_responded:
            if mem.id not in missed_streak: 
                missed_streak[mem.id] = 0
            missed_streak[mem.id] += 1
            modified = True
            s = missed_streak[mem.id]
            
            if s >= 6:
                try:
                    await mem.remove_roles(role)
                    await mem.send("Elvesztetted az SH rangot, egymást követő 6 alkalommal mulasztottad el a reagálást.")
                    lost_roles.append(mem.mention)
                    del missed_streak[mem.id]
                    modified = True
                except:
                    pass
            else:
                user_str = f"{mem.mention} ({s}/5)"
                if s == 5:
                    user_str = f"{mem.mention} **({s}/5)**❗"
                    try:
                        await mem.send("Figyelem! Ez már az 5. mulasztásod. Ha még egyszer nem reagálsz, el fogod veszíteni az SH rangot.")
                    except:
                        pass
                
                if len(names + user_str + ", ") > 1900:
                    messages.append(current_msg + names.rstrip(", "))
                    names = user_str + ", "
                else:
                    names += user_str + ", "
        
        if names:
            messages.append(current_msg + names.rstrip(", "))
        
        if lost_roles:
            current_msg = "\u200b\n**SH-rangot elvesztette:**\n"
            names = ""
            for user in lost_roles:
                if len(names + user + ", ") > 1900:
                    messages.append(current_msg + names.rstrip(", "))
                    names = user + ", "
                else:
                    names += user + ", "
            if names:
                messages.append(current_msg + names.rstrip(", "))
    else:
        messages.append(f"\u200b\n**Mind a(z) {len(role.members)} tankos reagált 🔥**")

    if modified:
        save_missed_streak(missed_streak)

    counts = {}
    emoji_users = defaultdict(list)

    for user_id, emojis in reaction_data.items():
        member = await guild.fetch_member(user_id)
        if not member:
            continue
        for e in emojis:
            counts[e] = counts.get(e, 0) + 1
            emoji_users[e].append(member.mention)

    # Első üzenet: Fejléc
    messages.append("\u200b\n## **A mai SH létszám:**\n")

    # Az evaluate_daily függvényben:
    for emoji, time_str in REACTIONS.items():
        c = counts.get(emoji, 0)
        if c > 0:
            current_msg = f"\u200b\n## **{time_str} ───────────**\n"  # Vizuális elválasztó
            current_msg += f"Létszám: **{c}** fő\n"         # Külön sorban a létszám
            current_msg += f"Jelentkezők:\n"            # Külön sorban a nevek
            user_list = emoji_users[emoji]
            names = ""
            
            # Nevek feldolgozása az időponthoz
            for user in user_list:
                if len(names + user + "\n") > 1900:  # Minden név új sorba
                    messages.append(current_msg + names)
                    names = user + "\n"
                    current_msg = f"{time_str} (folytatás):\n"
                else:
                    names += user + "\n"
            
            if names:
                messages.append(current_msg + names)
        else:
            messages.append(f"\n{time_str} **(-)**\n")


    # Végső összesítés
    valid_times = []
    for emoji, time_str in REACTIONS.items():
        if emoji != "❌" and counts.get(emoji, 0) >= REQUIRED_PLAYERS:
            valid_times.append(time_str)

    if valid_times:
        time_str = valid_times[0].split('-')[0]
        messages.append(f"\u200b\n# ✅ **INDUL** az SH ma **{time_str}** órától! ✅")
    else:
        messages.append("\u200b\n# ‼️ Az SH ma **ELMARAD** ‼️")

    # Üzenetek kiküldése
    await send_messages(channel, messages)

async def send_messages(channel, messages):
    """Üzenetek kiküldése egymás után"""
    for msg in messages:
        if msg.strip():  # Csak akkor küldjük, ha nem üres
            await channel.send(msg)

@bot.command()
async def evaluate(ctx):
    """Manuális parancs a napi kiértékeléshez"""
    await evaluate_daily()

@tasks.loop(time=message_time["evaluate"])
async def scheduled_evaluate():
    await evaluate_daily()

async def send_dm_reminder():
    """DM emlékeztető küldése a nem reagált tagoknak"""
    channel = bot.get_channel(schedule_channel_id)
    guild = channel.guild
    role = guild.get_role(role_id)

    if not role:
        print("Nincs SH szerep a szerveren!")
        return

    not_responded = []
    for mem in role.members:
        if mem.bot:
            continue
        if mem.id not in reaction_data:
            not_responded.append(mem)

    if not_responded:
        count = 0
        for mem in not_responded:
            try:
                await mem.send(
                    "Még nem reagáltál a mai SH-felmérésre. "
                    "Kérlek jelölj be egy időpontot vagy a ❌ reakciót, ha nem érsz rá!"
                )
                count += 1
            except:
                pass
        print(f"Összesen {count} főnek küldtem DM-emlékeztetőt.")
    else:
        print("Minden SH-tag reagált, nincs kinek emlékeztetőt küldeni.")

@bot.command()
async def dm_reminder(ctx):
    """Manuális parancs DM emlékeztető küldéséhez"""
    await send_dm_reminder()

@tasks.loop(time=message_time["reminder"])
async def scheduled_reminder():
    await send_dm_reminder()

async def check_and_rebuild():
    """Ellenőrzi az utolsó üzenetet és szükség esetén újraépíti a reaction_data-t"""
    channel = bot.get_channel(schedule_channel_id)

    if not channel:
        return
    
    try:
        # Utolsó 10 üzenet lekérése
        messages = [msg async for msg in channel.history(limit=20)]
        # Keressük meg az utolsó bot által küldött üzenetet
        for message in messages:
            if message.author == bot.user and any(emoji in message.content for emoji in REACTIONS.keys()):
                # Ellenőrizzük, hogy volt-e már kiértékelés
                async for msg in channel.history(limit=20, after=message):
                    if msg.author == bot.user and ("**INDUL**" in msg.content or "**ELMARAD**" in msg.content):
                        print("Az utolsó üzenet már ki volt értékelve.")
                        return
                
                print(f"Találtam egy ki nem értékelt üzenetet (ID: {message.id})")
                # Ha nincs kiértékelés, újraépítjük a reaction_data-t
                global daily_message_id
                daily_message_id = message.id
                await rebuild_reactions_data(message.id)
                return
                
    except Exception as e:
        print(f"Hiba történt az utolsó üzenet ellenőrzésekor: {e}")

@bot.event
async def on_ready():
    print(f"bot elindult a(z) {SERVER}-szerveren!")
    await check_and_rebuild()
    scheduled_send.start()
    scheduled_evaluate.start()
    scheduled_reminder.start()

async def rebuild_reactions_data(message_id: int):
    """Újraépíti a reaction_data-t egy adott üzenet ID alapján"""
    channel = bot.get_channel(schedule_channel_id)
    message = await channel.fetch_message(message_id)
    guild = channel.guild
    
    # Reaction data újraépítése
    global reaction_data, daily_message_id
    reaction_data.clear()
    daily_message_id = message_id
    
    for reaction in message.reactions:
        emoji = str(reaction.emoji)
        if emoji in REACTIONS:
            async for user in reaction.users():
                if not user.bot:
                    if user.id not in reaction_data:
                        reaction_data[user.id] = set()
                    reaction_data[user.id].add(emoji)
    

    print(f"Reaction data újraépítve:")
    for user_id, reactions in reaction_data.items():
        member = guild.get_member(user_id)
        username = member.display_name if member else f"User_{user_id}"
        print(f"{username}: {reactions}")

    return reaction_data

@bot.command()
async def clear(ctx, amount: int):
    if ctx.author.guild_permissions.manage_messages:  # Jogosultság ellenőrzése
        deleted = await ctx.channel.purge(limit=amount)
        await ctx.send(f"{len(deleted)} üzenet törölve!", delete_after=5)
    else:
        await ctx.send("Nincs jogosultságod az üzenetek törlésére!", delete_after=5)

@bot.command()
async def delete_message(ctx, message_id: int):
    """Töröl egy üzenetet az ID alapján (csak ha a bot küldte)"""
    try:
        channel = bot.get_channel(schedule_channel_id)
        message = await channel.fetch_message(message_id)
        
        # Ellenőrizzük, hogy a bot küldte-e az üzenetet
        if message.author == bot.user:
            await message.delete()
            await ctx.send(f"Üzenet törölve (ID: {message_id})", delete_after=5)
        else:
            await ctx.send("Ezt az üzenetet nem törölhetem, mert nem én küldtem.", delete_after=5)
            
    except discord.NotFound:
        await ctx.send("Nem található ilyen ID-jű üzenet.", delete_after=5)
    except discord.Forbidden:
        await ctx.send("Nincs jogosultságom törölni ezt az üzenetet.", delete_after=5)
    except Exception as e:
        await ctx.send(f"Hiba történt az üzenet törlésekor: {e}", delete_after=5)

@bot.command()
async def member(ctx):
    print("Checking members")
    # Először kinyerjük a guild-et (és a csatornát) a contextből, vagy a schedule_channel_id alapján
    channel = bot.get_channel(schedule_channel_id)
    guild = channel.guild
    role = guild.get_role(role_id)
    for member in role.members:
            print(f"Checking member: {member.name}")

@bot.command()
async def checkall(ctx):
    guild = ctx.guild
    role = guild.get_role(role_id)
    if not role:
        print("Nincs is ilyen szerep!")
        return
    
    # Megnézzük minden tagot:
    for member in guild.members:
        if role in member.roles:
            print(f"{member} szerepben: IGEN, roles={member.roles}")
        else:
            print(f"{member} szerepben: NEM, roles={member.roles}")
    
    await ctx.send("Checkall parancs lefutott. Nézd a konzolt!")

@bot.command()
async def checkuserroles(ctx, user_id: int):
    guild = ctx.guild
    member = guild.get_member(user_id)
    if not member:
        await ctx.send(f"Nem találok a szerveren ilyen ID-jű tagot: {user_id}")
        return
    
    role_names = [role.name for role in member.roles]
    # Vagy megjelenítheted a role ID-ket is, ha szeretnéd
    # role_data = [f"{role.name} (ID: {role.id})" for role in member.roles]
    
    print(f"Felhasználó: {member} | Rangjai: {role_names}")
    await ctx.send(f"{member.mention} rangjai: {', '.join(role_names)}")

@bot.command()
async def add_sh_role(ctx):
    """Parancs, amely az összes role_id2-vel rendelkező felhasználónak megadja a role_id1 rangot."""
    guild = ctx.guild
    role1 = guild.get_role(role_id)  # role_id1
    role2 = guild.get_role(role_id_clan)    # role_id2
    
    if not role1 or not role2:
        await ctx.send("Egy vagy több szerep nem található a szerveren!")
        return

    count = 0
    for member in guild.members:
        if role2 in member.roles and role1 not in member.roles:
            try:
                await member.add_roles(role1)
                count += 1
                print(f"SH rang hozzáadva: {member.name}")
            except discord.Forbidden:
                print("Nem tudom hozzáadni a rangot {member.mention}-nek.")
            except Exception as e:
                print(f"Hiba történt {member.name} SH rangjának hozzáadásakor: {e}")
    
    print(f"Összesen {count} felhasználónak adtam meg az SH rangot.")

@bot.command()
async def rebuild_and_evaluate(ctx, message_id: int):
    """Újraépíti a reaction_data-t egy adott üzenet ID alapján és kiértékeli"""
    channel = bot.get_channel(schedule_channel_id)
    message = await channel.fetch_message(message_id)
    
    # Reaction data újraépítése
    global reaction_data
    reaction_data.clear()
    
    for reaction in message.reactions:
        emoji = str(reaction.emoji)
        if emoji in REACTIONS:
            async for user in reaction.users():
                if not user.bot:
                    if user.id not in reaction_data:
                        reaction_data[user.id] = set()
                    reaction_data[user.id].add(emoji)
    
    print("Reaction data újraépítve:")
    for user_id, reactions in reaction_data.items():
        print(f"User {user_id}: {reactions}")
    
    # Missed streak tisztítása
    cleaned = 0
    for user_id in list(missed_streak.keys()):
        if user_id in reaction_data:
            del missed_streak[user_id]
            cleaned += 1

    save_missed_streak(missed_streak)
    
    print(f"\nMissed streak tisztítva ({cleaned} felhasználó törölve)")
    
    # Kiértékelés részekre bontva
    guild = channel.guild
    counts = {}
    emoji_users = defaultdict(list)
    
    for user_id, emojis in reaction_data.items():
        member = await guild.fetch_member(user_id)
        if not member:
            continue
        
        for e in emojis:
            counts[e] = counts.get(e, 0) + 1
            emoji_users[e].append(member.mention)
    
    # Üzenet részekre bontása
    messages = []
    current_msg = "A mai SH létszám:\n"
    
    # Időpontok és létszámok
    for emoji, time_str in REACTIONS.items():
        c = counts.get(emoji, 0)
        line = ""
        if c > 0:
            user_list = emoji_users[emoji]
            user_str = ", ".join(user_list)
            line = f"{time_str}: {c} fő ({user_str})\n"
        else:
            line = f"{time_str}: 0 fő\n"
            
        # Ha az új sor hozzáadásával túllépnénk a limitet
        if len(current_msg + line) > 1900:
            messages.append(current_msg)
            current_msg = line
        else:
            current_msg += line
    
    # Nem reagálók listája
    role = guild.get_role(role_id)
    not_responded = []
    for member in role.members:
        if not member.bot and member.id not in reaction_data:
            not_responded.append(member)
    
    if not_responded:
        not_resp_msg = "\n**Nem reagált:**\n"
        for mem in not_responded:
            line = f"{mem.mention} ({missed_streak.get(mem.id, 0)}/5)\n"
            if len(current_msg + not_resp_msg + line) > 1900:
                messages.append(current_msg)
                current_msg = not_resp_msg + line
                not_resp_msg = ""
            else:
                not_resp_msg += line
        current_msg += not_resp_msg
    else:
        current_msg += "\n**Mindenki reagált 🔥**"
    
    # Végső összesítés
    valid_times = []
    for emoji, time_str in REACTIONS.items():
        if emoji != "❌" and counts.get(emoji, 0) >= REQUIRED_PLAYERS:
            valid_times.append(time_str)
    
    summary = "\n\n"
    if valid_times:
        time_str = valid_times[0].split('-')[0]
        summary += f"✅ **INDUL** az SH ma **{time_str}** órától! ✅"
    else:
        summary += "‼️ Figyelem! Az SH ma **ELMARAD** ‼️"
    
    if len(current_msg + summary) > 1900:
        messages.append(current_msg)
        current_msg = summary
    else:
        current_msg += summary
    
    messages.append(current_msg)
    
    # Üzenetek kiírása print-tel
    print("\nKimeneti üzenetek:")
    for i, msg in enumerate(messages, 1):
        #print(f"\n--- Üzenet {i}/{len(messages)} ---")
        print(msg)
        #print(f"Karakterek száma: {len(msg)}")


# Indítsd a botot
def main():
    bot.run(TOKEN)

if __name__ == "__main__":
    main()
