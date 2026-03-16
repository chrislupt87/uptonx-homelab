#!/usr/bin/env python3
"""
Historical Video Import — process Nest/Eufy video files through the AI pipeline.

Extracts frames from video files, runs object detection (Frigate), face detection
(CompreFace), CLIP embedding (Qdrant), and optional LLaVA narration (Ollama).

Usage:
    # Import a single video
    python video-import.py /path/to/video.mp4 --camera eufy_kitchen

    # Batch import a directory
    python video-import.py /path/to/videos/ --camera nest_entrance --recursive

    # Import with specific options
    python video-import.py /path/to/video.mp4 --camera eufy_kitchen \
        --interval 2 --narrate --faces-only

    # Dry run — show what would be processed
    python video-import.py /path/to/videos/ --camera nest_entrance --dry-run

    # Import Frigate recordings directly (already in segment format)
    python video-import.py /path/to/recordings/ --camera eufy_kitchen --frigate-import

Sources:
    Nest: Export clips from Google Home app → Settings → Camera → Video History
    Eufy: Download from Eufy Security app, or pull from SD card / base station
    Frigate NAS archive: /mnt/nfs/frigate on aux (.18)
"""
import os
import sys
import json
import time
import argparse
import hashlib
import sqlite3
import base64
import tempfile
import subprocess
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# --- Configuration ---
FRIGATE_URL    = os.getenv("FRIGATE_URL",    "http://192.168.1.18:5000")
COMPREFACE_URL = os.getenv("COMPREFACE_URL", "http://192.168.1.69:8000")
COMPREFACE_KEY = os.getenv("COMPREFACE_API_KEY", "81491332-1960-4d3c-9c8e-a3be14b4e853")
QDRANT_URL     = os.getenv("QDRANT_URL",     "http://192.168.1.69:6333")
OLLAMA_URL     = os.getenv("OLLAMA_URL",     "http://192.168.1.110:11434")
LLAVA_MODEL    = os.getenv("LLAVA_MODEL",    "llava:13b")
CLIP_SERVICE   = os.getenv("CLIP_SERVICE",   "http://192.168.1.69:8000")  # if clip-indexer exposes API

DB_PATH        = os.getenv("IMPORT_DB", "/tmp/video-import.db")
COLLECTION     = "frigate_events"

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".ts", ".m4v", ".webm"}

import requests
try:
    from PIL import Image
    from io import BytesIO
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


def init_db():
    """Track which frames have been processed to allow resuming."""
    db = sqlite3.connect(DB_PATH)
    db.execute("""CREATE TABLE IF NOT EXISTS processed_frames (
        hash TEXT PRIMARY KEY,
        video_path TEXT,
        frame_time REAL,
        camera TEXT,
        objects TEXT,
        faces TEXT,
        narration TEXT,
        clip_indexed INTEGER DEFAULT 0,
        created_at TEXT
    )""")
    db.commit()
    return db


def is_processed(db, frame_hash):
    return db.execute("SELECT 1 FROM processed_frames WHERE hash=?", (frame_hash,)).fetchone() is not None


def mark_processed(db, frame_hash, video_path, frame_time, camera, objects=None, faces=None, narration=None, clip_indexed=False):
    db.execute(
        "INSERT OR REPLACE INTO processed_frames VALUES (?,?,?,?,?,?,?,?,?)",
        (frame_hash, str(video_path), frame_time, camera,
         json.dumps(objects or []), json.dumps(faces or []),
         narration or "", 1 if clip_indexed else 0,
         datetime.now().isoformat())
    )
    db.commit()


