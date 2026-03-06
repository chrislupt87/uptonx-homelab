#!/usr/bin/env python3
"""Face Trainer - recognize faces via CompreFace, ask via Telegram for unknowns."""
import os, json, base64, io, time, requests, sqlite3, threading
from datetime import datetime
import paho.mqtt.client as mqtt
from PIL import Image

MQTT_HOST         = os.getenv("MQTT_HOST",         "192.168.1.18")
FRIGATE_URL       = os.getenv("FRIGATE_URL",        "http://192.168.1.18:5000")
COMPREFACE_URL    = os.getenv("COMPREFACE_URL",     "http://compreface:8000")
COMPREFACE_APIKEY = os.getenv("COMPREFACE_API_KEY", "")
TELEGRAM_TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID  = os.getenv("TELEGRAM_CHAT_ID",  "")
DB_PATH           = "/data/faces.db"
CONFIDENCE        = 0.75

os.makedirs("/data", exist_ok=True)
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.execute("""CREATE TABLE IF NOT EXISTS detections (
    event_id TEXT PRIMARY KEY, camera TEXT, timestamp TEXT,
    name TEXT, confidence REAL, snapshot_b64 TEXT)""")
db.execute("""CREATE TABLE IF NOT EXISTS pending (
    event_id TEXT PRIMARY KEY, camera TEXT, timestamp TEXT, snapshot_b64 TEXT)""")
db.commit()

bot = None
pending_reply = {}

def init_telegram():
    global bot
    if not TELEGRAM_TOKEN:
        print("No Telegram token configured - running without notifications")
        return
    try:
        import telegram as tg
        bot = tg.Bot(token=TELEGRAM_TOKEN)
        print("Telegram bot initialized")
    except Exception as e:
        print(f"Telegram init error: {e}")

def recognize_face(snapshot_bytes):
    if not COMPREFACE_APIKEY:
        return None, 0
    try:
        resp = requests.post(
            f"{COMPREFACE_URL}/api/v1/recognition/faces",
            headers={"x-api-key": COMPREFACE_APIKEY},
            files={"file": ("snap.jpg", snapshot_bytes, "image/jpeg")},
            timeout=15)
        data = resp.json()
        results = data.get("result", [])
        if not results:
            return None, 0
        subject = results[0].get("subjects", [])
        if not subject:
            return None, 0
        best = max(subject, key=lambda x: x.get("similarity", 0))
        if best.get("similarity", 0) >= CONFIDENCE:
            return best["subject"], best["similarity"]
        return None, best.get("similarity", 0)
    except Exception as e:
        print(f"CompreFace error: {e}")
        return None, 0

def train_face(name, snapshot_bytes):
    if not COMPREFACE_APIKEY:
        return False
    try:
        resp = requests.post(
            f"{COMPREFACE_URL}/api/v1/recognition/faces",
            headers={"x-api-key": COMPREFACE_APIKEY},
            data={"subject": name},
            files={"file": ("snap.jpg", snapshot_bytes, "image/jpeg")},
            timeout=15)
        return resp.status_code == 200
    except Exception as e:
        print(f"Train error: {e}")
        return False

