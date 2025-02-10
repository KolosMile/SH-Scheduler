import os
import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta, time
from collections import defaultdict
from dotenv import load_dotenv
import asyncio
import json

load_dotenv()
# Bot token beolvasása környezeti változóból (vagy beírhatod közvetlenül)
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
if TOKEN is None:
    raise ValueError("The DISCORD_BOT_TOKEN environment variable is not set. Please set it and try again.")

# Fájl, ahová mentjük a missed_streak-et
STORAGE_FILE = "missed_streak.json"

def load_missed_streak():
    """Beolvassa a mulasztási adatokat a STORAGE_FILE-ból."""
    if not os.path.exists(STORAGE_FILE):
        return {}
    with open(STORAGE_FILE, "r", encoding="utf-8") as f:
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
    """Elmenti a mulasztási adatokat a STORAGE_FILE-ba JSON-ben."""
    with open(STORAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(missed_data, f, ensure_ascii=False, indent=2)

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.reactions = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Itt tároljuk a fontos adatokat (például reakciók, ki reagált, stb.)
# Később fájlba is mentheted (JSON), hogy ne vesszen el a leállítás után.
reaction_data = defaultdict(set)  # user_id -> {emoji1, emoji2, ...}
missed_streak = load_missed_streak() # user_id -> missed_count
daily_message_id = None  # Az utolsó kiküldött napi üzenet azonosítója

channel_ids = {
    "Scheff": 1337861261739823275, 
    "Test": 1336779385017073806
    }

role_ids = {
    "Scheff": 1337856047351595100,
    "Test": 1336764986344865895
    }

server = "Scheff"  # Teszt szerver
schedule_channel_id = channel_ids[server]   # Az ütemezett üzenetek csatornája
role_id = role_ids[server]  # Az SH rang ID-je
user_lock = set()  # Azok a felhasználók, akik éppen reagálnak

message_time = {
    "send": time(hour=1, minute=28, second=0), 
    "reminder": time(hour=1, minute=28, second=15),
    "evaluate": time(hour=1, minute=28, second=30)
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
        f"{role_mention} Ma ( {datetime.now().strftime('%Y-%m-%d')} ) "
        "mikor értek rá SH-ra? Reakciókkal jelöljétek!\n\n"
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

    channel = bot.get_channel(payload.channel_id)
    message = await channel.fetch_message(payload.message_id)
    user = await bot.fetch_user(user_id)

    # Ha a user már zárolva van, addig minden új reakciót törlünk
    if user_id in user_lock:
        await message.remove_reaction(emoji, user)
        return
    
    # Ha a reakció nincs a listában, töröljük
    if emoji not in REACTIONS and emoji not in TIME_EMOJIS:
        try:
            await message.remove_reaction(emoji, user)
        except Exception as e:
            print(f"[ERROR] Failed to remove reaction {emoji} from user {user_id}: {e}")
        return

    # Ha nincs még set, hozzunk létre
    if user_id not in reaction_data:
        reaction_data[user_id] = set()
    user_reactions = reaction_data[user_id]

    # Ha a user épp a ❌-et nyomta
    if emoji == NOT_EMOJI:
        # 1) Zároljuk a usert
        user_lock.add(user_id)
        try:
            # Töröljük a usernél az összes time-reakciót
            for e in list(user_reactions):
                if e in TIME_EMOJIS:
                    user_reactions.remove(e)
                    await message.remove_reaction(e, user)
            await asyncio.sleep(0.3)
            for e in list(user_reactions):
                if e in TIME_EMOJIS:
                    user_reactions.remove(e)
                    await message.remove_reaction(e, user)
            user_reactions.add(NOT_EMOJI)
            print(f"[INFO] User {user_id} végleges reakcióhalmaz (❌ után): {user_reactions}")
        finally:
            user_lock.remove(user_id)

    # Ha a user time-reakciót nyom
    elif emoji in TIME_EMOJIS:
        if NOT_EMOJI in user_reactions:
            user_reactions.remove(NOT_EMOJI)
            await message.remove_reaction(NOT_EMOJI, user)
        user_reactions.add(emoji)
        print(f"[INFO] User {user_id} végleges reakcióhalmaz (time hozzáadva): {user_reactions}")


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

    # Ha a reaction az általunk figyelt halmazban van:
    if emoji in REACTIONS:
        # Ha a user a reaction_data-ban létezik, és valóban az adott reakció van a halmazban, töröljük
        if user_id in reaction_data and emoji in reaction_data[user_id]:
            reaction_data[user_id].remove(emoji)
            # Ha üres maradt a user set-je, törölhetjük a kulcsot
            if not reaction_data[user_id]:
                del reaction_data[user_id]
            print(f"[REMOVE] User {user_id} eltávolította {emoji} reakciót. Jelenlegi set: {reaction_data.get(user_id, set())}")


async def evaluate_daily():
    """Napi SH kiértékelése"""
    channel = bot.get_channel(schedule_channel_id)
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

    summary = "A mai SH létszám:\n"
    for emoji, time_str in REACTIONS.items():
        c = counts.get(emoji, 0)
        if c > 0:
            user_list = emoji_users[emoji]
            user_str = ", ".join(user_list)
            summary += f"{time_str}: {c} fő ({user_str})\n"
        else:
            summary += f"{time_str}: 0 fő\n"
    
    role = guild.get_role(role_id)
    if role is None:
        summary += "\nNem találom a SH-résztvevő rangot."
        return await channel.send(summary)

    not_responded = []
    for member in role.members:
        if not member.bot and member.id not in reaction_data:
            not_responded.append(member)

    # Missed streak kezelése
    modified = False  # Jelzi ha változott a missed_streak
    
    # 1. Töröljük azokat akik reagáltak
    for user_id in list(missed_streak.keys()):
        if user_id in reaction_data:
            del missed_streak[user_id]
            modified = True
    
    # 2. Kezeljük a nem reagálókat
    if not_responded:
        entries = []
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
                except discord.Forbidden:
                    await channel.send(f"Nem tudom levenni a rangot {mem.mention}-ről.")
                except:
                    pass
            elif s == 5:
                try:
                    await mem.send("Figyelem! Ez már az 5. mulasztásod. Ha még egyszer nem reagálsz, el fogod veszíteni az SH rangot.")
                except:
                    pass
                entries.append(f"{mem.mention} **({s}/5)**❗")
            else:
                entries.append(f"{mem.mention} ({s}/5)")

        if entries:
            summary += "\n**Nem reagált:** " + ", ".join(entries)
        if lost_roles:
            summary += "\nSH-rangot elvesztette: " + ", ".join(lost_roles)
    
    # Végül, ha volt változás, mentjük a fájlba
    if modified:
        save_missed_streak(missed_streak)

    valid_times = []
    for emoji, time_str in REACTIONS.items():
        if emoji != "❌" and counts.get(emoji, 0) >= REQUIRED_PLAYERS:
            valid_times.append(time_str)

    if valid_times:
        time_str = valid_times[0].split('-')[0]
        summary += "\n✅ **INDUL** az SH ma **" + time_str + "** órától! ✅\n"
    else:
        summary += "\n‼️ Figyelem! Az SH ma **ELAMRAD** ‼️\n"
    
    await channel.send(summary)

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

# on_ready eventben indítás:
@bot.event
async def on_ready():
    print("Bot elindult!")
    scheduled_send.start()
    scheduled_evaluate.start()
    scheduled_reminder.start()


@bot.command()
async def clear(ctx, amount: int):
    if ctx.author.guild_permissions.manage_messages:  # Jogosultság ellenőrzése
        deleted = await ctx.channel.purge(limit=amount)
        await ctx.send(f"{len(deleted)} üzenet törölve!", delete_after=5)
    else:
        await ctx.send("Nincs jogosultságod az üzenetek törlésére!", delete_after=5)

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

# Indítsd a botot
def main():
    bot.run(TOKEN)

if __name__ == "__main__":
    main()
