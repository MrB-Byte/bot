import asyncio
import time
import os
from datetime import datetime, timedelta
from collections import Counter
import random
import string
import hashlib
import base64
from urllib.parse import quote
import html
import aiohttp
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters, CommandHandler, CallbackQueryHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from supabase import create_client, Client
from google import genai

# --- KONFIGURATION ---
# Keys werden jetzt aus den Environment-Variablen geladen (für Vercel)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8584873682:AAFNSd3dJ-kCj_uP-vUT0Iy7R5XS4tSQiok")
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID", "-1002027888526")
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://hocqzefbbnowautoldvw.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhvY3F6ZWZiYm5vd2F1dG9sZHZ3Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2OTY4NDU2NiwiZXhwIjoyMDg1MjYwNTY2fQ.fixKmVmcUNeqebl0IRpJO3ENUcbVQ1fqEJ3Ycv3vfQg")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyD6LTSd0Si8IfqD407ub4ZLhGAZazOCcxQ")

if not all([TELEGRAM_TOKEN, GROUP_CHAT_ID, SUPABASE_URL, SUPABASE_KEY, GEMINI_API_KEY]):
    raise ValueError("One or more environment variables are not set!")

# Enhanced Supabase client with connection stability
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = genai.Client(api_key=GEMINI_API_KEY)

# Connection status tracking
connection_status = {
    'is_connected': True,
    'last_error': None,
    'reconnect_attempts': 0,
    'max_reconnect_attempts': 5,
    'last_successful_operation': time.time()
}

