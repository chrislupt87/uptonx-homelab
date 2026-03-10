#!/usr/bin/env python3
"""
Nest/Frigate Video Exporter + Face Extractor

Usage:
  # Export a Frigate clip (camera + time range)
  python export.py clip nest_entrance "2026-03-10 14:00" "2026-03-10 14:30"

  # Export clips from a JSON manifest
  python export.py batch requests.json

  # Extract faces from an exported clip
  python export.py faces /path/to/clip.mp4

  # Export Nest event images for a time range (via SDM API)
  python export.py events nest_living_north "2026-03-10 12:00" "2026-03-10 18:00"

  # Start Google Takeout export for Nest camera data
  python export.py takeout

requests.json format:
[
  {"camera": "nest_entrance", "start": "2026-03-10 14:00", "end": "2026-03-10 14:30", "label": "incident_1"},
  {"camera": "nest_living_north", "start": "2026-03-10 15:00", "end": "2026-03-10 15:10", "label": "person_spotted"}
]
"""
import argparse
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

FRIGATE_URL = os.getenv("FRIGATE_URL", "http://192.168.1.18:5000")
COMPREFACE_URL = os.getenv("COMPREFACE_URL", "http://192.168.1.69:8000")
COMPREFACE_API_KEY = os.getenv("COMPREFACE_API_KEY", "81491332-1960-4d3c-9c8e-a3be14b4e853")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", os.path.expanduser("~/video-exports"))

# Nest SDM API credentials
NEST_CLIENT_ID = os.getenv("NEST_CLIENT_ID", "")
NEST_CLIENT_SECRET = os.getenv("NEST_CLIENT_SECRET", "")
NEST_REFRESH_TOKEN = os.getenv("NEST_REFRESH_TOKEN", "")
NEST_PROJECT_ID = os.getenv("NEST_PROJECT_ID", "")

NEST_CAMERAS = {
    "nest_living_north": "AVPHwEs1pZqJD3NZmCXlYIL2EqJX2-QmjkmlS_K2dAtv0qXTs1kVz8XYXbhbl8EOEuoBNTqhdSfHDyk7SaAZh4buzS1vyQ",
    "nest_living_south": "AVPHwEsJbx4MBDXSsTlC7kLIC3SDX5XJohrTlGjw2ojqFNoqqD6O5T_CxhTGo7JLVFM096lC_IcXAkDWrj4x-5yDPiCMOA",
    "nest_entrance": "AVPHwEsbjFKFzHieGfycKqVWg5xWL7HtFsSgn7IhpiismLDSiEYnjVVSCyE4Xadk7oyZlWPLEVT2Q8Ur6QtWUUHCmYKQ1g",
}

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE


def parse_time(s):
    """Parse datetime string to unix timestamp."""
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"]:
        try:
            return int(datetime.strptime(s, fmt).timestamp())
        except ValueError:
            continue
    raise ValueError(f"Cannot parse time: {s}")


def ensure_dir(path):
    Path(path).mkdir(parents=True, exist_ok=True)


