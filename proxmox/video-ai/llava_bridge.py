#!/usr/bin/env python3
"""LLaVA Bridge - on each completed Frigate event, fetch snapshot, narrate via LLaVA, store."""
import os, json, base64, requests, sqlite3
from datetime import datetime
import paho.mqtt.client as mqtt

MQTT_HOST    = os.getenv("MQTT_HOST",    "192.168.1.18")
FRIGATE_URL  = os.getenv("FRIGATE_URL",  "http://192.168.1.18:5000")
OLLAMA_URL   = os.getenv("OLLAMA_URL",   "http://192.168.1.110:11434")
LLAVA_MODEL  = os.getenv("LLAVA_MODEL",  "llava:13b")
DB_PATH      = "/data/narrations.db"

os.makedirs("/data", exist_ok=True)
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.execute("""CREATE TABLE IF NOT EXISTS narrations (
    id TEXT PRIMARY KEY, camera TEXT, label TEXT,
    start_time INTEGER, narration TEXT, created_at TEXT)""")
db.commit()

def narrate(event_id, camera, label, start_time):
    if db.execute("SELECT id FROM narrations WHERE id=?", (event_id,)).fetchone():
        return
    r = requests.get(f"{FRIGATE_URL}/api/events/{event_id}/snapshot.jpg", timeout=10)
    if r.status_code != 200:
        return
    img_b64 = base64.b64encode(r.content).decode()
    prompt = (f"Security camera '{camera}' detected a '{label}'. "
              "Describe what you see in 1-2 sentences. Focus on: number of people/objects, "
              "position, and any notable activity or behaviour.")
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/generate", json={
            "model": LLAVA_MODEL, "prompt": prompt,
            "images": [img_b64], "stream": False}, timeout=120)
        narration = resp.json().get("response", "").strip()
        db.execute("INSERT OR REPLACE INTO narrations VALUES (?,?,?,?,?,?)",
            (event_id, camera, label, start_time, narration, datetime.utcnow().isoformat()))
        db.commit()
        print(f"[{camera}] {label}: {narration[:80]}...")
    except Exception as e:
        print(f"LLaVA error {event_id}: {e}")

def on_connect(client, userdata, flags, rc):
    print(f"Connected to MQTT (rc={rc})")
    client.subscribe("frigate/events")

def on_message(client, userdata, msg):
    try:
        p = json.loads(msg.payload)
        if p.get("type") == "end":
            a = p.get("after", {})
            if a.get("label") in ["person", "car", "dog"]:
                narrate(a["id"], a.get("camera","?"), a.get("label","?"), a.get("start_time",0))
    except Exception as e:
        print(f"Message error: {e}")

client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message
client.connect(MQTT_HOST, 1883, 60)
print(f"LLaVA Bridge running - connected to {MQTT_HOST}")
client.loop_forever()
