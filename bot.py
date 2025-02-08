import os
import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
from collections import defaultdict
import asyncio
import json


# Bot token beolvasása környezeti változóból (vagy beírhatod közvetlenül)
TOKEN = "MTMzNjc2OTc1NTQ2NTY0NjIwMw.GMwQ68.tgC4_WczjEfWiJr2ZRY9pugvK7IwpWV5AXUhX0"  # vagy: TOKEN = "IDE_ÍRD_A_TOKENED"

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
schedule_channel_id = 1337861261739823275  # A "SH schedule" csatorna ID-ja (tesztszerveren)
role_id = 1337856047351595100
user_lock = set()  # Azok a felhasználók, akik éppen reagálnak

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
@bot.command()
async def send(ctx):
    """Teszt parancs: azonnal elküldi a napi kérdést a kijelölt csatornába."""
    channel = bot.get_channel(schedule_channel_id)
    if channel is None:
        await ctx.send("Hibás csatorna ID vagy nem találom a csatornát.")
        return
    
    # Napi üzenet
    channel = bot.get_channel(schedule_channel_id)
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
    
    # Tároljuk a message id-t
    global daily_message_id
    daily_message_id = message.id
    
    # Ürítjük az előző adathalmazt (új nap, új adatok)
    global reaction_data
    reaction_data = {}
    
    # A bot automatikusan hozzáadja a reakciókat
    for emoji in REACTIONS.keys():
        await message.add_reaction(emoji)

    #await ctx.send("Napi SH üzenet elküldve.")