def extract_frames(video_path, interval=2.0, max_frames=None):
    """Extract frames from video at given interval using ffmpeg."""
    # Get video duration
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video_path)],
        capture_output=True, text=True
    )
    duration = float(probe.stdout.strip()) if probe.stdout.strip() else 0
    if duration == 0:
        print(f"  Could not determine duration for {video_path}")
        return

    num_frames = int(duration / interval)
    if max_frames:
        num_frames = min(num_frames, max_frames)

    print(f"  Duration: {duration:.1f}s — extracting {num_frames} frames (every {interval}s)")

    for i in range(num_frames):
        t = i * interval
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name

        cmd = [
            "ffmpeg", "-ss", str(t), "-i", str(video_path),
            "-vframes", "1", "-q:v", "2", "-y", tmp_path
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode == 0 and os.path.getsize(tmp_path) > 0:
            with open(tmp_path, "rb") as f:
                frame_bytes = f.read()
            os.unlink(tmp_path)
            yield t, frame_bytes
        else:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


def frame_hash(video_path, frame_time):
    """Unique hash for a specific frame in a video."""
    key = f"{video_path}:{frame_time:.2f}"
    return hashlib.md5(key.encode()).hexdigest()


def detect_objects_frigate(frame_bytes, camera):
    """Use Frigate's detection if available (requires the detect endpoint)."""
    # Frigate doesn't have a standalone detection API for arbitrary images.
    # We'll use a simple approach: check if there's motion/objects visible.
    # For now, we rely on CompreFace for faces and CLIP for semantic search.
    return []


def detect_faces(frame_bytes):
    """Detect and recognize faces via CompreFace."""
    try:
        resp = requests.post(
            f"{COMPREFACE_URL}/api/v1/recognition/recognize",
            headers={"x-api-key": COMPREFACE_KEY},
            files={"file": ("frame.jpg", frame_bytes, "image/jpeg")},
            params={"limit": 5, "det_prob_threshold": 0.5, "prediction_count": 1},
            timeout=15,
        )
        if resp.status_code == 200:
            results = resp.json().get("result", [])
            faces = []
            for r in results:
                box = r.get("box", {})
                subjects = r.get("subjects", [])
                name = subjects[0]["subject"] if subjects else "unknown"
                similarity = subjects[0]["similarity"] if subjects else 0
                faces.append({
                    "name": name,
                    "similarity": round(similarity, 3),
                    "box": box,
                    "probability": round(r.get("box", {}).get("probability", 0), 3),
                })
            return faces
    except Exception as e:
        pass  # CompreFace may not be reachable
    return []


def embed_clip(frame_bytes, metadata):
    """Generate CLIP embedding and store in Qdrant."""
    try:
        # Try the clip-indexer's internal API if available
        # Fall back to direct open_clip if installed
        try:
            import open_clip
            import torch

            model, _, preprocess = open_clip.create_model_and_transforms(
                "ViT-B-32", pretrained="openai"
            )
            model.eval()

            img = Image.open(BytesIO(frame_bytes)).convert("RGB")
            img_tensor = preprocess(img).unsqueeze(0)

            with torch.no_grad():
                embedding = model.encode_image(img_tensor)
                embedding = embedding / embedding.norm(dim=-1, keepdim=True)
                vector = embedding.squeeze().tolist()

            # Store in Qdrant
            point_id = hashlib.md5(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
            resp = requests.put(
                f"{QDRANT_URL}/collections/{COLLECTION}/points",
                json={
                    "points": [{
                        "id": point_id,
                        "vector": vector,
                        "payload": metadata,
                    }]
                },
                timeout=15,
            )
            return resp.status_code == 200
        except ImportError:
            # No local open_clip — skip embedding
            return False
    except Exception as e:
        return False


def narrate_llava(frame_bytes, camera, detected_objects=None):
    """Generate a natural language description via LLaVA."""
    try:
        img_b64 = base64.b64encode(frame_bytes).decode()
        context = f"Camera: {camera}."
        if detected_objects:
            context += f" Detected: {', '.join(detected_objects)}."

        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": LLAVA_MODEL,
                "prompt": (
                    f"{context} Describe what you see in this security camera frame "
                    "in 1-2 sentences. Focus on people, activity, and anything notable."
                ),
                "images": [img_b64],
                "stream": False,
            },
            timeout=120,
        )
        if resp.status_code == 200:
            return resp.json().get("response", "").strip()
    except Exception:
        pass
    return None


