#!/usr/bin/env python3
"""
Person Re-Identification Service for Frigate.

Matches the same person across cameras using appearance features (clothing,
body shape) instead of face recognition. Works with any camera angle.

Flow:
  1. Frigate MQTT event (person detected)
  2. Download cropped person snapshot
  3. Extract appearance embedding via OSNet
  4. Store in Qdrant (person_reid collection)
  5. Search for recent matches across other cameras
  6. If a match has a face name, propagate identity
  7. Log trajectories and notify
"""
import os, json, time, hashlib, threading, sqlite3
from datetime import datetime, timedelta
import requests
import numpy as np
import paho.mqtt.client as mqtt

# --- Config ---
MQTT_HOST      = os.getenv("MQTT_HOST", "192.168.1.18")
FRIGATE_URL    = os.getenv("FRIGATE_URL", "http://192.168.1.18:5000")
QDRANT_HOST    = os.getenv("QDRANT_HOST", "qdrant-video")
QDRANT_PORT    = int(os.getenv("QDRANT_PORT", "6333"))
COMPREFACE_URL = os.getenv("COMPREFACE_URL", "http://compreface:80")
COMPREFACE_KEY = os.getenv("COMPREFACE_API_KEY", "")
DB_PATH        = "/data/reid.db"

# Re-ID parameters
MATCH_THRESHOLD    = float(os.getenv("REID_THRESHOLD", "0.60"))     # cosine similarity (CLIP)
TIME_WINDOW        = int(os.getenv("REID_TIME_WINDOW", "1800"))     # 30 min
EMBEDDING_DIM      = 512  # OSNet output dimension
COLLECTION_NAME    = "person_reid"
FACE_CAMERAS       = [s.strip() for s in os.getenv("FACE_CAMERAS", "tapo_46,eufy_living_pan").split(",")]
MIN_CROP_SIZE      = int(os.getenv("MIN_CROP_SIZE", "64"))          # min person crop px

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("reid")

# --- Database ---
os.makedirs("/data", exist_ok=True)
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.execute("""CREATE TABLE IF NOT EXISTS trajectories (
    track_id TEXT, person_name TEXT, camera TEXT, timestamp REAL,
    event_id TEXT, confidence REAL,
    PRIMARY KEY (event_id, camera))""")
db.execute("""CREATE TABLE IF NOT EXISTS identities (
    track_id TEXT PRIMARY KEY, person_name TEXT, first_seen REAL,
    last_seen REAL, cameras TEXT, sighting_count INTEGER)""")
db.commit()

# --- Qdrant ---
from qdrant_client import QdrantClient
from qdrant_client.models import (
    VectorParams, Distance, PointStruct,
    Filter, FieldCondition, Range
)

qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

def init_qdrant():
    """Create the person_reid collection if it doesn't exist."""
    collections = [c.name for c in qdrant.get_collections().collections]
    if COLLECTION_NAME not in collections:
        qdrant.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )
        log.info(f"Created Qdrant collection: {COLLECTION_NAME}")
    else:
        log.info(f"Qdrant collection exists: {COLLECTION_NAME}")

# --- OSNet Model ---
_model = None
_transform = None

def load_model():
    """Load CLIP ViT-B-32 for person Re-ID (same model used by clip-indexer).

    CLIP produces excellent appearance embeddings that capture clothing, body shape,
    and overall visual similarity — ideal for cross-camera person matching.
    """
    global _model, _transform, EMBEDDING_DIM
    import open_clip

    log.info("Loading CLIP ViT-B-32 for person Re-ID...")

    _model, _, _transform = open_clip.create_model_and_transforms(
        'ViT-B-32', pretrained='openai'
    )
    _model.eval()
    EMBEDDING_DIM = 512  # CLIP ViT-B-32 output
    log.info("CLIP ViT-B-32 loaded — embedding dim: 512")

def extract_embedding(image_bytes):
    """Extract appearance embedding from a person crop using CLIP."""
    import torch
    from PIL import Image
    from io import BytesIO

    img = Image.open(BytesIO(image_bytes)).convert('RGB')

    # Check minimum size
    if img.width < MIN_CROP_SIZE or img.height < MIN_CROP_SIZE:
        return None

    tensor = _transform(img).unsqueeze(0)
    with torch.no_grad():
        embedding = _model.encode_image(tensor).squeeze().numpy()

    # Normalize to unit vector for cosine similarity
    norm = np.linalg.norm(embedding)
    if norm > 0:
        embedding = embedding / norm

    return embedding.tolist()

