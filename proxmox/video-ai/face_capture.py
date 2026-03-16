#!/usr/bin/env python3
"""
Face Capture — collect high-quality face crops from Frigate events.
Run this temporarily to gather good reference images for CompreFace training.

Listens to MQTT, grabs snapshots, uses CompreFace detection to crop faces,
filters for quality (size, sharpness), and saves the best ones.

Usage:
    python face_capture.py          # collect until 10 good crops
    python face_capture.py --count 20  # collect 20
    python face_capture.py --list   # show what's been collected
    python face_capture.py --train chris  # train all collected into CompreFace as "chris"
"""
import os, sys, json, time, argparse, hashlib
from datetime import datetime
from pathlib import Path

import requests
import paho.mqtt.client as mqtt
from PIL import Image
from io import BytesIO

MQTT_HOST      = os.getenv("MQTT_HOST", "192.168.1.18")
FRIGATE_URL    = os.getenv("FRIGATE_URL", "http://192.168.1.18:5000")
COMPREFACE_URL = os.getenv("COMPREFACE_URL", "http://compreface:80")
COMPREFACE_KEY = os.getenv("COMPREFACE_API_KEY", "")
OUTPUT_DIR     = Path(os.getenv("OUTPUT_DIR", "/data/face-capture"))

# Quality thresholds
MIN_FACE_WIDTH  = 80    # pixels — reject tiny faces
MIN_FACE_HEIGHT = 80
MIN_SHARPNESS   = 30.0  # Laplacian variance — reject blurry
MAX_COLLECT     = 10

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def detect_faces(image_bytes):
    """Use CompreFace detection API to find faces and get bounding boxes."""
    try:
        resp = requests.post(
            f"{COMPREFACE_URL}/api/v1/detection/detect",
            headers={"x-api-key": COMPREFACE_KEY},
            files={"file": ("snap.jpg", image_bytes, "image/jpeg")},
            params={"limit": 5, "det_prob_threshold": 0.5},
            timeout=15,
        )
        if resp.status_code != 200:
            # Try recognition endpoint's detect if detection service isn't set up
            resp = requests.post(
                f"{COMPREFACE_URL}/api/v1/recognition/faces",
                headers={"x-api-key": COMPREFACE_KEY},
                files={"file": ("snap.jpg", image_bytes, "image/jpeg")},
                timeout=15,
            )
        data = resp.json()
        return data.get("result", [])
    except Exception as e:
        print(f"  Detection error: {e}")
        return []


def compute_sharpness(pil_image):
    """Laplacian variance as a sharpness metric. Higher = sharper."""
    import numpy as np
    gray = pil_image.convert("L")
    arr = np.array(gray, dtype=np.float64)
    # Laplacian kernel
    laplacian = (
        arr[:-2, 1:-1] + arr[2:, 1:-1] + arr[1:-1, :-2] + arr[1:-1, 2:]
        - 4 * arr[1:-1, 1:-1]
    )
    return float(laplacian.var())


def crop_face(image_bytes, box):
    """Crop face from image with padding."""
    img = Image.open(BytesIO(image_bytes))
    w, h = img.size
    x_min = max(0, box["x_min"] - 20)
    y_min = max(0, box["y_min"] - 30)  # more padding above for forehead
    x_max = min(w, box["x_max"] + 20)
    y_max = min(h, box["y_max"] + 20)
    crop = img.crop((x_min, y_min, x_max, y_max))
    return crop


def evaluate_crop(crop):
    """Return (pass, reason) based on quality checks."""
    cw, ch = crop.size
    if cw < MIN_FACE_WIDTH or ch < MIN_FACE_HEIGHT:
        return False, f"too small ({cw}x{ch})"
    sharpness = compute_sharpness(crop)
    if sharpness < MIN_SHARPNESS:
        return False, f"too blurry (sharpness={sharpness:.1f})"
    return True, f"ok (size={cw}x{ch}, sharp={sharpness:.1f})"