def import_to_frigate(video_path, camera):
    """
    Copy video file into Frigate's recording structure for native playback.
    Frigate stores recordings as: /media/frigate/recordings/{camera}/{YYYY-MM}/{DD}/{HH}/{MM.SS.mp4}
    """
    # Get video creation time from metadata
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format_tags=creation_time",
         "-of", "csv=p=0", str(video_path)],
        capture_output=True, text=True
    )
    creation_time = probe.stdout.strip()
    if creation_time:
        try:
            dt = datetime.fromisoformat(creation_time.replace("Z", "+00:00"))
        except ValueError:
            dt = datetime.fromtimestamp(os.path.getmtime(video_path))
    else:
        dt = datetime.fromtimestamp(os.path.getmtime(video_path))

    # Build Frigate recording path
    rec_dir = f"/media/frigate/recordings/{camera}/{dt.strftime('%Y-%m')}/{dt.strftime('%d')}/{dt.strftime('%H')}"
    rec_file = f"{dt.strftime('%M')}.{dt.strftime('%S')}.mp4"
    rec_path = f"{rec_dir}/{rec_file}"

    print(f"  Frigate import: {video_path.name} → {rec_path}")

    # Re-encode to Frigate-compatible segment format if needed
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp_path = tmp.name

    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-c:v", "copy", "-c:a", "aac",
        "-movflags", "+faststart",
        "-y", tmp_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=300)

    if result.returncode == 0:
        # Copy to Frigate host via SSH
        ssh_mkdir = subprocess.run(
            ["ssh", "root@192.168.1.18", f"mkdir -p {rec_dir}"],
            capture_output=True, timeout=10
        )
        scp = subprocess.run(
            ["scp", tmp_path, f"root@192.168.1.18:{rec_path}"],
            capture_output=True, timeout=120
        )
        os.unlink(tmp_path)
        return scp.returncode == 0
    else:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        return False


def process_video(video_path, camera, args, db):
    """Process a single video through the AI pipeline."""
    video_path = Path(video_path)
    print(f"\n{'='*60}")
    print(f"Processing: {video_path.name}")
    print(f"Camera: {camera}")

    stats = {"frames": 0, "faces": 0, "narrations": 0, "clips": 0, "skipped": 0}

    # Optionally import into Frigate recording structure
    if args.frigate_import:
        ok = import_to_frigate(video_path, camera)
        if ok:
            print(f"  ✓ Imported to Frigate recordings")
        else:
            print(f"  ✗ Frigate import failed")

    # Extract and process frames
    for frame_time, frame_bytes in extract_frames(video_path, args.interval, args.max_frames):
        fhash = frame_hash(str(video_path), frame_time)

        if is_processed(db, fhash) and not args.reprocess:
            stats["skipped"] += 1
            continue

        stats["frames"] += 1
        ts_str = f"{int(frame_time//60):02d}:{int(frame_time%60):02d}"
        faces = []
        narration = None
        objects = []

        # Face detection
        if not args.skip_faces:
            faces = detect_faces(frame_bytes)
            if faces:
                stats["faces"] += len(faces)
                face_names = [f"{f['name']}({f['similarity']:.0%})" for f in faces]
                print(f"  [{ts_str}] Faces: {', '.join(face_names)}")

        # Skip frames with no faces if --faces-only
        if args.faces_only and not faces:
            mark_processed(db, fhash, video_path, frame_time, camera)
            continue

        # LLaVA narration
        if args.narrate:
            narration = narrate_llava(frame_bytes, camera, [f["name"] for f in faces])
            if narration:
                stats["narrations"] += 1
                print(f"  [{ts_str}] LLaVA: {narration[:100]}...")

        # CLIP embedding
        if not args.skip_clip and HAS_PIL:
            metadata = {
                "camera": camera,
                "source": "import",
                "video": video_path.name,
                "frame_time": frame_time,
                "faces": [f["name"] for f in faces],
                "narration": narration or "",
                "imported_at": datetime.now().isoformat(),
            }
            if embed_clip(frame_bytes, metadata):
                stats["clips"] += 1

        mark_processed(db, fhash, video_path, frame_time, camera,
                       objects=objects, faces=faces, narration=narration,
                       clip_indexed=stats["clips"] > 0)

        # Progress
        if stats["frames"] % 10 == 0:
            print(f"  ... {stats['frames']} frames processed")

    return stats


def find_videos(path, recursive=False):
    """Find video files in a directory."""
    path = Path(path)
    if path.is_file():
        if path.suffix.lower() in VIDEO_EXTENSIONS:
            return [path]
        return []

    if recursive:
        return sorted(p for p in path.rglob("*") if p.suffix.lower() in VIDEO_EXTENSIONS)
    else:
        return sorted(p for p in path.iterdir() if p.suffix.lower() in VIDEO_EXTENSIONS)