# --- Face Recognition (for identity propagation) ---
def try_face_recognition(image_bytes, camera):
    """Try to recognize a face in the image via CompreFace."""
    if not COMPREFACE_KEY or camera not in FACE_CAMERAS:
        return None, 0
    try:
        resp = requests.post(
            f"{COMPREFACE_URL}/api/v1/recognition/recognize?det_prob_threshold=0.3",
            headers={"x-api-key": COMPREFACE_KEY},
            files={"file": ("snap.jpg", image_bytes, "image/jpeg")},
            timeout=10)
        data = resp.json()
        results = data.get("result", [])
        if not results:
            return None, 0
        subjects = results[0].get("subjects", [])
        if not subjects:
            return None, 0
        best = max(subjects, key=lambda x: x.get("similarity", 0))
        if best.get("similarity", 0) >= 0.75:
            return best["subject"], best["similarity"]
    except Exception as e:
        log.warning(f"Face recognition error: {e}")
    return None, 0

# --- Core Re-ID Logic ---
def generate_track_id(event_id):
    """Generate a deterministic point ID for Qdrant."""
    return int(hashlib.md5(event_id.encode()).hexdigest()[:15], 16)

def find_matches(embedding, current_camera, current_time):
    """Search Qdrant for matching appearances in the time window."""
    cutoff = current_time - TIME_WINDOW

    try:
        # Try new API first (qdrant-client >= 1.7), fall back to legacy
        try:
            from qdrant_client.models import QueryRequest
            results = qdrant.query_points(
                collection_name=COLLECTION_NAME,
                query=embedding,
                limit=10,
                query_filter=Filter(
                    must=[
                        FieldCondition(
                            key="timestamp",
                            range=Range(gte=cutoff),
                        )
                    ]
                ),
                score_threshold=MATCH_THRESHOLD,
            ).points
        except (ImportError, AttributeError, TypeError):
            results = qdrant.search(
                collection_name=COLLECTION_NAME,
                query_vector=embedding,
                limit=10,
                query_filter=Filter(
                    must=[
                        FieldCondition(
                            key="timestamp",
                            range=Range(gte=cutoff),
                        )
                    ]
                ),
                score_threshold=MATCH_THRESHOLD,
            )

        # Filter to other cameras (cross-camera matching)
        matches = []
        for r in results:
            payload = r.payload if hasattr(r, 'payload') else {}
            if payload.get("camera") != current_camera:
                matches.append({
                    "event_id": payload.get("event_id"),
                    "camera": payload.get("camera"),
                    "timestamp": payload.get("timestamp"),
                    "person_name": payload.get("person_name"),
                    "track_id": payload.get("track_id"),
                    "score": r.score,
                })
        return matches
    except Exception as e:
        log.error(f"Qdrant search error: {e}")
        return []

def store_embedding(event_id, camera, timestamp, embedding, person_name=None, track_id=None):
    """Store a person appearance embedding in Qdrant."""
    point_id = generate_track_id(event_id)
    if not track_id:
        track_id = f"person_{point_id}"

    try:
        qdrant.upsert(
            collection_name=COLLECTION_NAME,
            points=[PointStruct(
                id=point_id,
                vector=embedding,
                payload={
                    "event_id": event_id,
                    "camera": camera,
                    "timestamp": timestamp,
                    "person_name": person_name or "",
                    "track_id": track_id,
                }
            )]
        )
    except Exception as e:
        log.error(f"Qdrant upsert error: {e}")

def update_identity(track_id, person_name, camera, timestamp):
    """Update the identity tracker in SQLite."""
    existing = db.execute("SELECT cameras, sighting_count FROM identities WHERE track_id=?",
                         (track_id,)).fetchone()
    if existing:
        cameras = set(existing[0].split(","))
        cameras.add(camera)
        db.execute("""UPDATE identities SET person_name=?, last_seen=?,
                      cameras=?, sighting_count=sighting_count+1
                      WHERE track_id=?""",
                   (person_name, timestamp, ",".join(sorted(cameras)), track_id))
    else:
        db.execute("""INSERT OR REPLACE INTO identities VALUES (?,?,?,?,?,?)""",
                   (track_id, person_name, timestamp, timestamp, camera, 1))
    db.commit()