def ask_telegram(event_id, camera, snapshot_bytes):
    if not bot:
        print(f"No Telegram - unknown face on {camera} event {event_id}")
        return
    try:
        caption = (f"Unknown face detected\n"
                   f"Camera: {camera}\n"
                   f"{datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                   f"Reply with a name to train, or skip to ignore.")
        bot.send_photo(chat_id=TELEGRAM_CHAT_ID,
            photo=io.BytesIO(snapshot_bytes), caption=caption)
        pending_reply["last"] = {"event_id": event_id, "snapshot": snapshot_bytes}
        print(f"Sent unknown face to Telegram for {camera}")
    except Exception as e:
        print(f"Telegram send error: {e}")

def process_event(event_id, camera, label, start_time):
    if label != "person":
        return
    if db.execute("SELECT event_id FROM detections WHERE event_id=?", (event_id,)).fetchone():
        return
    r = requests.get(f"{FRIGATE_URL}/api/events/{event_id}/snapshot.jpg", timeout=10)
    if r.status_code != 200:
        return
    snapshot_bytes = r.content
    name, conf = recognize_face(snapshot_bytes)
    ts = datetime.utcfromtimestamp(start_time).isoformat() if start_time else datetime.utcnow().isoformat()
    if name:
        db.execute("INSERT OR REPLACE INTO detections VALUES (?,?,?,?,?,)",
            (event_id, camera, ts, name, conf))
        db.commit()
        print(f"[{camera}] Recognized: {name} ({conf:.0%})")
        if bot:
            bot.send_message(chat_id=TELEGRAM_CHAT_ID,
                text=f"{name} detected on {camera} ({conf:.0%} confidence)")
    else:
        db.execute("INSERT OR IGNORE INTO pending VALUES (?,?,?,?)",
            (event_id, camera, ts, base64.b64encode(snapshot_bytes).decode()))
        db.commit()
        print(f"[{camera}] Unknown face - asking via Telegram")
        ask_telegram(event_id, camera, snapshot_bytes)

def on_connect(client, userdata, flags, rc):
    print(f"Connected to MQTT (rc={rc})")
    client.subscribe("frigate/events")

def on_message(client, userdata, msg):
    try:
        p = json.loads(msg.payload)
        if p.get("type") == "end":
            a = p.get("after", {})
            threading.Thread(target=process_event, args=(
                a["id"], a.get("camera","?"), a.get("label","?"), a.get("start_time",0)
            ), daemon=True).start()
    except Exception as e:
        print(f"MQTT error: {e}")

def start_telegram_polling():
    if not TELEGRAM_TOKEN:
        return
    try:
        from telegram.ext import Updater, MessageHandler, CommandHandler, Filters
        def handle_reply(update, context):
            text = update.message.text.strip()
            if text.lower() == "skip":
                update.message.reply_text("Skipped.")
                pending_reply.clear()
                return
            if "last" not in pending_reply:
                update.message.reply_text("No pending face to label.")
                return
            pending = pending_reply.pop("last")
            success = train_face(text, pending["snapshot"])
            if success:
                update.message.reply_text(f"Trained! Future appearances of {text} will be auto-identified.")
            else:
                update.message.reply_text("Training failed - check CompreFace logs.")

        def handle_stats(update, context):
            known = db.execute("SELECT name, COUNT(*) FROM detections GROUP BY name ORDER BY COUNT(*) DESC").fetchall()
            if not known:
                update.message.reply_text("No detections logged yet.")
                return
            msg = "Detection stats:\n\n"
            for name, count in known:
                msg += f"  {name}: {count} detections\n"
            update.message.reply_text(msg)

        def handle_scan(update, context):
            update.message.reply_text("Scanning recent events for unknown faces...")
            try:
                events = requests.get(f"{FRIGATE_URL}/api/events?limit=200&label=person", timeout=15).json()
                unknown_count = 0
                for evt in events:
                    eid = evt["id"]
                    if db.execute("SELECT event_id FROM detections WHERE event_id=?", (eid,)).fetchone():
                        continue
                    r = requests.get(f"{FRIGATE_URL}/api/events/{eid}/snapshot.jpg", timeout=10)
                    if r.status_code != 200:
                        continue
                    name, conf = recognize_face(r.content)
                    if name:
                        db.execute("INSERT OR IGNORE INTO detections VALUES (?,?,?,?,?,)",
                            (eid, evt.get("camera","?"), datetime.utcnow().isoformat(), name, conf))
                        db.commit()
                    else:
                        unknown_count += 1
                        time.sleep(2)
                        ask_telegram(eid, evt.get("camera","?"), r.content)
                update.message.reply_text(f"Scan complete. {unknown_count} unknown faces sent for labelling.")
            except Exception as e:
                update.message.reply_text(f"Scan error: {e}")

        updater = Updater(token=TELEGRAM_TOKEN)
        dp = updater.dispatcher
        dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_reply))
        dp.add_handler(CommandHandler("scan", handle_scan))
        dp.add_handler(CommandHandler("stats", handle_stats))
        updater.start_polling()
        print("Telegram bot polling started")
    except Exception as e:
        print(f"Telegram polling error: {e}")

init_telegram()
threading.Thread(target=start_telegram_polling, daemon=True).start()

mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.connect(MQTT_HOST, 1883, 60)
print(f"Face Trainer running - connected to {MQTT_HOST}")
mqtt_client.loop_forever()