def get_nest_access_token():
    """Get a fresh access token using the refresh token."""
    data = urllib.parse.urlencode({
        "client_id": NEST_CLIENT_ID,
        "client_secret": NEST_CLIENT_SECRET,
        "refresh_token": NEST_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())["access_token"]


# --- Frigate Clip Export ---

def export_frigate_clip(camera, start, end, label=None):
    """Export a video clip from Frigate recordings."""
    start_ts = parse_time(start)
    end_ts = parse_time(end)
    label = label or f"{camera}_{start.replace(' ', '_').replace(':', '')}"

    ensure_dir(OUTPUT_DIR)
    out_path = os.path.join(OUTPUT_DIR, f"{label}.mp4")

    print(f"  Exporting {camera}: {start} -> {end}")

    # Use Frigate's export API
    url = f"{FRIGATE_URL}/api/export/{camera}/start/{start_ts}/end/{end_ts}"
    data = json.dumps({"playback": "realtime"}).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
            if result.get("success"):
                print(f"  Export queued: {result}")
                # Frigate exports are saved internally; also download via recording segments
                download_frigate_segments(camera, start_ts, end_ts, out_path)
            else:
                print(f"  Export failed: {result.get('message', 'unknown error')}")
                # Try direct segment download
                download_frigate_segments(camera, start_ts, end_ts, out_path)
    except Exception as e:
        print(f"  API export failed: {e}, trying direct segment download...")
        download_frigate_segments(camera, start_ts, end_ts, out_path)

    return out_path


def download_frigate_segments(camera, start_ts, end_ts, out_path):
    """Download recording segments from Frigate and concatenate with ffmpeg."""
    # Get recording segments
    url = f"{FRIGATE_URL}/api/{camera}/recordings?after={start_ts}&before={end_ts}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            segments = json.loads(resp.read())
    except Exception as e:
        print(f"  No recordings found: {e}")
        return False

    if not segments:
        print(f"  No recording segments found for time range")
        return False

    print(f"  Found {len(segments)} recording segments")

    # Download each segment and concatenate
    temp_dir = os.path.join(OUTPUT_DIR, ".tmp")
    ensure_dir(temp_dir)

    seg_files = []
    for i, seg in enumerate(segments):
        seg_id = seg.get("id", i)
        seg_url = f"{FRIGATE_URL}/api/{camera}/start/{seg['start_time']}/end/{seg['end_time']}/clip.mp4"
        seg_path = os.path.join(temp_dir, f"seg_{i:04d}.mp4")
        try:
            req = urllib.request.Request(seg_url)
            with urllib.request.urlopen(req, timeout=60) as resp:
                with open(seg_path, "wb") as f:
                    f.write(resp.read())
            seg_files.append(seg_path)
        except Exception as e:
            print(f"  Segment {i} download failed: {e}")

    if not seg_files:
        print(f"  No segments downloaded")
        return False

    if len(seg_files) == 1:
        os.rename(seg_files[0], out_path)
    else:
        # Concatenate with ffmpeg
        concat_file = os.path.join(temp_dir, "concat.txt")
        with open(concat_file, "w") as f:
            for sf in seg_files:
                f.write(f"file '{sf}'\n")
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_file, "-c", "copy", out_path
        ], capture_output=True)
        # Cleanup
        for sf in seg_files:
            os.remove(sf)
        os.remove(concat_file)

    if os.path.exists(out_path):
        size_mb = os.path.getsize(out_path) / (1024 * 1024)
        print(f"  Saved: {out_path} ({size_mb:.1f} MB)")
        return True
    return False


# --- Nest Event Images ---