async def execute_db_operation_with_retry(operation, max_retries=3, operation_name="database operation"):
    """Execute database operation with retry logic and connection monitoring"""
    global connection_status
    
    for attempt in range(max_retries + 1):
        try:
            # Add query timeout to prevent hanging
            result = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, operation),
                timeout=5.0  # 5 second timeout for database operations
            )
            
            # Update connection status on success
            if not connection_status['is_connected']:
                connection_status['is_connected'] = True
                connection_status['last_error'] = None
                connection_status['reconnect_attempts'] = 0
                print(f"✅ Database connection restored after {operation_name}")
            
            connection_status['last_successful_operation'] = time.time()
            return result
            
        except asyncio.TimeoutError:
            connection_status['last_error'] = f"Timeout after 5s"
            if attempt < max_retries:
                delay = min(1.5 ** attempt, 3)  # Faster exponential backoff, max 3s
                print(f"⏱️ {operation_name} timed out (attempt {attempt + 1}/{max_retries + 1})")
                print(f"   Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)
            else:
                connection_status['is_connected'] = False
                connection_status['reconnect_attempts'] += 1
                print(f"❌ {operation_name} timed out after {max_retries + 1} attempts")
                raise Exception(f"{operation_name} timed out after {max_retries + 1} attempts")
                
        except Exception as error:
            connection_status['last_error'] = str(error)
            
            if attempt < max_retries:
                delay = min(1.5 ** attempt, 3)  # Faster exponential backoff, max 3s
                print(f"⚠️ {operation_name} failed (attempt {attempt + 1}/{max_retries + 1}): {error}")
                print(f"   Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)
            else:
                connection_status['is_connected'] = False
                connection_status['reconnect_attempts'] += 1
                print(f"❌ {operation_name} failed after {max_retries + 1} attempts: {error}")
                raise Exception(f"{operation_name} failed after {max_retries + 1} attempts: {error}")

async def test_database_connection():
    """Test database connection health"""
    try:
        result = await execute_db_operation_with_retry(
            lambda: supabase.table("users").select("count", count="exact").execute(),
            max_retries=1,
            operation_name="connection health check"
        )
        return True
    except Exception:
        return False

def get_connection_health():
    """Get current database connection health status"""
    return {
        **connection_status,
        'timestamp': datetime.now().isoformat(),
        'time_since_last_success': time.time() - connection_status['last_successful_operation']
    }

async def send_long_message(target, text, parse_mode=None):
    """Sendet Nachrichten, die länger als 4096 Zeichen sind, in Stücken."""
    max_length = 4096
    for i in range(0, len(text), max_length):
        chunk = text[i:i+max_length]
        # target kann update.message oder context.bot sein (mit chat_id)
        # Hier vereinfacht für update.message.reply_text
        await target.reply_text(chunk, parse_mode=parse_mode)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sendet eine Willkommensnachricht und behandelt Web-Login."""
    user = update.message.from_user
    
    # Check if this is a web login request
    if context.args and context.args[0] == "weblogin":
        # Generate a temporary login code
        login_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        
        # Store login code in users table temporarily
        try:
            # Update user with login code and expiration
            user_data = {
                "id": str(user.id),
                "username": user.first_name,
                "login_code": login_code,
                "login_expires": (datetime.now() + timedelta(minutes=5)).isoformat(),
                "last_seen": datetime.now().isoformat()
            }
            await execute_db_operation_with_retry(
                lambda: supabase.table("users").upsert(user_data).execute(),
                operation_name="store login code in users table"
            )
            
            await update.message.reply_text(
                f"🔐 <b>Web-Login Code:</b>\n\n"
                f"<code>{login_code}</code>\n\n"
                f"Gib diesen Code auf der Website ein.\n"
                f"⏰ <i>Gültig für 5 Minuten</i>",
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"[Login Code Error] {e}")
            await update.message.reply_text(
                "❌ Fehler beim Generieren des Login-Codes. Bitte versuche es erneut."
            )
    else:
        # Normal start message
        await update.message.reply_text(
            "Willkommen beim MIB Mainframe Bot!\n"
            "Ich bin die Schnittstelle zum Forum. Nutze /help für eine Befehlsliste."
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sendet eine Hilfenachricht."""
    help_text = (
        "<b>MIB Mainframe Bot Hilfe</b>\n\n"
        "<b>#forum</b>\n"
        "Archiviert deine Textnachricht als permanenten Post im Forum.\n"
        "<i>Beispiel:</i> <code>Wichtige Ankündigung #forum</code>\n\n"
        "<b>#shout</b>\n"
        "Sendet deine Textnachricht live in die Shoutbox auf der Startseite.\n"
        "<i>Beispiel:</i> <code>Hallo an alle! #shout</code>\n\n"
        "<b>#upload</b>\n"
        "Lädt eine angehängte Datei in den 'Payloads'-Bereich hoch. Der Text wird zur Beschreibung.\n"
        "<i>Anwendung:</i> Sende eine Datei und schreibe in die Bildunterschrift <code>#upload</code>."
        "\n\n<b>#ai</b>\n"
        "Stelle eine Frage an die MIB-KI.\n"
        "<i>Beispiel:</i> <code>Was ist die Matrix? #ai</code>"
        "\n\n<b>/stats</b>\n"
        "Zeigt Statistiken des Mainframes an."
        "\n\n<b>/search</b>\n"
        "Durchsucht das Forum nach einem Begriff.\n"
        "<i>Beispiel:</i> <code>/search Linux</code>"
        "\n\n<b>/rank</b>\n"
        "Zeigt deinen aktuellen Rang und XP an."
        "\n\n<b>/report</b>\n"
        "Meldet eine Nachricht an die Admins (auf Nachricht antworten)."
        "\n\n<b>/birthday</b>\n"
        "Hinterlege deinen Geburtstag für Glückwünsche.\n"
        "<i>Beispiel:</i> <code>/birthday 24.12.1999</code>"
        "\n\n<b>/check</b>\n"
        "Prüft, ob eine URL/Stream erreichbar ist.\n"
        "<i>Beispiel:</i> <code>/check http://example.com</code>"
        "\n\n<b>/scene</b>\n"
        "Sucht nach Scene-Releases (Warez Datenbank).\n"
        "<i>Beispiel:</i> <code>/scene Matrix</code>"
        "\n\n<b>/tempmail</b>\n"
        "Erstellt eine Wegwerf-E-Mail-Adresse."
        "\n\n<b>/fakeid</b>\n"
        "Generiert eine deutsche Fake-Identität."
        "\n\n<b>/ip</b>\n"
        "Zeigt Infos zu IP oder Domain (Geo, ISP).\n"
        "<i>Beispiel:</i> <code>/ip 1.1.1.1</code>"
        "\n\n<b>/coin</b>\n"
        "Zeigt aktuellen Crypto-Kurs (Binance).\n"
        "<i>Beispiel:</i> <code>/coin BTC</code>"
        "\n\n<b>/port</b>\n"
        "Prüft, ob ein Port offen ist.\n"
        "<i>Beispiel:</i> <code>/port google.com 443</code>"
        "\n\n<b>/genpass</b>\n"
        "Erstellt ein sicheres Passwort."
        "\n\n<b>/encode & /decode</b>\n"
        "Base64 Tools für versteckte Links.\n"
        "<i>Beispiel:</i> <code>/decode aHR0cHM6Ly9...</code>"
        "\n\n<b>/qr</b>\n"
        "Erstellt einen QR-Code (z.B. für IPTV Links).\n"
        "<i>Beispiel:</i> <code>/qr https://mein-stream.com</code>"
        "\n\n<b>/blitzdings</b>\n"
        "Löscht die Erinnerung (und den Befehl).\n"
        "<i>Achtung:</i> Nur für MIB Agenten."
    )
    await update.message.reply_text(help_text, parse_mode="HTML")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Zeigt Statistiken des Mainframes an."""
    try:
        # Wir zählen die Einträge in den Tabellen (count='exact' gibt die Anzahl zurück)
        users_result = await execute_db_operation_with_retry(
            lambda: supabase.table("users").select("id", count="exact").execute(),
            operation_name="users count query"
        )
        posts_result = await execute_db_operation_with_retry(
            lambda: supabase.table("posts").select("id", count="exact").execute(),
            operation_name="posts count query"
        )
        downloads_result = await execute_db_operation_with_retry(
            lambda: supabase.table("downloads").select("id", count="exact").execute(),
            operation_name="downloads count query"
        )
        snippets_result = await execute_db_operation_with_retry(
            lambda: supabase.table("snippets").select("id", count="exact").execute(),
            operation_name="snippets count query"
        )
        
        users_count = users_result.count
        posts_count = posts_result.count
        downloads_count = downloads_result.count
        snippets_count = snippets_result.count
        
        # Add connection health info for admins
        health = get_connection_health()
        health_indicator = "🟢" if health['is_connected'] else "🔴"
        
        msg = (
            f"<b>📊 MIB Mainframe Status</b>\n\n"
            f"👥 <b>Agenten:</b> {users_count}\n"
            f"📝 <b>Forum Posts:</b> {posts_count}\n"
            f"💾 <b>Payloads:</b> {downloads_count}\n"
            f"💻 <b>Snippets:</b> {snippets_count}\n\n"
            f"{health_indicator} <b>DB Status:</b> {'Online' if health['is_connected'] else 'Degraded'}\n"
            f"<i>System läuft stabil.</i>"
        )
        await update.message.reply_text(msg, parse_mode="HTML")
    except Exception as e:
        print(f"[Stats Error] {e}")
        await update.message.reply_text("❌ Fehler beim Abrufen der Statistiken. Verbindung wird wiederhergestellt...")
        
        # Try to restore connection
        if await test_database_connection():
            await update.message.reply_text("✅ Datenbankverbindung wiederhergestellt. Bitte versuchen Sie es erneut.")
        else:
            await update.message.reply_text("⚠️ Datenbankverbindung instabil. Bitte warten Sie einen Moment.")

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Durchsucht das Forum nach einem Begriff."""
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("⚠️ Bitte Suchbegriff angeben: <code>/search Linux</code>", parse_mode="HTML")
        return

    await update.message.reply_chat_action("typing")
    
    results = []
    
    try:
        # Suche in Posts (ilike ist case-insensitive Suche)
        res_posts = supabase.table("posts").select("topic, content").ilike("content", f"%{query}%").limit(3).execute()
        for p in res_posts.data:
            preview = p['content'][:50] + "..." if len(p['content']) > 50 else p['content']
            results.append(f"📝 <b>Post ({p['topic']}):</b> {preview}")

        # Suche in Downloads
        res_dl = supabase.table("downloads").select("name, description").ilike("name", f"%{query}%").limit(3).execute()
        for d in res_dl.data:
            results.append(f"💾 <b>File:</b> {d['name']}")

        if results:
            await update.message.reply_text(f"🔍 <b>Suchergebnisse für '{query}':</b>\n\n" + "\n\n".join(results), parse_mode="HTML")
        else:
            await update.message.reply_text(f"❌ Nichts im Mainframe gefunden für '{query}'.")
            
    except Exception as e:
        print(f"[Search Error] {e}")
        await update.message.reply_text("❌ Fehler bei der Suche.")

async def add_xp(user_id: int, username: str, amount: int):
    """Fügt einem Nutzer XP hinzu."""
    try:
        # Aktuelle XP holen
        res = await execute_db_operation_with_retry(
            lambda: supabase.table("users").select("xp").eq("id", str(user_id)).execute(),
            operation_name="get user XP"
        )
        current_xp = 0
        if res.data:
            current_xp = res.data[0].get("xp", 0) or 0
        
        new_xp = current_xp + amount
        
        # Update (Upsert falls User noch nicht existiert)
        data = {
            "id": str(user_id),
            "username": username,
            "xp": new_xp
        }
        await execute_db_operation_with_retry(
            lambda: supabase.table("users").upsert(data).execute(),
            operation_name="update user XP"
        )
        return new_xp
    except Exception as e:
        print(f"[XP Error] {e}")
        return None

async def rank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Zeigt den aktuellen Rang und XP des Nutzers an."""
    user = update.message.from_user
    res = supabase.table("users").select("xp").eq("id", str(user.id)).execute()
    xp = 0
    if res.data:
        xp = res.data[0].get("xp", 0) or 0
    
    # Einfache Level-Formel: Alle 100 XP ein Level
    level = int(xp / 100) + 1
    await update.message.reply_text(f"🎖 <b>Agent Status:</b>\n\n👤 <b>{user.first_name}</b>\n✨ <b>XP:</b> {xp}\n⭐ <b>Level:</b> {level}", parse_mode="HTML")

async def welcome_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Begrüßt neue Mitglieder in der Gruppe."""
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            continue
        
        welcome_text = (
            f"👋 <b>Willkommen im Mainframe, {member.first_name}!</b>\n\n"
            "Ich bin der MIB Bot. Ich synchronisiere diesen Chat mit unserem Forum.\n"
            "Nutze /help für eine Liste meiner Funktionen oder /birthday um deinen Geburtstag einzutragen."
        )
        await update.message.reply_text(welcome_text, parse_mode="HTML")

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Meldet eine Nachricht an die Admins."""
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ Bitte antworte auf die Nachricht, die du melden möchtest.")
        return

    reporter = update.message.from_user.first_name
    reported_msg = update.message.reply_to_message
    reported_user = reported_msg.from_user.first_name
    msg_link = reported_msg.link if reported_msg.link else "Link nicht verfügbar"
    
    # Statusmeldung in der Gruppe
    status_msg = await update.message.reply_text(f"🚨 <b>REPORT</b>\n\nVon: {reporter}\nGemeldet: {reported_user}\n\n<i>Admins werden alarmiert...</i>", parse_mode="HTML")

    try:
        # Admins der Gruppe abrufen
        admins = await context.bot.get_chat_administrators(update.message.chat_id)
        notified = 0
        
        pm_text = (
            f"🚨 <b>REPORT ALARM</b>\n\n"
            f"<b>Gruppe:</b> {update.message.chat.title}\n"
            f"<b>Melder:</b> {reporter}\n"
            f"<b>Gemeldet:</b> {reported_user}\n"
            f"<b>Inhalt:</b> {reported_msg.text or reported_msg.caption or '[Medien]'}\n"
            f"🔗 <a href='{msg_link}'>Zur Nachricht</a>"
        )

        for admin in admins:
            if not admin.user.is_bot:
                try:
                    await context.bot.send_message(chat_id=admin.user.id, text=pm_text, parse_mode="HTML")
                    notified += 1
                except Exception:
                    continue # Admin hat Bot nicht gestartet oder blockiert
        
        await context.bot.edit_message_text(chat_id=update.message.chat_id, message_id=status_msg.message_id, text=f"🚨 <b>REPORT</b>\n\nVon: {reporter}\nGemeldet: {reported_user}\n\n<i>✅ {notified} Admins wurden privat benachrichtigt.</i>", parse_mode="HTML")
    except Exception as e:
        print(f"[Report Error] {e}")
        await context.bot.edit_message_text(chat_id=update.message.chat_id, message_id=status_msg.message_id, text=f"🚨 <b>REPORT</b>\n\nVon: {reporter}\nGemeldet: {reported_user}\n\n<i>⚠️ Fehler beim Alarmieren (Bot Rechte prüfen).</i>", parse_mode="HTML")

async def birthday_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Speichert den Geburtstag des Nutzers."""
    user = update.message.from_user
    text = update.message.text.replace("/birthday", "").strip()
    
    try:
        # Validierung des Formats DD.MM.YYYY
        date_obj = datetime.strptime(text, "%d.%m.%Y")
        iso_date = date_obj.strftime("%Y-%m-%d")
        
        # Speichern in DB
        data = {
            "id": str(user.id),
            "username": user.first_name,
            "birthday": iso_date
        }
        # Upsert: Aktualisiert User oder legt ihn an
        supabase.table("users").upsert(data).execute()
        
        await update.message.reply_text(f"✅ Geburtstag {text} gespeichert! Ich werde daran denken. 🎂")
    except ValueError:
        await update.message.reply_text("⚠️ Format nicht erkannt. Bitte nutze: /birthday DD.MM.YYYY\nBeispiel: <code>/birthday 24.12.1990</code>", parse_mode="HTML")
    except Exception as e:
        print(f"[Error] Birthday: {e}")
        await update.message.reply_text("❌ Fehler beim Speichern des Datums.")

async def check_birthdays(application: Application):
    """Prüft täglich auf Geburtstage und gratuliert."""
    bot = application.bot
    today = datetime.now()
    print(f"[{today.strftime('%H:%M')}] Prüfe Geburtstage...")
    
    try:
        # Alle User holen (bei sehr vielen Usern müsste man das optimieren)
        res = supabase.table("users").select("*").execute()
        
        for user in res.data:
            if not user.get("birthday"):
                continue
                
            try:
                bday = datetime.strptime(user["birthday"], "%Y-%m-%d")
                
                if bday.day == today.day and bday.month == today.month:
                    # GEBURTSTAG GEFUNDEN!
                    age = today.year - bday.year
                    username = user.get('username', 'Agent')
                    
                    msg_text = f"🎉 <b>Happy Birthday!</b> 🎉\n\nAlles Gute zum {age}. Geburtstag, {username}! 🎂🥳\nDas MIB Team wünscht dir einen fantastischen Tag!"
                    
                    # 1. Telegram Gruppe
                    try:
                        await bot.send_message(chat_id=GROUP_CHAT_ID, text=msg_text, parse_mode="HTML")
                    except Exception as e:
                        print(f"[Birthday] Telegram Send Failed: {e}")
                    
                    # 2. Shoutbox (Webseite)
                    try:
                        shout_data = {
                            "user": "MIB-Bot",
                            "text": f"🎉 Alles Gute zum {age}. Geburtstag, {username}! 🎂",
                            "time": today.strftime("%H:%M"),
                            "is_system": True,
                            "sent_to_telegram": True
                        }
                        supabase.table("shoutbox").insert(shout_data).execute()
                    except Exception as e:
                        print(f"[Birthday] Shoutbox Insert Failed: {e}")
            except ValueError:
                continue # Datum war ungültig gespeichert
                    
    except Exception as e:
        print(f"[Birthday Check Error] {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    # Text kann in 'text' (normale Nachricht) oder 'caption' (bei Dateien/Bildern) stehen
    text = update.message.text or update.message.caption or ""
    
    if not text:
        return

    user = update.message.from_user
    
    print(f"Nachricht empfangen von {user.first_name}: {text}")

    # --- LOGIK: GEBURTSTAGS-ERINNERUNG (Nur im Privatchat) ---
    # Wenn User privat schreibt und keinen Geburtstag hat -> Erinnern
    if update.message.chat.type == 'private' and not text.startswith("/"):
        try:
            # Kurz prüfen, ob Geburtstag da ist
            res = supabase.table("users").select("birthday").eq("id", str(user.id)).execute()
            # Wenn User nicht existiert oder kein Geburtstag gesetzt ist
            if not res.data or not res.data[0].get("birthday"):
                # Wir senden das als separate Info, aber nicht zu aufdringlich
                await update.message.reply_text("ℹ️ <b>Tipp:</b> Ich kenne deinen Geburtstag noch nicht.\nNutze <code>/birthday DD.MM.YYYY</code> damit wir dir gratulieren können!", parse_mode="HTML")
        except Exception as e:
            print(f"[Check User Error] {e}")
            # Fehler ignorieren, um den Chatfluss nicht zu stören

    # --- LOGIK: AI CHAT (#ai) ---
    if "#ai" in text:
        clean_text = text.replace("#ai", "").strip()
        if not clean_text:
            await update.message.reply_text("⚠️ Bitte stelle eine Frage zusammen mit #ai.")
            return

        try:
            # Status "Schreibt..." anzeigen
            await context.bot.send_chat_action(chat_id=update.message.chat_id, action="typing")
            
            prompt = f"Du bist MIB-KI, eine freundliche, höfliche und persönliche KI des MIB Mainframe Systems. Antworte auf folgende Frage: {clean_text}"
            response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            
            # Fix für zu lange Nachrichten (Split bei 4096 Zeichen)
            full_response = f"🤖 MIB-KI:\n{response.text}"
            if len(full_response) > 4096:
                await send_long_message(update.message, full_response)
            else:
                await update.message.reply_text(full_response)
        except Exception as e:
            print(f"[Error] AI: {e}")
            await update.message.reply_text("❌ Entschuldigung, meine neuronalen Netze sind gerade überlastet.")
        return

    # --- LOGIK: UPLOAD (#upload) ---
    if "#upload" in text:
        # Prüfen ob Datei direkt angehängt ist ODER ob auf eine Datei geantwortet wurde
        document = update.message.document
        if not document and update.message.reply_to_message:
            document = update.message.reply_to_message.document
            
        if document:
            try:
                status_msg = await update.message.reply_text("⏳ Upload in MIB Cloud gestartet...")
                
                # 1. Datei-Infos holen
                file_id = document.file_id
                file_name = document.file_name or f"file_{file_id}"
                file_size = f"{document.file_size / 1024 / 1024:.2f} MB"
                mime_type = document.mime_type or "application/octet-stream"
                
                # Dateiendung ermitteln
                file_ext = "FILE"
                if "." in file_name:
                    file_ext = file_name.split(".")[-1].upper()
                
                # 2. Datei von Telegram laden
                new_file = await context.bot.get_file(file_id)
                file_byte_array = await new_file.download_as_bytearray()
                
                # 3. Upload zu Supabase Storage
                storage_path = f"{int(time.time())}_{file_name}"
                supabase.storage.from_("files").upload(
                    path=storage_path,
                    file=bytes(file_byte_array),
                    file_options={"content-type": mime_type}
                )
                
                # 4. Public URL abrufen
                public_url = supabase.storage.from_("files").get_public_url(storage_path)
                
                # 5. Datenbank Eintrag erstellen
                clean_desc = text.replace("#upload", "").strip()
                if not clean_desc:
                    clean_desc = f"Upload via Telegram von {user.first_name}"

                download_data = {
                    "name": file_name,
                    "type": file_ext,
                    "size": file_size,
                    "source": user.first_name,
                    "description": clean_desc,
                    "url": public_url,
                    "sent_to_telegram": True # Verhindert Loop (nicht nochmal an Telegram senden)
                }
                
                supabase.table("downloads").insert(download_data).execute()
                
                await context.bot.edit_message_text(chat_id=update.message.chat_id, message_id=status_msg.message_id, text="✅ Datei erfolgreich archiviert!")
                print(f"-> Upload erfolgreich: {file_name}")
                
                # XP vergeben (+20 für Upload)
                await add_xp(user.id, user.first_name, 20)
                return

            except Exception as e:
                print(f"[Error] Upload: {e}")
                await update.message.reply_text(f"❌ Fehler beim Upload: {e}")
                return
        else:
            await update.message.reply_text("⚠️ Kein Anhang gefunden. Bitte sende eine Datei mit #upload oder antworte auf eine Datei.")
            return

    # --- LOGIK: ENTWEDER FORUM ODER SHOUTBOX ---
    if "#forum" in text:
        # --- FORUM ARCHIV ---
        clean_text = text.replace("#forum", "").strip()
        
        # Standard-Topic setzen
        topic_id = "all"
        topic_name = "General"

        # Versuch, den Thread-Namen zu ermitteln (falls in einem Topic gepostet)
        if update.message.is_topic_message:
            topic_id = "telegram_topic"
            topic_name = "Telegram Import"

        post_data = {
            "username": user.first_name,
            "telegram_id": str(user.id),
            "content": clean_text,
            "topic": topic_name,
            "topic_id": topic_id,
            "is_founder": False,
            "sent_to_telegram": True # Verhindert Loop
        }
        
        try:
            supabase.table("posts").insert(post_data).execute()
            await update.message.reply_text("✅ Im MIB Mainframe archiviert.")
            print(f"-> Neuer Post archiviert!")
            # XP vergeben (+10 für Post)
            await add_xp(user.id, user.first_name, 10)
        except Exception as e:
            print(f"[Error] Forum Post: {e}")

    elif "#shout" in text:
        # --- SHOUTBOX SYNC ---
        # Nur Nachrichten MIT #shout landen in der Shoutbox
        clean_text = text.replace("#shout", "").strip()
        try:
            shout_data = {
                "user": user.first_name,
                "text": clean_text,
                "time": update.message.date.strftime("%H:%M"),
                "is_system": False,
                "sent_to_telegram": True # Verhindert Loop
            }
            supabase.table("shoutbox").insert(shout_data).execute()
            print(f"-> Nachricht in Shoutbox gesendet!")
            # XP vergeben (+1 für Shout)
            await add_xp(user.id, user.first_name, 1)
        except Exception as e:
            print(f"[Error] Shoutbox: {e}")

async def sync_database_to_telegram(application: Application):
    """Optimized database sync with batching and error handling."""
    bot = application.bot
    sync_start_time = time.time()
    
    # Batch size for processing to prevent memory issues
    BATCH_SIZE = 10
    
    # Track sync statistics
    sync_stats = {
        'shoutbox': {'processed': 0, 'errors': 0},
        'downloads': {'processed': 0, 'errors': 0},
        'posts': {'processed': 0, 'errors': 0},
        'snippets': {'processed': 0, 'errors': 0}
    }
    
    # 1. OPTIMIZED SHOUTBOX SYNC (Web -> Telegram)
    try:
        # Use limit to prevent large result sets
        res = await execute_db_operation_with_retry(
            lambda: supabase.table("shoutbox").select("*").eq("sent_to_telegram", False).limit(BATCH_SIZE).execute(),
            operation_name="fetch unsynced shoutbox messages"
        )
        
        # Batch update IDs for efficiency
        processed_ids = []
        
        for msg in res.data:
            try:
                if not msg.get('is_system', False):
                    text = f"💬 <b>[WEB] {msg['user']}:</b> {msg['text']}"
                    await bot.send_message(chat_id=GROUP_CHAT_ID, text=text, parse_mode="HTML")
                
                processed_ids.append(msg['id'])
                sync_stats['shoutbox']['processed'] += 1
                
            except Exception as e:
                print(f"[Sync Error] Shoutbox Send Failed for ID {msg.get('id')}: {e}")
                sync_stats['shoutbox']['errors'] += 1
        
        # Batch update all processed messages
        if processed_ids:
            await execute_db_operation_with_retry(
                lambda: supabase.table("shoutbox").update({"sent_to_telegram": True}).in_("id", processed_ids).execute(),
                operation_name="batch update shoutbox sync flags"
            )
            
    except Exception as e:
        print(f"[Sync Error] Shoutbox batch: {e}")
        sync_stats['shoutbox']['errors'] += 1

    # 2. OPTIMIZED DOWNLOADS SYNC (Web -> Telegram)
    try:
        res = await execute_db_operation_with_retry(
            lambda: supabase.table("downloads").select("*").eq("sent_to_telegram", False).limit(BATCH_SIZE).execute(),
            operation_name="fetch unsynced downloads"
        )
        
        processed_ids = []
        
        for file in res.data:
            try:
                # Truncate long descriptions to prevent message size issues
                description = (file.get('description') or '')[:200]
                if len(file.get('description', '')) > 200:
                    description += "..."
                
                caption = f"📂 <b>Neuer Web-Upload:</b> {file['name']}\n\n{description}\n\n🔗 <a href='{file['url']}'>Download</a>"
                await bot.send_message(chat_id=GROUP_CHAT_ID, text=caption, parse_mode="HTML")
                
                processed_ids.append(file['id'])
                sync_stats['downloads']['processed'] += 1
                
            except Exception as e:
                print(f"[Sync Error] Downloads Send Failed for ID {file.get('id')}: {e}")
                sync_stats['downloads']['errors'] += 1
        
        # Batch update
        if processed_ids:
            await execute_db_operation_with_retry(
                lambda: supabase.table("downloads").update({"sent_to_telegram": True}).in_("id", processed_ids).execute(),
                operation_name="batch update downloads sync flags"
            )
            
    except Exception as e:
        print(f"[Sync Error] Downloads batch: {e}")
        sync_stats['downloads']['errors'] += 1

    # 3. OPTIMIZED FORUM POSTS SYNC (Web -> Telegram)
    try:
        res = await execute_db_operation_with_retry(
            lambda: supabase.table("posts").select("*").eq("sent_to_telegram", False).limit(BATCH_SIZE).execute(),
            operation_name="fetch unsynced posts"
        )
        
        processed_ids = []
        
        for post in res.data:
            try:
                # Truncate long content to prevent message size issues
                content = post.get('content', '')[:300]
                if len(post.get('content', '')) > 300:
                    content += "..."
                
                text = f"📝 <b>Neuer Forum Post</b>\n\n<b>Von:</b> {post['username']}\n<b>Thema:</b> {post['topic']}\n\n{content}"
                await bot.send_message(chat_id=GROUP_CHAT_ID, text=text, parse_mode="HTML")
                
                processed_ids.append(post['id'])
                sync_stats['posts']['processed'] += 1
                
            except Exception as e:
                print(f"[Sync Error] Posts Send Failed for ID {post.get('id')}: {e}")
                sync_stats['posts']['errors'] += 1
        
        # Batch update
        if processed_ids:
            await execute_db_operation_with_retry(
                lambda: supabase.table("posts").update({"sent_to_telegram": True}).in_("id", processed_ids).execute(),
                operation_name="batch update posts sync flags"
            )
            
    except Exception as e:
        print(f"[Sync Error] Posts batch: {e}")
        sync_stats['posts']['errors'] += 1

    # 4. OPTIMIZED SNIPPETS SYNC (Web -> Telegram)
    try:
        res = await execute_db_operation_with_retry(
            lambda: supabase.table("snippets").select("*").eq("sent_to_telegram", False).limit(BATCH_SIZE).execute(),
            operation_name="fetch unsynced snippets"
        )
        
        processed_ids = []
        
        for snip in res.data:
            try:
                # Escape HTML-sensitive characters and limit code length
                code = snip.get('code', '')[:500]  # Limit code length
                if len(snip.get('code', '')) > 500:
                    code += "\n... (truncated)"
                
                escaped_code = html.escape(code)
                text = f"💻 <b>Neues Code Snippet</b>\n\n<b>Titel:</b> {snip.get('title', 'Ohne Titel')}\n<b>Sprache:</b> {snip.get('lang', 'Unbekannt')}\n\n<pre><code>{escaped_code}</code></pre>"
                
                if len(text) > 4096:
                    # Fallback for very long code snippets
                    fallback_text = f"💻 <b>Neues Code Snippet:</b> {snip.get('title', 'Ohne Titel')}\n\nDer Code ist zu lang für eine einzelne Telegram-Nachricht. Bitte im Forum ansehen."
                    await bot.send_message(chat_id=GROUP_CHAT_ID, text=fallback_text, parse_mode="HTML")
                else:
                    await bot.send_message(chat_id=GROUP_CHAT_ID, text=text, parse_mode="HTML")
                
                processed_ids.append(snip['id'])
                sync_stats['snippets']['processed'] += 1
                
            except Exception as e:
                print(f"[Sync Error] Snippets Send Failed for ID {snip.get('id')}: {e}")
                sync_stats['snippets']['errors'] += 1
        
        # Batch update
        if processed_ids:
            await execute_db_operation_with_retry(
                lambda: supabase.table("snippets").update({"sent_to_telegram": True}).in_("id", processed_ids).execute(),
                operation_name="batch update snippets sync flags"
            )
            
    except Exception as e:
        print(f"[Sync Error] Snippets batch: {e}")
        sync_stats['snippets']['errors'] += 1
    
    # Log sync performance
    sync_duration = time.time() - sync_start_time
    total_processed = sum(stats['processed'] for stats in sync_stats.values())
    total_errors = sum(stats['errors'] for stats in sync_stats.values())
    
    print(f"✅ Sync completed in {sync_duration:.2f}s: {total_processed} items processed, {total_errors} errors")
    if total_errors > 0:
        print(f"   Error breakdown: {sync_stats}")
    
    return {
        'duration': sync_duration,
        'processed': total_processed,
        'errors': total_errors,
        'stats': sync_stats
    }

async def trigger_welcome_all(application: Application):
    """Sendet eine Begrüßung an alle in der Gruppe (ausgelöst durch Admin)."""
    bot = application.bot
    welcome_text = (
        "👋 <b>System-Broadcast:</b>\n\n"
        "Hallo an alle Agenten! Der MIB Mainframe grüßt euch.\n"
        "Bleibt wachsam und synchronisiert. 🕶️\n\n"
        "<i>Nutzt /help für eine Liste der verfügbaren Befehle.</i>"
    )
    try:
        await bot.send_message(chat_id=GROUP_CHAT_ID, text=welcome_text, parse_mode="HTML")
        print("-> Welcome-All Broadcast gesendet.")
    except Exception as e:
        print(f"[Broadcast Error] {e}")

async def send_daily_ai_greeting(application: Application):
    """Generiert eine tägliche Begrüßung mit KI (Fun Fact, Motivation)."""
    bot = application.bot
    today_str = datetime.now().strftime("%d.%m.%Y")
    
    print(f"Generiere Daily AI Greeting für {today_str}...")
    
    # Top Poster der letzten 24h ermitteln
    top_poster_info = ""
    try:
        yesterday = datetime.now() - timedelta(days=1)
        res = supabase.table("posts").select("username").gte("created_at", yesterday.isoformat()).execute()
        
        if res.data:
            usernames = [p['username'] for p in res.data]
            if usernames:
                most_common = Counter(usernames).most_common(1)
                top_user = most_common[0][0]
                count = most_common[0][1]
                top_poster_info = f"Erwähne am Ende lobend unseren Top-Poster der letzten 24 Stunden: {top_user} ({count} Beiträge)."
    except Exception as e:
        print(f"[Top Poster Error] {e}")

    prompt = (
        f"Erstelle eine freundliche Tagesbegrüßung für die Telegram-Gruppe. "
        f"Datum: {today_str}. "
        f"Inhalt: "
        f"1. Wünsche einen guten Morgen und einen erfolgreichen Tag. "
        f"2. Ein kurzer, spannender Fun Fact (Allgemeinwissen oder Technik). "
        f"3. Ein motivierendes Zitat. "
        f"{top_poster_info} "
        f"Stil: Normal, freundlich, Community-orientiert (kein MIB/Sci-Fi Rollenspiel). Nutze passende Emojis."
    )

    try:
        # Wir nutzen das gleiche Modell wie im Chat
        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        await bot.send_message(chat_id=GROUP_CHAT_ID, text=response.text)
        print("-> Daily AI Greeting gesendet.")
    except Exception as e:
        print(f"[Daily AI Error] {e}")

async def daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manueller Trigger für die Tagesbegrüßung (zum Testen)."""
    await update.message.reply_text("⏳ Generiere Tagesbericht...")
    await send_daily_ai_greeting(context.application)

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prüft Erreichbarkeit einer URL (IPTV/Web)."""
    url = " ".join(context.args)
    if not url:
        await update.message.reply_text("⚠️ Bitte URL angeben: <code>/check http://example.com</code>", parse_mode="HTML")
        return

    if "." not in url and not url.startswith("http"):
        await update.message.reply_text("⚠️ Das sieht nicht wie eine gültige Domain aus.\nBitte gib eine URL ein, z.B. <code>google.com</code>\n\n<i>Für Release-Suche nutze: /scene</i>", parse_mode="HTML")
        return

    if not url.startswith("http"):
        url = "http://" + url

    status_msg = await update.message.reply_text(f"🔎 Prüfe Verfügbarkeit von {url} ...")
    
    try:
        start_time = time.time()
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                duration = (time.time() - start_time) * 1000
                status_code = response.status
                
                if status_code == 200:
                    await context.bot.edit_message_text(
                        chat_id=update.message.chat_id,
                        message_id=status_msg.message_id,
                        text=f"✅ <b>ONLINE</b>\n\n🔗 {url}\n⚡ Ping: {duration:.0f}ms\n📡 Status: {status_code} OK",
                        parse_mode="HTML"
                    )
                else:
                    await context.bot.edit_message_text(
                        chat_id=update.message.chat_id,
                        message_id=status_msg.message_id,
                        text=f"❌ <b>OFFLINE</b> (oder geschützt)\n\n🔗 {url}\n⚡ Ping: {duration:.0f}ms\n⚠️ Status: {status_code}",
                        parse_mode="HTML"
                    )
    except aiohttp.ClientConnectorError:
        await context.bot.edit_message_text(
            chat_id=update.message.chat_id,
            message_id=status_msg.message_id,
            text=f"❌ <b>NICHT ERREICHBAR</b>\n\nDer Server konnte nicht gefunden werden.\n(DNS-Fehler oder falsche URL)",
            parse_mode="HTML"
        )
    except Exception as e:
        await context.bot.edit_message_text(
            chat_id=update.message.chat_id,
            message_id=status_msg.message_id,
            text=f"❌ <b>FEHLER</b>\n\nVerbindung fehlgeschlagen.\n<i>{str(e)}</i>",
            parse_mode="HTML"
        )

async def scene_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sucht nach Scene Releases."""
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("⚠️ Bitte Suchbegriff angeben: <code>/scene Matrix</code>", parse_mode="HTML")
        return

    await update.message.reply_chat_action("typing")
    
    try:
        # Nutzung der xrel.to API (Deutschsprachige Community)
        api_url = f"https://api.xrel.to/v2/search/releases.json?q={query}"
        async with aiohttp.ClientSession() as session:
            # User-Agent setzen, um Blockierung zu vermeiden
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            async with session.get(api_url, headers=headers) as resp:
                if resp.status != 200:
                    await update.message.reply_text(f"❌ XREL API antwortet nicht (Status: {resp.status}).")
                    return
                
                try:
                    # content_type=None erlaubt das Parsen auch wenn der Server text/html sendet
                    data = await resp.json(content_type=None)
                except Exception:
                    await update.message.reply_text("❌ Fehler: API lieferte ungültige Daten (evtl. offline oder geschützt).")
                    return

                results = data.get('results', [])
                
                if not results:
                    await update.message.reply_text(f"❌ Keine Scene-Releases gefunden für '{query}'.")
                    return
                
                msg = f"🏴‍☠️ <b>XREL Search: '{query}'</b>\n\n"
                for release in results[:5]:
                    name = release.get('dirname', 'N/A')
                    cat = release.get('category_name', 'N/A')
                    ts = release.get('time', 0)
                    date_str = datetime.fromtimestamp(float(ts)).strftime('%d.%m.%Y') if ts else "N/A"
                    
                    # Link zum Release auf xrel bauen
                    link_suffix = release.get('link_href', '')
                    link = f"https://www.xrel.to{link_suffix}" if link_suffix else ""
                    
                    if link:
                        msg += f"📦 <b><a href='{link}'>{name}</a></b>\n📅 {date_str} | 📂 {cat}\n\n"
                    else:
                        msg += f"📦 <b>{name}</b>\n📅 {date_str} | 📂 {cat}\n\n"
                
                await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)

    except Exception as e:
        print(f"[Scene Error] {e}")
        await update.message.reply_text("❌ Fehler bei der Suche.")

async def blitzdings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Löscht den Befehl und sendet einen Neuralyzer-Blitz."""
    chat_id = update.message.chat_id
    message_id = update.message.message_id
    
    # Neuralyzer GIF (MIB)
    flash_gif = "https://media1.tenor.com/m/6IPNUgkpCsDRK/men-in-black-memory-erase.gif"

    try:
        # 1. Den Befehl selbst löschen (Spuren beseitigen)
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        
        # 2. Blitz senden
        await context.bot.send_animation(chat_id=chat_id, animation=flash_gif, caption="🕶️ <b>BLITZDINGS!</b>\n\nWas ist gerade passiert? Ich weiß es nicht, du weißt es nicht.\n<i>(Chat bereinigt)</i>", parse_mode="HTML")
    except Exception as e:
        print(f"[Blitzdings Error] {e}")
        await update.message.reply_text("❌ Fehler: Mein Neuralyzer hat keine Batterie mehr (Admin-Rechte prüfen).")

def get_temp_password(email):
    """Erstellt ein deterministisches Passwort für den Temp-Mail Account."""
    secret = "MIB_MAIN_FRAME_SECRET"
    return hashlib.sha256((email + secret).encode()).hexdigest()[:20]

async def tempmail_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generiert eine Wegwerf-E-Mail via Mail.tm."""
    try:
        async with aiohttp.ClientSession() as session:
            # 1. Domain holen
            async with session.get("https://api.mail.tm/domains") as resp:
                if resp.status != 200:
                    await update.message.reply_text("❌ Fehler: Mail-Provider nicht erreichbar.")
                    return
                domains_data = await resp.json()
                domain = domains_data['hydra:member'][0]['domain']
            
            # 2. Account erstellen
            username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
            email = f"{username}@{domain}"
            password = get_temp_password(email)
            
            async with session.post("https://api.mail.tm/accounts", json={"address": email, "password": password}) as resp:
                if resp.status not in [200, 201]:
                    await update.message.reply_text(f"❌ Fehler beim Erstellen: {resp.status}")
                    return
            
            # 3. UI senden
            keyboard = [[InlineKeyboardButton("📥 Posteingang prüfen", callback_data=f"checkmail_{email}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"📧 <b>Deine Wegwerf-Adresse:</b>\n\n<code>{email}</code>\n\n<i>Klicke unten, um Mails abzurufen.</i>",
                parse_mode="HTML",
                reply_markup=reply_markup
            )
    except Exception as e:
        print(f"[TempMail Error] {e}")
        await update.message.reply_text("❌ Fehler beim Generieren der Adresse.")

async def check_mail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prüft Posteingang via Mail.tm."""
    query = update.callback_query
    await query.answer("Lade Posteingang...")
    
    email = query.data.replace("checkmail_", "")
    password = get_temp_password(email)
    
    try:
        async with aiohttp.ClientSession() as session:
            # 1. Token holen
            async with session.post("https://api.mail.tm/token", json={"address": email, "password": password}) as resp:
                if resp.status != 200:
                    await query.edit_message_text(
                        f"📧 <b>Adresse:</b> <code>{email}</code>\n\n❌ <b>Session abgelaufen.</b>\nBitte neue Adresse generieren.",
                        parse_mode="HTML"
                    )
                    return
                token_data = await resp.json()
                token = token_data['token']
            
            # 2. Nachrichten abrufen
            headers = {"Authorization": f"Bearer {token}"}
            async with session.get("https://api.mail.tm/messages", headers=headers) as resp:
                msgs_data = await resp.json()
                messages = msgs_data['hydra:member']
                
                if not messages:
                    await query.edit_message_text(
                        f"📧 <b>Adresse:</b> <code>{email}</code>\n\n❌ <b>Keine Nachrichten.</b>\nVersuche es gleich nochmal.",
                        parse_mode="HTML",
                        reply_markup=query.message.reply_markup
                    )
                    return
                
                # Neueste Nachricht lesen
                latest_id = messages[0]['id']
                async with session.get(f"https://api.mail.tm/messages/{latest_id}", headers=headers) as msg_resp:
                    full_msg = await msg_resp.json()
                    
                    sender = full_msg.get('from', {}).get('address', 'Unbekannt')
                    subject = full_msg.get('subject', 'Kein Betreff')
                    body = full_msg.get('text', 'Kein Text')[:500]
                    
                    text = (
                        f"📧 <b>Adresse:</b> <code>{email}</code>\n\n"
                        f"📩 <b>Von:</b> {sender}\n"
                        f"📝 <b>Betreff:</b> {subject}\n\n"
                        f"{body}..."
                    )
                    
                    await query.edit_message_text(text, parse_mode="HTML", reply_markup=query.message.reply_markup)

    except Exception as e:
        print(f"[CheckMail Error] {e}")
        await query.edit_message_text(f"❌ Fehler: {e}", reply_markup=query.message.reply_markup)

async def fakeid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generiert eine Fake-Identität (DE)."""
    try:
        # Wir nutzen randomuser.me API mit ?nat=de für deutsche Daten
        # Das ist stabiler als HTML-Scraping von Webseiten.
        url = "https://randomuser.me/api/?nat=de"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    await update.message.reply_text("❌ Fehler: API nicht erreichbar.")
                    return
                
                data = await resp.json()
                user = data['results'][0]
                
                # Datum formatieren
                dob_raw = user['dob']['date'] # z.B. 1993-07-20T09:44:18.651Z
                dob_date = datetime.strptime(dob_raw.split('T')[0], "%Y-%m-%d").strftime("%d.%m.%Y")
                
                msg = (
                    f"🕵️ <b>Neue Identität (DE)</b>\n\n"
                    f"👤 <b>Name:</b> {user['name']['first']} {user['name']['last']}\n"
                    f"🏠 <b>Adresse:</b> {user['location']['street']['name']} {user['location']['street']['number']}, {user['location']['postcode']} {user['location']['city']}\n"
                    f"📧 <b>E-Mail:</b> {user['email']}\n"
                    f"🎂 <b>Geburtstag:</b> {dob_date} ({user['dob']['age']} Jahre)\n"
                    f"🔐 <b>Login:</b> <code>{user['login']['username']}</code> / <code>{user['login']['password']}</code>\n"
                    f"🖼️ <a href='{user['picture']['large']}'>Foto ansehen</a>"
                )
                
                await update.message.reply_text(msg, parse_mode="HTML")
    except Exception as e:
        print(f"[FakeID Error] {e}")
        await update.message.reply_text("❌ Fehler beim Generieren der Identität.")

async def ip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Zeigt Geo-IP Informationen an."""
    target = " ".join(context.args)
    if not target:
        await update.message.reply_text("⚠️ Bitte IP oder Domain angeben: <code>/ip 1.1.1.1</code>", parse_mode="HTML")
        return
    
    # ip-api.com ist kostenlos für nicht-kommerzielle Nutzung (bis 45 req/min)
    url = f"http://ip-api.com/json/{target}?fields=status,message,country,city,isp,org,query,timezone"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                if data['status'] == 'fail':
                    await update.message.reply_text(f"❌ Fehler: {data['message']}")
                    return
                
                msg = (
                    f"🌍 <b>IP Info: {data['query']}</b>\n\n"
                    f"🏳️ <b>Land:</b> {data['country']}\n"
                    f"🏙️ <b>Stadt:</b> {data['city']}\n"
                    f"🏢 <b>ISP:</b> {data['isp']}\n"
                    f"🏢 <b>Org:</b> {data['org']}\n"
                    f"🕒 <b>Timezone:</b> {data['timezone']}"
                )
                await update.message.reply_text(msg, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Fehler: {e}")

async def coin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Zeigt Crypto-Preise via Binance API."""
    symbol = " ".join(context.args).upper()
    if not symbol:
        await update.message.reply_text("⚠️ Bitte Coin angeben: <code>/coin BTC</code>", parse_mode="HTML")
        return
    
    # Binance API erwartet z.B. BTCUSDT
    pair = f"{symbol}USDT"
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={pair}"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    await update.message.reply_text(f"❌ Coin '{symbol}' nicht gefunden (oder API Fehler).")
                    return
                
                data = await resp.json()
                price = float(data['price'])
                
                # Schöne Formatierung je nach Preis
                if price < 1:
                    price_str = f"{price:.4f}"
                else:
                    price_str = f"{price:,.2f}"
                
                await update.message.reply_text(f"💰 <b>{symbol}</b>: ${price_str} (USDT)", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Fehler: {e}")

async def port_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prüft, ob ein Port offen ist."""
    if len(context.args) != 2:
        await update.message.reply_text("⚠️ Nutzung: <code>/port <host> <port></code>\nBeispiel: <code>/port google.com 443</code>", parse_mode="HTML")
        return
    
    host = context.args[0]
    try:
        port = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Port muss eine Zahl sein.")
        return

    status_msg = await update.message.reply_text(f"🔌 Prüfe {host}:{port} ...")
    
    try:
        # Async Socket Connect mit Timeout
        future = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(future, timeout=3)
        writer.close()
        await writer.wait_closed()
        
        await context.bot.edit_message_text(
            chat_id=update.message.chat_id,
            message_id=status_msg.message_id,
            text=f"✅ <b>OPEN</b>\n\n{host}:{port} ist erreichbar.",
            parse_mode="HTML"
        )
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
        await context.bot.edit_message_text(
            chat_id=update.message.chat_id,
            message_id=status_msg.message_id,
            text=f"❌ <b>CLOSED</b> (oder gefiltert)\n\n{host}:{port} antwortet nicht.",
            parse_mode="HTML"
        )
    except Exception as e:
        await context.bot.edit_message_text(
            chat_id=update.message.chat_id,
            message_id=status_msg.message_id,
            text=f"⚠️ Fehler: {e}",
            parse_mode="HTML"
        )

async def genpass_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generiert ein sicheres Passwort."""
    length = 16
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    password = "".join(random.choice(chars) for _ in range(length))
    
    # Als Monospace formatieren zum leichten Kopieren
    await update.message.reply_text(f"🔐 <b>Neues Passwort:</b>\n<code>{password}</code>", parse_mode="HTML")

async def encode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Base64 Encode."""
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("⚠️ Bitte Text angeben: <code>/encode Hallo</code>", parse_mode="HTML")
        return
    
    encoded = base64.b64encode(text.encode('utf-8')).decode('utf-8')
    await update.message.reply_text(f"🔒 <b>Base64 Encoded:</b>\n<code>{encoded}</code>", parse_mode="HTML")

async def decode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Base64 Decode."""
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("⚠️ Bitte Base64-String angeben: <code>/decode ...</code>", parse_mode="HTML")
        return
    
    try:
        decoded = base64.b64decode(text).decode('utf-8')
        await update.message.reply_text(f"🔓 <b>Decoded:</b>\n<code>{decoded}</code>", parse_mode="HTML")
    except Exception:
        await update.message.reply_text("❌ Fehler: Ungültiger Base64-String.")

async def qr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generiert einen QR-Code."""
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("⚠️ Bitte Text/Link angeben: <code>/qr https://google.com</code>", parse_mode="HTML")
        return
    
    # Wir nutzen die QuickChart API (schnell & zuverlässig für QR Codes)
    encoded_text = quote(text)
    qr_url = f"https://quickchart.io/qr?text={encoded_text}&size=400&margin=1&dark=000000&light=ffffff"
    
    await update.message.reply_chat_action("upload_photo")
    try:
        await update.message.reply_photo(
            photo=qr_url,
            caption=f"📱 <b>QR Code</b>\nInhalt: <code>{text}</code>",
            parse_mode="HTML"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Fehler beim Senden des Bildes: {e}")

if __name__ == '__main__':
    # Detect environment
    is_railway = os.getenv('RAILWAY_ENVIRONMENT') is not None
    is_render = os.getenv('RENDER_ENVIRONMENT') is not None
    is_koyeb = os.getenv('KOYEB_ENVIRONMENT') is not None
    is_vercel = os.getenv('VERCEL') is not None
    
    if is_koyeb:
        print("🛸 MIB Bot System v1.0 wird gestartet (KOYEB - 24/7)...")
        
        # Starte Health-Server in separatem Thread (für Koyeb)
        import threading
        from health_server import start_health_server
        
        health_thread = threading.Thread(target=start_health_server, daemon=True)
        health_thread.start()
        
        # Koyeb: Use polling for true 24/7 operation
        application = Application.builder().token(TELEGRAM_TOKEN).build()

        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("hilfe", help_command))
        application.add_handler(CommandHandler("birthday", birthday_command))
        application.add_handler(CommandHandler("stats", stats_command))
        application.add_handler(CommandHandler("search", search_command))
        application.add_handler(CommandHandler("rank", rank_command))
        application.add_handler(CommandHandler("report", report_command))
        application.add_handler(CommandHandler("daily", daily_command))
        application.add_handler(CommandHandler("check", check_command))
        application.add_handler(CommandHandler("scene", scene_command))
        application.add_handler(CommandHandler("tempmail", tempmail_command))
        application.add_handler(CommandHandler("fakeid", fakeid_command))
        application.add_handler(CommandHandler("ip", ip_command))
        application.add_handler(CommandHandler("coin", coin_command))
        application.add_handler(CommandHandler("port", port_command))
        application.add_handler(CommandHandler("genpass", genpass_command))
        application.add_handler(CommandHandler("encode", encode_command))
        application.add_handler(CommandHandler("decode", decode_command))
        application.add_handler(CommandHandler("qr", qr_command))
        application.add_handler(CommandHandler("blitzdings", blitzdings_command))
        application.add_handler(CallbackQueryHandler(check_mail_callback, pattern="^checkmail_"))
        application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_member))
        application.add_handler(MessageHandler((filters.TEXT | filters.Document.ALL | filters.CAPTION) & (~filters.COMMAND), handle_message))

        if application.job_queue:
            # Sync job every 30 seconds (Koyeb can handle this easily)
            async def sync_wrapper(context: ContextTypes.DEFAULT_TYPE):
                await sync_database_to_telegram(context.application)
            
            # Birthday check daily at 8 AM
            async def birthday_wrapper(context: ContextTypes.DEFAULT_TYPE):
                await check_birthdays(context.application)
            
            # Daily greeting at 7 AM
            async def greeting_wrapper(context: ContextTypes.DEFAULT_TYPE):
                await send_daily_ai_greeting(context.application)
            
            application.job_queue.run_repeating(sync_wrapper, interval=30, first=10)
            application.job_queue.run_daily(birthday_wrapper, time=datetime.now().replace(hour=8, minute=0, second=0, microsecond=0).time())
            application.job_queue.run_daily(greeting_wrapper, time=datetime.now().replace(hour=7, minute=0, second=0, microsecond=0).time())
            
            print("✅ Koyeb Jobs gestartet (Sync: 30s, Daily: 7/8 AM)")
        
        print("🚀 Bot läuft auf Koyeb - ECHTES 24/7 ohne Sleep!")
        application.run_polling(drop_pending_updates=True)
        
    elif is_render:
        print("🚀 MIB Bot System v1.0 wird gestartet (KOYEB - 24/7)...")
        
        # Starte Health-Server in separatem Thread (für Koyeb Keep-Alive)
        import threading
        from health_server import start_health_server
        
        health_thread = threading.Thread(target=start_health_server, daemon=True)
        health_thread.start()
        
        # Koyeb: Use polling for 24/7 operation
        application = Application.builder().token(TELEGRAM_TOKEN).build()

        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("hilfe", help_command))
        application.add_handler(CommandHandler("birthday", birthday_command))
        application.add_handler(CommandHandler("stats", stats_command))
        application.add_handler(CommandHandler("search", search_command))
        application.add_handler(CommandHandler("rank", rank_command))
        application.add_handler(CommandHandler("report", report_command))
        application.add_handler(CommandHandler("daily", daily_command))
        application.add_handler(CommandHandler("check", check_command))
        application.add_handler(CommandHandler("scene", scene_command))
        application.add_handler(CommandHandler("tempmail", tempmail_command))
        application.add_handler(CommandHandler("fakeid", fakeid_command))
        application.add_handler(CommandHandler("ip", ip_command))
        application.add_handler(CommandHandler("coin", coin_command))
        application.add_handler(CommandHandler("port", port_command))
        application.add_handler(CommandHandler("genpass", genpass_command))
        application.add_handler(CommandHandler("encode", encode_command))
        application.add_handler(CommandHandler("decode", decode_command))
        application.add_handler(CommandHandler("qr", qr_command))
        application.add_handler(CommandHandler("blitzdings", blitzdings_command))
        application.add_handler(CallbackQueryHandler(check_mail_callback, pattern="^checkmail_"))
        application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_member))
        application.add_handler(MessageHandler((filters.TEXT | filters.Document.ALL | filters.CAPTION) & (~filters.COMMAND), handle_message))

        if application.job_queue:
            # Sync job every 30 seconds (Koyeb can handle this)
            async def sync_wrapper(context: ContextTypes.DEFAULT_TYPE):
                await sync_database_to_telegram(context.application)
            
            # Birthday check daily at 8 AM
            async def birthday_wrapper(context: ContextTypes.DEFAULT_TYPE):
                await check_birthdays(context.application)
            
            # Daily greeting at 7 AM
            async def greeting_wrapper(context: ContextTypes.DEFAULT_TYPE):
                await send_daily_ai_greeting(context.application)
            
            application.job_queue.run_repeating(sync_wrapper, interval=30, first=10)
            application.job_queue.run_daily(birthday_wrapper, time=datetime.now().replace(hour=8, minute=0, second=0, microsecond=0).time())
            application.job_queue.run_daily(greeting_wrapper, time=datetime.now().replace(hour=7, minute=0, second=0, microsecond=0).time())
            
            print("✅ Koyeb Jobs gestartet (Sync: 30s, Daily: 7/8 AM)")
        
        print("🚀 Bot läuft auf Koyeb - 24/7 Polling aktiv")
        application.run_polling(drop_pending_updates=True)
        
    elif is_render:
        print("🎨 MIB Bot System v1.0 wird gestartet (RENDER - 24/7)...")
        
        # Starte Health-Server in separatem Thread (für Render Keep-Alive)
        import threading
        from health_server import start_health_server
        
        health_thread = threading.Thread(target=start_health_server, daemon=True)
        health_thread.start()
        
        # Render: Use polling for 24/7 operation
        application = Application.builder().token(TELEGRAM_TOKEN).build()

        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("hilfe", help_command))
        application.add_handler(CommandHandler("birthday", birthday_command))
        application.add_handler(CommandHandler("stats", stats_command))
        application.add_handler(CommandHandler("search", search_command))
        application.add_handler(CommandHandler("rank", rank_command))
        application.add_handler(CommandHandler("report", report_command))
        application.add_handler(CommandHandler("daily", daily_command))
        application.add_handler(CommandHandler("check", check_command))
        application.add_handler(CommandHandler("scene", scene_command))
        application.add_handler(CommandHandler("tempmail", tempmail_command))
        application.add_handler(CommandHandler("fakeid", fakeid_command))
        application.add_handler(CommandHandler("ip", ip_command))
        application.add_handler(CommandHandler("coin", coin_command))
        application.add_handler(CommandHandler("port", port_command))
        application.add_handler(CommandHandler("genpass", genpass_command))
        application.add_handler(CommandHandler("encode", encode_command))
        application.add_handler(CommandHandler("decode", decode_command))
        application.add_handler(CommandHandler("qr", qr_command))
        application.add_handler(CommandHandler("blitzdings", blitzdings_command))
        application.add_handler(CallbackQueryHandler(check_mail_callback, pattern="^checkmail_"))
        application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_member))
        application.add_handler(MessageHandler((filters.TEXT | filters.Document.ALL | filters.CAPTION) & (~filters.COMMAND), handle_message))

        if application.job_queue:
            # Sync job every 60 seconds (Render can handle this)
            async def sync_wrapper(context: ContextTypes.DEFAULT_TYPE):
                await sync_database_to_telegram(context.application)
            
            # Birthday check daily at 8 AM
            async def birthday_wrapper(context: ContextTypes.DEFAULT_TYPE):
                await check_birthdays(context.application)
            
            # Daily greeting at 7 AM
            async def greeting_wrapper(context: ContextTypes.DEFAULT_TYPE):
                await send_daily_ai_greeting(context.application)
            
            application.job_queue.run_repeating(sync_wrapper, interval=60, first=10)
            application.job_queue.run_daily(birthday_wrapper, time=datetime.now().replace(hour=8, minute=0, second=0, microsecond=0).time())
            application.job_queue.run_daily(greeting_wrapper, time=datetime.now().replace(hour=7, minute=0, second=0, microsecond=0).time())
            
            print("✅ Render Jobs gestartet (Sync: 60s, Daily: 7/8 AM)")
        
        print("🚀 Bot läuft auf Render - 24/7 Polling aktiv")
        application.run_polling(drop_pending_updates=True)
        
    elif is_railway:
        print("🚂 MIB Bot System v1.0 wird gestartet (RAILWAY)...")
        # Railway: Use polling for 24/7 operation
        application = Application.builder().token(TELEGRAM_TOKEN).build()

        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("hilfe", help_command))
        application.add_handler(CommandHandler("birthday", birthday_command))
        application.add_handler(CommandHandler("stats", stats_command))
        application.add_handler(CommandHandler("search", search_command))
        application.add_handler(CommandHandler("rank", rank_command))
        application.add_handler(CommandHandler("report", report_command))
        application.add_handler(CommandHandler("daily", daily_command))
        application.add_handler(CommandHandler("check", check_command))
        application.add_handler(CommandHandler("scene", scene_command))
        application.add_handler(CommandHandler("tempmail", tempmail_command))
        application.add_handler(CommandHandler("fakeid", fakeid_command))
        application.add_handler(CommandHandler("ip", ip_command))
        application.add_handler(CommandHandler("coin", coin_command))
        application.add_handler(CommandHandler("port", port_command))
        application.add_handler(CommandHandler("genpass", genpass_command))
        application.add_handler(CommandHandler("encode", encode_command))
        application.add_handler(CommandHandler("decode", decode_command))
        application.add_handler(CommandHandler("qr", qr_command))
        application.add_handler(CommandHandler("blitzdings", blitzdings_command))
        application.add_handler(CallbackQueryHandler(check_mail_callback, pattern="^checkmail_"))
        application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_member))
        application.add_handler(MessageHandler((filters.TEXT | filters.Document.ALL | filters.CAPTION) & (~filters.COMMAND), handle_message))

        if application.job_queue:
            # Sync job every 30 seconds (Railway can handle this)
            async def sync_wrapper(context: ContextTypes.DEFAULT_TYPE):
                await sync_database_to_telegram(context.application)
            
            # Birthday check daily at 8 AM
            async def birthday_wrapper(context: ContextTypes.DEFAULT_TYPE):
                await check_birthdays(context.application)
            
            # Daily greeting at 7 AM
            async def greeting_wrapper(context: ContextTypes.DEFAULT_TYPE):
                await send_daily_ai_greeting(context.application)
            
            application.job_queue.run_repeating(sync_wrapper, interval=30, first=10)
            application.job_queue.run_daily(birthday_wrapper, time=datetime.now().replace(hour=8, minute=0, second=0, microsecond=0).time())
            application.job_queue.run_daily(greeting_wrapper, time=datetime.now().replace(hour=7, minute=0, second=0, microsecond=0).time())
            
            print("✅ Railway Jobs gestartet (Sync: 30s, Daily: 7/8 AM)")
        
        print("🚀 Bot läuft auf Railway - 24/7 Polling aktiv")
        application.run_polling(drop_pending_updates=True)
        
    elif is_vercel:
        print("⚡ MIB Bot System v1.0 (VERCEL - Webhook Mode)")
        # Vercel mode is handled by api/index.py
        pass
        
    else:
        print("💻 MIB Bot System v1.0 wird gestartet (LOKAL)...")
        # Local development
        application = Application.builder().token(TELEGRAM_TOKEN).build()

        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("hilfe", help_command))
        application.add_handler(CommandHandler("birthday", birthday_command))
        application.add_handler(CommandHandler("stats", stats_command))
        application.add_handler(CommandHandler("search", search_command))
        application.add_handler(CommandHandler("rank", rank_command))
        application.add_handler(CommandHandler("report", report_command))
        application.add_handler(CommandHandler("daily", daily_command))
        application.add_handler(CommandHandler("check", check_command))
        application.add_handler(CommandHandler("scene", scene_command))
        application.add_handler(CommandHandler("tempmail", tempmail_command))
        application.add_handler(CommandHandler("fakeid", fakeid_command))
        application.add_handler(CommandHandler("ip", ip_command))
        application.add_handler(CommandHandler("coin", coin_command))
        application.add_handler(CommandHandler("port", port_command))
        application.add_handler(CommandHandler("genpass", genpass_command))
        application.add_handler(CommandHandler("encode", encode_command))
        application.add_handler(CommandHandler("decode", decode_command))
        application.add_handler(CommandHandler("qr", qr_command))
        application.add_handler(CommandHandler("blitzdings", blitzdings_command))
        application.add_handler(CallbackQueryHandler(check_mail_callback, pattern="^checkmail_"))
        application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_member))
        application.add_handler(MessageHandler((filters.TEXT | filters.Document.ALL | filters.CAPTION) & (~filters.COMMAND), handle_message))

        if application.job_queue:
            async def sync_wrapper(context: ContextTypes.DEFAULT_TYPE):
                await sync_database_to_telegram(context.application)
            
            application.job_queue.run_repeating(sync_wrapper, interval=5, first=5)
            print("✅ Sync-Service gestartet (Interval: 5s)")
        
        application.run_polling()