def main():
    parser = argparse.ArgumentParser(
        description="Import historical video from Nest/Eufy into the AI pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s /mnt/eufy-exports/ --camera eufy_kitchen --recursive
  %(prog)s clip.mp4 --camera nest_entrance --narrate --interval 5
  %(prog)s /mnt/nfs/frigate/clips/ --camera reolink_86 --frigate-import
  %(prog)s video.mp4 --camera eufy_kitchen --faces-only --interval 1
        """
    )
    parser.add_argument("path", help="Video file or directory to process")
    parser.add_argument("--camera", required=True,
                        help="Camera name (must match Frigate config)")
    parser.add_argument("--interval", type=float, default=2.0,
                        help="Seconds between frame extractions (default: 2)")
    parser.add_argument("--max-frames", type=int, default=None,
                        help="Max frames to extract per video")
    parser.add_argument("--recursive", action="store_true",
                        help="Recursively search directories")
    parser.add_argument("--narrate", action="store_true",
                        help="Generate LLaVA narrations (requires Ollama)")
    parser.add_argument("--faces-only", action="store_true",
                        help="Only process frames containing faces")
    parser.add_argument("--skip-faces", action="store_true",
                        help="Skip face detection")
    parser.add_argument("--skip-clip", action="store_true",
                        help="Skip CLIP embedding")
    parser.add_argument("--frigate-import", action="store_true",
                        help="Also import video into Frigate recording structure")
    parser.add_argument("--reprocess", action="store_true",
                        help="Reprocess already-handled frames")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be processed without doing it")

    args = parser.parse_args()
    videos = find_videos(args.path, args.recursive)

    if not videos:
        print(f"No video files found at: {args.path}")
        sys.exit(1)

    print(f"Video Import Pipeline")
    print(f"{'='*60}")
    print(f"Videos found: {len(videos)}")
    print(f"Camera: {args.camera}")
    print(f"Frame interval: {args.interval}s")
    print(f"Face detection: {'skip' if args.skip_faces else 'enabled'}")
    print(f"CLIP embedding: {'skip' if args.skip_clip else 'enabled'}")
    print(f"LLaVA narration: {'enabled' if args.narrate else 'disabled'}")
    print(f"Frigate import: {'yes' if args.frigate_import else 'no'}")

    if args.dry_run:
        print(f"\n--- DRY RUN ---")
        for v in videos:
            size_mb = v.stat().st_size / (1024 * 1024)
            print(f"  {v.name} ({size_mb:.1f} MB)")
        print(f"\nTotal: {len(videos)} videos")
        return

    # Check dependencies
    if not args.skip_faces:
        try:
            r = requests.get(f"{COMPREFACE_URL}/api/v1/recognition/subjects",
                             headers={"x-api-key": COMPREFACE_KEY}, timeout=5)
            subjects = r.json().get("subjects", [])
            print(f"CompreFace subjects: {subjects}")
        except Exception as e:
            print(f"⚠ CompreFace unreachable: {e}")

    if args.narrate:
        try:
            r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
            models = [m["name"] for m in r.json().get("models", [])]
            if LLAVA_MODEL not in models:
                print(f"⚠ Model {LLAVA_MODEL} not found. Available: {models}")
            else:
                print(f"Ollama: {LLAVA_MODEL} ready")
        except Exception as e:
            print(f"⚠ Ollama unreachable: {e} — narration will be skipped")
            args.narrate = False

    db = init_db()

    total_stats = {"frames": 0, "faces": 0, "narrations": 0, "clips": 0, "skipped": 0}
    start = time.time()

    for video in videos:
        stats = process_video(video, args.camera, args, db)
        for k in total_stats:
            total_stats[k] += stats[k]

    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"Import Complete!")
    print(f"  Videos: {len(videos)}")
    print(f"  Frames processed: {total_stats['frames']} (skipped: {total_stats['skipped']})")
    print(f"  Faces detected: {total_stats['faces']}")
    print(f"  CLIP embeddings: {total_stats['clips']}")
    print(f"  Narrations: {total_stats['narrations']}")
    print(f"  Time: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