def export_nest_events(camera, start, end):
    """Download Nest camera event images for a time range via Frigate's event API."""
    start_ts = parse_time(start)
    end_ts = parse_time(end)

    ensure_dir(os.path.join(OUTPUT_DIR, "events"))
    print(f"  Fetching events for {camera}: {start} -> {end}")

    # Use Frigate's event API (Nest events are captured by Frigate)
    url = f"{FRIGATE_URL}/api/events?camera={camera}&after={start_ts}&before={end_ts}&has_snapshot=1&limit=500"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            events = json.loads(resp.read())
    except Exception as e:
        print(f"  Failed to fetch events: {e}")
        return []

    print(f"  Found {len(events)} events")

    downloaded = []
    for evt in events:
        evt_id = evt["id"]
        label = evt.get("label", "unknown")
        sub_label = evt.get("sub_label", "")
        ts = datetime.fromtimestamp(evt["start_time"]).strftime("%Y%m%d_%H%M%S")
        fname = f"{camera}_{ts}_{label}"
        if sub_label:
            fname += f"_{sub_label}"
        fname += ".jpg"

        snap_url = f"{FRIGATE_URL}/api/events/{evt_id}/snapshot.jpg"
        out_path = os.path.join(OUTPUT_DIR, "events", fname)
        try:
            req = urllib.request.Request(snap_url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                with open(out_path, "wb") as f:
                    f.write(resp.read())
            downloaded.append(out_path)
            print(f"    {fname} ({label}{' - ' + sub_label if sub_label else ''})")
        except Exception:
            pass

    print(f"  Downloaded {len(downloaded)} event snapshots")
    return downloaded


# --- Face Extraction ---

def extract_faces(video_path, interval=2):
    """Extract faces from a video clip using ffmpeg + CompreFace."""
    if not os.path.exists(video_path):
        print(f"  File not found: {video_path}")
        return []

    basename = Path(video_path).stem
    faces_dir = os.path.join(OUTPUT_DIR, "faces", basename)
    frames_dir = os.path.join(OUTPUT_DIR, "faces", basename, "frames")
    ensure_dir(frames_dir)

    print(f"  Extracting frames every {interval}s from {video_path}")

    # Extract frames with ffmpeg
    subprocess.run([
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"fps=1/{interval}",
        "-q:v", "2",
        os.path.join(frames_dir, "frame_%04d.jpg")
    ], capture_output=True)

    frames = sorted(Path(frames_dir).glob("*.jpg"))
    print(f"  Extracted {len(frames)} frames")

    if not frames:
        return []

    # Send each frame to CompreFace for face detection + recognition
    faces_found = []
    for frame in frames:
        try:
            with open(frame, "rb") as f:
                img_data = f.read()

            # CompreFace recognition API
            req = urllib.request.Request(
                f"{COMPREFACE_URL}/api/v1/recognition/recognize",
                data=img_data,
                headers={
                    "Content-Type": "application/octet-stream",
                    "x-api-key": COMPREFACE_API_KEY,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())

            for face in result.get("result", []):
                box = face.get("box", {})
                subjects = face.get("subjects", [])
                best_match = subjects[0] if subjects else {"subject": "unknown", "similarity": 0}

                # Crop face
                crop_face(str(frame), box, faces_dir, frame.stem, best_match["subject"])
                faces_found.append({
                    "frame": frame.name,
                    "subject": best_match["subject"],
                    "similarity": best_match.get("similarity", 0),
                    "box": box,
                })
                subj = best_match["subject"]
                sim = best_match.get("similarity", 0)
                print(f"    {frame.name}: {subj} ({sim:.2f})")

        except Exception as e:
            pass  # Frame with no faces or API error

    # Summary
    print(f"\n  Faces found: {len(faces_found)}")
    subjects = {}
    for f in faces_found:
        s = f["subject"]
        subjects[s] = subjects.get(s, 0) + 1
    for s, count in sorted(subjects.items(), key=lambda x: -x[1]):
        print(f"    {s}: {count} appearances")

    # Save results
    results_path = os.path.join(faces_dir, "results.json")
    with open(results_path, "w") as f:
        json.dump(faces_found, f, indent=2)
    print(f"  Results saved: {results_path}")

    return faces_found


def crop_face(img_path, box, out_dir, prefix, subject):
    """Crop a face from an image using ffmpeg."""
    x = box.get("x_min", 0)
    y = box.get("y_min", 0)
    w = box.get("x_max", 0) - x
    h = box.get("y_max", 0) - y
    if w <= 0 or h <= 0:
        return

    out_path = os.path.join(out_dir, f"{prefix}_{subject}.jpg")
    subprocess.run([
        "ffmpeg", "-y", "-i", img_path,
        "-vf", f"crop={w}:{h}:{x}:{y}",
        "-frames:v", "1",
        out_path
    ], capture_output=True)


# --- Google Takeout ---

def initiate_takeout():
    """Print instructions for Google Takeout export of Nest camera data."""
    print("""
=== Google Takeout — Export Historical Nest Camera Footage ===

The Google SDM API does NOT support downloading historical video recordings.
For footage from BEFORE Frigate integration, use Google Takeout:

1. Go to: https://takeout.google.com
2. Click "Deselect all"
3. Scroll down and select "Nest" (or "Google Nest")
   - Choose specific cameras if available
   - Select date range if available
4. Click "Next step"
5. Choose delivery method (email link, Drive, etc.)
6. Click "Create export"

The export may take hours to days depending on the amount of footage.
Once downloaded, extract the videos and use this tool to process them:

  python export.py faces /path/to/downloaded/video.mp4

This will extract faces from the video for identification.
""")


# --- Batch Processing ---

def process_batch(manifest_path):
    """Process a batch of export requests from a JSON file."""
    with open(manifest_path) as f:
        requests = json.load(f)

    print(f"Processing {len(requests)} export requests\n")
    ensure_dir(OUTPUT_DIR)

    results = []
    for i, req in enumerate(requests, 1):
        camera = req["camera"]
        start = req["start"]
        end = req["end"]
        label = req.get("label", f"clip_{i:03d}")

        print(f"[{i}/{len(requests)}] {label}")

        # Export clip
        clip_path = export_frigate_clip(camera, start, end, label)

        # Export event snapshots
        events = export_nest_events(camera, start, end)

        # Extract faces if clip exists
        faces = []
        if os.path.exists(clip_path):
            faces = extract_faces(clip_path)

        results.append({
            "label": label,
            "camera": camera,
            "start": start,
            "end": end,
            "clip": clip_path if os.path.exists(clip_path) else None,
            "events": len(events),
            "faces": len(faces),
        })
        print()

    # Save summary
    summary_path = os.path.join(OUTPUT_DIR, "export_summary.json")
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSummary saved: {summary_path}")

    # Print summary table
    print(f"\n{'Label':<25} {'Camera':<22} {'Clip':<8} {'Events':<8} {'Faces':<8}")
    print("-" * 71)
    for r in results:
        clip_status = "Yes" if r["clip"] else "No"
        print(f"{r['label']:<25} {r['camera']:<22} {clip_status:<8} {r['events']:<8} {r['faces']:<8}")


# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="Nest/Frigate Video Exporter + Face Extractor")
    sub = parser.add_subparsers(dest="command")

    # clip command
    p_clip = sub.add_parser("clip", help="Export a Frigate recording clip")
    p_clip.add_argument("camera", help="Camera name (e.g. nest_entrance)")
    p_clip.add_argument("start", help="Start time (YYYY-MM-DD HH:MM)")
    p_clip.add_argument("end", help="End time (YYYY-MM-DD HH:MM)")
    p_clip.add_argument("--label", help="Output filename label")

    # batch command
    p_batch = sub.add_parser("batch", help="Process batch export from JSON manifest")
    p_batch.add_argument("manifest", help="Path to JSON manifest file")

    # faces command
    p_faces = sub.add_parser("faces", help="Extract faces from a video file")
    p_faces.add_argument("video", help="Path to video file")
    p_faces.add_argument("--interval", type=int, default=2, help="Frame extraction interval in seconds")

    # events command
    p_events = sub.add_parser("events", help="Export Nest camera event images")
    p_events.add_argument("camera", help="Camera name")
    p_events.add_argument("start", help="Start time")
    p_events.add_argument("end", help="End time")

    # takeout command
    sub.add_parser("takeout", help="Google Takeout instructions for historical footage")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    ensure_dir(OUTPUT_DIR)

    if args.command == "clip":
        export_frigate_clip(args.camera, args.start, args.end, args.label)
    elif args.command == "batch":
        process_batch(args.manifest)
    elif args.command == "faces":
        extract_faces(args.video, args.interval)
    elif args.command == "events":
        export_nest_events(args.camera, args.start, args.end)
    elif args.command == "takeout":
        initiate_takeout()


if __name__ == "__main__":
    main()