def save_crop(crop, camera, event_id):
    """Save crop with metadata filename."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_id = event_id[:8] if event_id else "unknown"
    fname = OUTPUT_DIR / f"{ts}_{camera}_{short_id}.jpg"
    crop.save(fname, "JPEG", quality=95)
    return fname


def count_collected():
    return len(list(OUTPUT_DIR.glob("*.jpg")))


def process_event(event_id, camera):
    """Download snapshot, detect faces, crop, evaluate, save."""
    n = count_collected()
    if n >= MAX_COLLECT:
        return True  # done

    # Download snapshot
    try:
        r = requests.get(
            f"{FRIGATE_URL}/api/events/{event_id}/snapshot.jpg", timeout=10
        )
        if r.status_code != 200:
            print(f"  [{camera}] No snapshot for {event_id[:12]}")
            return False
    except Exception as e:
        print(f"  [{camera}] Snapshot fetch error: {e}")
        return False

    image_bytes = r.content

    # Detect faces
    results = detect_faces(image_bytes)
    if not results:
        print(f"  [{camera}] No faces detected in {event_id[:12]}")
        return False

    saved = 0
    for face in results:
        box = face.get("box", {})
        if not box:
            continue
        prob = face.get("face", {}).get("prob", face.get("probability", 0))

        crop = crop_face(image_bytes, box)
        passed, reason = evaluate_crop(crop)

        if passed:
            fname = save_crop(crop, camera, event_id)
            saved += 1
            n = count_collected()
            print(f"  ✓ [{n}/{MAX_COLLECT}] Saved {fname.name} — {reason} (det={prob:.0%})")
        else:
            print(f"  ✗ [{camera}] Rejected — {reason}")

    return count_collected() >= MAX_COLLECT


def on_connect(client, userdata, flags, rc):
    print(f"Connected to MQTT (rc={rc})")
    client.subscribe("frigate/events")
    n = count_collected()
    print(f"Collecting face crops... {n}/{MAX_COLLECT} so far")
    print("Walk past your cameras! Good faces will be saved automatically.\n")


def on_message(client, userdata, msg):
    try:
        p = json.loads(msg.payload)
        # Process on both "new" and "end" events for more chances
        if p.get("type") in ("new", "end"):
            after = p.get("after", {})
            if after.get("label") != "person":
                return
            event_id = after["id"]
            camera = after.get("camera", "?")

            # Deduplicate — don't re-process same event
            marker = OUTPUT_DIR / f".processed_{event_id[:16]}"
            if marker.exists():
                return
            marker.touch()

            done = process_event(event_id, camera)
            if done:
                print(f"\n✓ Collected {MAX_COLLECT} face crops! Stopping.")
                print(f"Review them in: {OUTPUT_DIR}")
                print("Then run: python face_capture.py --train chris")
                client.disconnect()
    except Exception as e:
        print(f"MQTT error: {e}")


def cmd_list():
    """List collected crops."""
    crops = sorted(OUTPUT_DIR.glob("*.jpg"))
    if not crops:
        print("No crops collected yet.")
        return
    print(f"\nCollected {len(crops)} face crops in {OUTPUT_DIR}:\n")
    for c in crops:
        sz = c.stat().st_size // 1024
        img = Image.open(c)
        print(f"  {c.name}  ({img.size[0]}x{img.size[1]}, {sz}KB)")
    print(f"\nTo train: python face_capture.py --train <name>")


def cmd_train(name):
    """Train all collected crops into CompreFace as the given subject."""
    if not COMPREFACE_KEY:
        print("ERROR: COMPREFACE_API_KEY not set")
        sys.exit(1)

    crops = sorted(OUTPUT_DIR.glob("*.jpg"))
    if not crops:
        print("No crops to train. Run capture first.")
        sys.exit(1)

    print(f"\nTraining {len(crops)} face crops as '{name}'...\n")
    success = 0
    for c in crops:
        img_bytes = c.read_bytes()
        try:
            resp = requests.post(
                f"{COMPREFACE_URL}/api/v1/recognition/faces",
                headers={"x-api-key": COMPREFACE_KEY},
                data={"subject": name},
                files={"file": ("face.jpg", img_bytes, "image/jpeg")},
                timeout=15,
            )
            if resp.status_code == 201:
                success += 1
                print(f"  ✓ {c.name}")
            else:
                print(f"  ✗ {c.name} — HTTP {resp.status_code}: {resp.text[:100]}")
        except Exception as e:
            print(f"  ✗ {c.name} — {e}")

    print(f"\nDone! Trained {success}/{len(crops)} images as '{name}'")

    # Verify
    try:
        resp = requests.get(
            f"{COMPREFACE_URL}/api/v1/recognition/subjects",
            headers={"x-api-key": COMPREFACE_KEY},
            timeout=10,
        )
        subjects = resp.json().get("subjects", [])
        print(f"CompreFace subjects: {subjects}")
    except:
        pass


def main():
    parser = argparse.ArgumentParser(description="Face Capture for CompreFace training")
    parser.add_argument("--count", type=int, default=10, help="Number of crops to collect")
    parser.add_argument("--list", action="store_true", help="List collected crops")
    parser.add_argument("--train", type=str, help="Train collected crops as this subject name")
    args = parser.parse_args()

    global MAX_COLLECT
    MAX_COLLECT = args.count

    if args.list:
        cmd_list()
        return

    if args.train:
        cmd_train(args.train)
        return

    # Install numpy if needed (for sharpness check)
    try:
        import numpy
    except ImportError:
        print("Installing numpy...")
        os.system("pip install -q numpy")

    print(f"Face Capture — collecting up to {MAX_COLLECT} high-quality face crops")
    print(f"Output: {OUTPUT_DIR}")
    print(f"Frigate: {FRIGATE_URL}")
    print(f"CompreFace: {COMPREFACE_URL}")
    print(f"Min face size: {MIN_FACE_WIDTH}x{MIN_FACE_HEIGHT}px")
    print(f"Min sharpness: {MIN_SHARPNESS}\n")

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, 1883, 60)
    client.loop_forever()


if __name__ == "__main__":
    main()