def process_event(event_id, camera, label, start_time):
    """Main Re-ID pipeline for a person detection event."""
    if label != "person":
        return

    # Check if already processed
    if db.execute("SELECT event_id FROM trajectories WHERE event_id=?",
                  (event_id,)).fetchone():
        return

    # Download cropped person snapshot
    try:
        r = requests.get(
            f"{FRIGATE_URL}/api/events/{event_id}/snapshot.jpg?crop=1&quality=90",
            timeout=10)
        if r.status_code != 200:
            return
    except Exception as e:
        log.error(f"Snapshot download error: {e}")
        return

    image_bytes = r.content

    # Extract appearance embedding
    embedding = extract_embedding(image_bytes)
    if embedding is None:
        log.debug(f"[{camera}] Crop too small, skipping")
        return

    # Try face recognition on face-capable cameras
    face_name, face_conf = try_face_recognition(image_bytes, camera)

    # Search for matching appearances across other cameras
    matches = find_matches(embedding, camera, start_time)

    # Determine identity
    person_name = face_name
    track_id = None
    best_match = None

    if matches:
        best_match = max(matches, key=lambda m: m["score"])
        track_id = best_match["track_id"]

        # If we don't have a face name but a match does, inherit it
        if not person_name and best_match.get("person_name"):
            person_name = best_match["person_name"]
            log.info(f"[{camera}] Identity propagated from {best_match['camera']}: "
                     f"{person_name} (appearance match {best_match['score']:.0%})")

        # If we have a face name and match doesn't, update the match
        if person_name and not best_match.get("person_name"):
            try:
                match_point_id = generate_track_id(best_match["event_id"])
                qdrant.set_payload(
                    collection_name=COLLECTION_NAME,
                    payload={"person_name": person_name},
                    points=[match_point_id],
                )
                log.info(f"[{best_match['camera']}] Retroactively identified as {person_name}")
            except Exception:
                pass

    if not track_id:
        track_id = f"person_{generate_track_id(event_id)}"

    # Store this sighting
    store_embedding(event_id, camera, start_time, embedding, person_name, track_id)

    # Log trajectory
    confidence = best_match["score"] if best_match else (face_conf or 0)
    db.execute("INSERT OR IGNORE INTO trajectories VALUES (?,?,?,?,?,?)",
               (track_id, person_name or "", camera, start_time, event_id, confidence))
    db.commit()

    if person_name:
        update_identity(track_id, person_name, camera, start_time)

    # Log result
    if person_name and best_match:
        log.info(f"[{camera}] {person_name} — matched from {best_match['camera']} "
                 f"({best_match['score']:.0%} appearance, {time.time()-best_match['timestamp']:.0f}s ago)")
    elif person_name:
        log.info(f"[{camera}] {person_name} — identified by face ({face_conf:.0%})")
    elif best_match:
        log.info(f"[{camera}] Unknown person — matches {best_match['camera']} "
                 f"({best_match['score']:.0%}, {time.time()-best_match['timestamp']:.0f}s ago)")
    else:
        log.info(f"[{camera}] New unknown person")

# --- MQTT ---
def on_connect(client, userdata, flags, rc):
    log.info(f"Connected to MQTT (rc={rc})")
    client.subscribe("frigate/events")

def on_message(client, userdata, msg):
    try:
        p = json.loads(msg.payload)
        if p.get("type") == "end":
            a = p.get("after", {})
            threading.Thread(target=process_event, args=(
                a["id"], a.get("camera", "?"), a.get("label", "?"),
                a.get("start_time", 0)
            ), daemon=True).start()
    except Exception as e:
        log.error(f"MQTT error: {e}")

# --- Trajectory Query API ---
def get_recent_trajectories(minutes=60):
    """Get recent person trajectories."""
    cutoff = time.time() - (minutes * 60)
    rows = db.execute("""
        SELECT track_id, person_name, camera, timestamp, confidence
        FROM trajectories WHERE timestamp > ?
        ORDER BY track_id, timestamp
    """, (cutoff,)).fetchall()

    tracks = {}
    for track_id, name, camera, ts, conf in rows:
        if track_id not in tracks:
            tracks[track_id] = {"name": name, "path": []}
        tracks[track_id]["path"].append({
            "camera": camera,
            "time": datetime.fromtimestamp(ts).strftime("%H:%M:%S"),
            "confidence": conf,
        })
        if name and not tracks[track_id]["name"]:
            tracks[track_id]["name"] = name

    return tracks

def print_trajectories():
    """Print recent trajectories to log."""
    tracks = get_recent_trajectories(60)
    if not tracks:
        log.info("No trajectories in the last hour")
        return
    log.info(f"=== Trajectories (last hour): {len(tracks)} people ===")
    for tid, info in tracks.items():
        name = info["name"] or "Unknown"
        path = " → ".join(f"{p['camera']}({p['time']})" for p in info["path"])
        log.info(f"  {name}: {path}")

# --- Main ---
if __name__ == "__main__":
    log.info("Person Re-ID Service starting...")
    load_model()
    init_qdrant()

    # Print trajectories every 5 minutes
    def trajectory_logger():
        while True:
            time.sleep(300)
            try:
                print_trajectories()
            except Exception as e:
                log.error(f"Trajectory log error: {e}")

    threading.Thread(target=trajectory_logger, daemon=True).start()

    mqtt_client = mqtt.Client()
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    mqtt_client.connect(MQTT_HOST, 1883, 60)
    log.info(f"Re-ID Service running — connected to {MQTT_HOST}")
    mqtt_client.loop_forever()