@bot.event
async def on_raw_reaction_add(payload):
    if payload.message_id != daily_message_id:
        return
    if payload.user_id == bot.user.id:
        return

    user_id = payload.user_id
    emoji = str(payload.emoji.name)

    # Ha a user már zárolva van, addig minden új reakciót törlünk
    if user_id in user_lock:
        channel = bot.get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
        user = await bot.fetch_user(user_id)
        await message.remove_reaction(emoji, user)
        return

    if emoji not in REACTIONS:
        return

    channel = bot.get_channel(payload.channel_id)
    message = await channel.fetch_message(payload.message_id)
    user = await bot.fetch_user(user_id)

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
            # (opcionálisan kis szünet)
            await asyncio.sleep(0.3)
            # Utólagos ellenőrzés – ha valaki extragyorsan mégis time-ot nyomott
            # a fentiek remove-jai közben:
            for e in list(user_reactions):
                if e in TIME_EMOJIS:
                    user_reactions.remove(e)
                    await message.remove_reaction(e, user)

            # 2) Végül hozzáadjuk a ❌-et
            user_reactions.add(NOT_EMOJI)
            print(f"[INFO] User {user_id} végleges reakcióhalmaz (❌ után): {user_reactions}")
            # Ha bármelyik reakció is van, lenullázzuk a streaket
            if missed_streak[user_id] > 0:
                missed_streak[user_id] = 0
                print(f"[INFO] {user_id} streak nullázva (x reagál).")
        finally:
            # Oldjuk a lockot
            user_lock.remove(user_id)

    # Ha a user time-reakciót nyom
    elif emoji in TIME_EMOJIS:
        # Ha benn van a ❌ a setjében, töröljük
        if NOT_EMOJI in user_reactions:
            user_reactions.remove(NOT_EMOJI)
            await message.remove_reaction(NOT_EMOJI, user)

        # Hozzáadjuk az új time-reakciót
        user_reactions.add(emoji)
        print(f"[INFO] User {user_id} végleges reakcióhalmaz (time hozzáadva): {user_reactions}")

        # Ha reagál, nullázzuk a streaket
        if missed_streak[user_id] > 0:
            missed_streak[user_id] = 0
            print(f"[INFO] {user_id} streak nullázva (time reagál).")


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
async def evaluate(ctx):
    """
    Kiértékelés + (nem reagált + mulasztásnövelés).
    Ha valaki 5/5 lesz, kap figyelmeztetést DM-ben,
    ha 6/6, elveszti a rangot.
    """
    # Először kinyerjük a guild-et (és a csatornát) a contextből, vagy a schedule_channel_id alapján
    channel = bot.get_channel(schedule_channel_id)
    guild = channel.guild

    # Két segédtároló: egy számláló és egy userlista
    counts = {}
    emoji_users = defaultdict(list)

    # Végigmegyünk a user -> emoji_halmaz szerkezeten
    for user_id, emojis in reaction_data.items():
        # Megpróbáljuk lekérni a guild-tag objektumot
        member = guild.get_member(user_id)
        # Ha valamiért nincs a szerveren (pl. kilépett), akkor None lehet
        if not member:
            continue

        # Minden egyes emojihoz incrementáljuk a számlálót és hozzácsapjuk a user mentiont
        for e in emojis:
            counts[e] = counts.get(e, 0) + 1
            emoji_users[e].append(member.mention)

    # Létrehozzuk az összefoglaló szöveget
    summary = "A mai SH időpontok:\n"
    for emoji, time_str in REACTIONS.items():
        c = counts.get(emoji, 0)
        if c > 0:
            # Ha van legalább 1 fő, soroljuk fel a user(ek)et
            user_list = emoji_users[emoji]
            user_str = ", ".join(user_list)
            summary += f"{time_str}: {c} fő ({user_str})\n"
        else:
            summary += f"{time_str}: 0 fő\n"
    
    
    # Megnézzük, kik EGYÁLTALÁN nem reagáltak
    #for role_ in guild.roles:
    #    print(f"Role found: {role_.name}")

    role = guild.get_role(role_id)
    for member in role.members:
            print(f"Checking member: {member.name}")
    
    if role is None:
        summary += "\nNem találom a SH-résztvevő szerepet."
    else:
        not_responded = []
        for member in role.members:
            if member.bot:
                continue
            # Ha valaki NINCS a reaction_data kulcsai közt, akkor nem reagált semmit
            if member.id not in reaction_data:
                not_responded.append(member)
        if not_responded:
            
            entries = []
            lost_roles = []  # ÚJ lista az SH-rangot elvesztő felhasználók számára
            
            for mem in not_responded:
                increment_missed(mem.id)
                s = missed_streak[mem.id]
                # Ha 6 vagy több a mulasztás, elveszti a rangot
                if s >= 6:
                    try:
                        await mem.remove_roles(role)
                        try:
                            await mem.send("Elvesztetted az SH rangot (6/6 mulasztás).")
                        except:
                            pass
                        lost_roles.append(mem.mention)
                        # Töröljük a user adatait a missed_streak-ből és a reaction_data-ból
                        if mem.id in missed_streak:
                            del missed_streak[mem.id]
                            save_missed_streak(missed_streak)
                        if mem.id in reaction_data:
                            del reaction_data[mem.id]
                    except discord.Forbidden:
                        await channel.send(f"Nem tudom levenni a rangot {mem.mention}-ről.")
                elif s == 5:
                    try:
                        await mem.send(
                            "Figyelem! Ez már az 5. mulasztásod. Ha még egyszer nem reagálsz, elveszíted az SH rangot."
                        )
                    except:
                        pass
                    entries.append(f"{mem.mention} **({s}/5)**❗")
                
                else:
                    entries.append(f"{mem.mention} ({s}/5)")
            if entries:
                summary += "\n**Nem reagált:** " + ", ".join(entries)
            # Az SH-rangot elvesztett felhasználók összegyűjtése
            if lost_roles:
                summary += "\nSH-rangot elvesztette: " + ", ".join(lost_roles)
        else:
            summary += "\nMindenki reagált! 👍"
        summary += "\n"
    
    # Megállapítjuk, mely idősávok érik el a REQUIRED_PLAYERS limitet
    valid_times = []
    for emoji, time_str in REACTIONS.items():
        if emoji != "❌" and counts.get(emoji, 0) >= REQUIRED_PLAYERS:
            valid_times.append(time_str)
    #valid_times = ["18-19", "19-20", "20-21", "21-22", "22-től"]
    if valid_times:
        time_str = valid_times[0].split('-')[0]
        summary += "\n✅ **INDUL** az SH ma **" + time_str + "** órától! ✅\n"
    else:
        summary += "\n‼️ Figyelem! Az SH a mai napon **ELAMRAD** ‼️\n"
    
    await ctx.send(summary)

@bot.command()
async def dm_reminder(ctx):
    """
    Minden @SH-tag, aki NEM reagált, kap egy DM-et.
    """
    channel = bot.get_channel(schedule_channel_id)
    guild = channel.guild
    role = guild.get_role(role_id)

    if not role:
        await ctx.send("Nincs SH szerep a szerveren!")
        return

    # Kikeressük a nem reagáltakat
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
                    "Szia! Még nem reagáltál a mai SH-felmérésre. "
                    "Kérlek jelölj be egy időpontot vagy a ❌ reakciót, ha nem érsz rá!"
                )
                count += 1
            except:
                pass
        await ctx.send(f"Összesen {count} főnek küldtem DM-emlékeztetőt.")
    else:
        await ctx.send("Minden SH-tag reagált, nincs kinek emlékeztetőt küldeni.")


# Indítsd a botot
def main():
    bot.run(TOKEN)

if __name__ == "__main__":
    main()
