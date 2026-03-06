#!/usr/bin/env python3
"""CLIP Indexer - polls Frigate events, embeds snapshots into Qdrant for semantic search."""
import os, time, requests, torch
from pathlib import Path
from PIL import Image
import open_clip
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

FRIGATE_URL = os.getenv("FRIGATE_URL", "http://192.168.1.18:5000")
QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant-video")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
COLLECTION = "frigate_events"

model, _, preprocess = open_clip.create_model_and_transforms("ViT-B-32", pretrained="openai")
model.eval()
tokenizer = open_clip.get_tokenizer("ViT-B-32")
qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

try:
    qdrant.get_collection(COLLECTION)
except Exception:
    qdrant.create_collection(COLLECTION,
        vectors_config=VectorParams(size=512, distance=Distance.COSINE))
    print(f"Created collection: {COLLECTION}")

indexed = set()

def embed_image(path):
    img = preprocess(Image.open(path).convert("RGB")).unsqueeze(0)
    with torch.no_grad():
        return model.encode_image(img).squeeze().numpy().tolist()

def poll_frigate():
    try:
        events = requests.get(f"{FRIGATE_URL}/api/events?limit=100", timeout=10).json()
        new = 0
        for evt in events:
            eid = evt["id"]
            if eid in indexed:
                continue
            r = requests.get(f"{FRIGATE_URL}/api/events/{eid}/snapshot.jpg", timeout=10)
            if r.status_code != 200:
                continue
            tmp = Path(f"/tmp/{eid}.jpg")
            tmp.write_bytes(r.content)
            vec = embed_image(tmp)
            qdrant.upsert(COLLECTION, points=[PointStruct(
                id=hash(eid) % (2**63), vector=vec,
                payload={"event_id": eid, "camera": evt.get("camera",""),
                         "label": evt.get("label",""), "start_time": evt.get("start_time",0),
                         "score": evt.get("top_score",0)}
            )])
            indexed.add(eid)
            tmp.unlink()
            new += 1
        if new:
            print(f"Indexed {new} new events. Total: {len(indexed)}")
    except Exception as e:
        print(f"Poll error: {e}")

print("CLIP Indexer running - polling every 60s")
while True:
    poll_frigate()
    time.sleep(60)
