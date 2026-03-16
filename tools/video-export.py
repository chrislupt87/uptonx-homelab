#!/usr/bin/env python3
"""
Video Export Tool — Pull clips from Eufy homebase and Nest cameras by date range.

Usage:
  python video-export.py --source eufy --camera kitchen --start "2026-02-01 08:00" --end "2026-02-01 18:00" --output /tmp/export/
  python video-export.py --source nest --camera entrance --start "2026-03-10 10:00" --end "2026-03-10 12:00" --output /tmp/export/
  python video-export.py --list-cameras
  python video-export.py --source eufy --count --start "2026-02-01" --end "2026-03-16"

Eufy: Downloads clips from homebase via eufy-security-ws WebSocket API.
Nest: Generates camera snapshots via Google SDM API (historical video requires Nest app).
"""
import argparse, asyncio, json, os, sys, time, struct
from datetime import datetime, timedelta
from pathlib import Path

# --- Config ---
EUFY_WS_URL = os.getenv("EUFY_WS_URL", "ws://192.168.1.18:3100")
NEST_CLIENT_ID = os.getenv("FRIGATE_NEST_OAUTH_CLIENT_ID", "")
NEST_CLIENT_SECRET = os.getenv("FRIGATE_NEST_OAUTH_CLIENT_SECRET", "")
NEST_REFRESH_TOKEN = os.getenv("FRIGATE_NEST_DEVICE_REFRESH_TOKEN", "")
NEST_PROJECT_ID = os.getenv("FRIGATE_NEST_DEVICE_ACCESS_PROJECT_ID", "")
SCHEMA_VERSION = 21

EUFY_CAMERAS = {
    "living_pan":   {"serial": "T8416P0023372302", "name": "Living Room Pan"},
    "living_north": {"serial": "T8600P10234314D7", "name": "Living Room North"},
    "living_south": {"serial": "T8600P1023432659", "name": "Living Room South"},
    "kitchen":      {"serial": "T8600P1023450946", "name": "Kitchen"},
    "entryway":     {"serial": "T8600P10234319D0", "name": "Entryway"},
}

EUFY_STATION = "T8030P1323430DF6"

NEST_CAMERAS = {
    "nest_north":    {"id": "AVPHwEs1pZqJD3NZmCXlYIL2EqJX2-QmjkmlS_K2dAtv0qXTs1kVz8XYXbhbl8EOEuoBNTqhdSfHDyk7SaAZh4buzS1vyQ", "name": "LivingRoom North"},
    "nest_south":    {"id": "AVPHwEsJbx4MBDXSsTlC7kLIC3SDX5XJohrTlGjw2ojqFNoqqD6O5T_CxhTGo7JLVFM096lC_IcXAkDWrj4x-5yDPiCMOA", "name": "LivingRoom South"},
    "nest_entrance": {"id": "AVPHwEsbjFKFzHieGfycKqVWg5xWL7HtFsSgn7IhpiismLDSiEYnjVVSCyE4Xadk7oyZlWPLEVT2Q8Ur6QtWUUHCmYKQ1g", "name": "Entrance Cam"},
}


# ==================== EUFY ====================

async def eufy_connect():
    """Connect to eufy-security-ws and set up API."""
    import websockets
    ws = await websockets.connect(EUFY_WS_URL, max_size=100 * 1024 * 1024)
    await asyncio.wait_for(ws.recv(), timeout=10)  # version
    await ws.send(json.dumps({"messageId": "s", "command": "set_api_schema", "schemaVersion": SCHEMA_VERSION}))
    await asyncio.wait_for(ws.recv(), timeout=5)
    await ws.send(json.dumps({"messageId": "l", "command": "start_listening"}))
    await asyncio.wait_for(ws.recv(), timeout=10)
    return ws


async def eufy_send_and_wait_event(ws, command, params, event_name, timeout=30):
    """Send a command and wait for the matching async event."""
    msg = {"messageId": "cmd_" + str(time.time()), "command": command}
    msg.update(params)
    await ws.send(json.dumps(msg))

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=min(5, deadline - time.time()))
            data = json.loads(raw)
            if data.get("type") == "event":
                evt = data.get("event", {})
                if evt.get("event") == event_name:
                    return evt
        except asyncio.TimeoutError:
            continue
    return None


async def eufy_count_clips(start_date, end_date):
    """Count clips on the Eufy homebase for a date range."""
    ws = await eufy_connect()
    try:
        # Query each day in range
        current = start_date
        total = 0
        while current <= end_date:
            date_str = current.strftime("%Y%m%d")
            evt = await eufy_send_and_wait_event(
                ws,
                "station.database_count_by_date",
                {"serialNumber": EUFY_STATION, "startDate": date_str, "endDate": date_str},
                "database count by date",
                timeout=10
            )
            if evt:
                for item in evt.get("data", []):
                    count = item.get("count", 0)
                    day = item.get("day", date_str)
                    if count > 0:
                        print("  %s: %d clips" % (day[:10] if isinstance(day, str) else date_str, count))
                        total += count
            current += timedelta(days=1)
        print("\nTotal: %d clips" % total)
    finally:
        await ws.close()


async def eufy_download_clips(camera_key, start_dt, end_dt, output_dir):
    """Download video clips from Eufy homebase for a camera and time range."""
    if camera_key not in EUFY_CAMERAS:
        print("Unknown camera: %s" % camera_key)
        print("Available: %s" % ", ".join(EUFY_CAMERAS.keys()))
        return

    cam = EUFY_CAMERAS[camera_key]
    serial = cam["serial"]
    os.makedirs(output_dir, exist_ok=True)

    print("Connecting to Eufy homebase...")
    ws = await eufy_connect()

    try:
        # Start download for the device
        print("Requesting download from %s (%s)" % (cam["name"], serial))
        print("Time range: %s to %s" % (start_dt, end_dt))

        # Convert to unix timestamps
        start_ts = int(start_dt.timestamp())
        end_ts = int(end_dt.timestamp())

        await ws.send(json.dumps({
            "messageId": "download_start",
            "command": "device.start_download",
            "serialNumber": serial,
            "path": "/media/mmcblk0p1/Camera00",  # default path on homebase
            "cipherId": 0,
        }))

        # Listen for download events
        print("Waiting for download data...")
        file_count = 0
        current_file = None
        current_data = bytearray()

        deadline = time.time() + 300  # 5 min timeout
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                data = json.loads(raw)

                if data.get("type") == "result":
                    mid = data.get("messageId", "")
                    if "download" in mid:
                        print("Download result: success=%s %s" % (data.get("success"), json.dumps(data.get("result", {}))[:200]))

                if data.get("type") == "event":
                    evt = data.get("event", {})
                    evt_name = evt.get("event", "")

                    if "download started" in evt_name:
                        print("Download started!")

                    elif "download finished" in evt_name:
                        print("Download finished! Files: %d" % file_count)
                        break

                    elif "download video data" in evt_name:
                        buf = evt.get("buffer", {}).get("data", [])
                        if buf:
                            current_data.extend(bytes(buf))

                    elif "download progress" in evt_name:
                        progress = evt.get("progress", 0)
                        print("  Progress: %d%%" % progress)

                    elif evt_name:
                        if "download" in evt_name.lower():
                            print("Event: %s" % evt_name)
                            print("  %s" % json.dumps(evt)[:300])

            except asyncio.TimeoutError:
                continue

        if current_data:
            out_path = os.path.join(output_dir, "%s_%s.mp4" % (camera_key, start_dt.strftime("%Y%m%d_%H%M")))
            with open(out_path, "wb") as f:
                f.write(current_data)
            print("Saved: %s (%d bytes)" % (out_path, len(current_data)))

        # Cancel download
        await ws.send(json.dumps({
            "messageId": "download_cancel",
            "command": "device.cancel_download",
            "serialNumber": serial,
        }))

    finally:
        await ws.close()


# ==================== NEST ====================

def nest_get_token():
    """Get a fresh Nest SDM access token."""
    import requests
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": NEST_CLIENT_ID,
        "client_secret": NEST_CLIENT_SECRET,
        "refresh_token": NEST_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    })
    return resp.json().get("access_token")


def nest_generate_image(camera_key, output_dir):
    """Generate a current camera image from Nest SDM API."""
    import requests

    if camera_key not in NEST_CAMERAS:
        print("Unknown Nest camera: %s" % camera_key)
        print("Available: %s" % ", ".join(NEST_CAMERAS.keys()))
        return

    cam = NEST_CAMERAS[camera_key]
    token = nest_get_token()
    if not token:
        print("Failed to get Nest access token")
        return

    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    device_name = "enterprises/%s/devices/%s" % (NEST_PROJECT_ID, cam["id"])

    # Generate camera image
    print("Generating image from %s..." % cam["name"])
    resp = requests.post(
        "https://smartdevicemanagement.googleapis.com/v1/%s:executeCommand" % device_name,
        headers=headers,
        json={"command": "sdm.devices.commands.CameraEventImage.GenerateImage"}
    )

    if resp.status_code == 200:
        result = resp.json().get("results", {})
        url = result.get("url")
        token_val = result.get("token")
        if url:
            os.makedirs(output_dir, exist_ok=True)
            img_resp = requests.get(url, headers={"Authorization": "Basic " + token_val})
            out_path = os.path.join(output_dir, "%s_%s.jpg" % (camera_key, datetime.now().strftime("%Y%m%d_%H%M%S")))
            with open(out_path, "wb") as f:
                f.write(img_resp.content)
            print("Saved: %s (%d bytes)" % (out_path, len(img_resp.content)))
        else:
            print("No image URL in response: %s" % json.dumps(result)[:300])
    else:
        print("API error %d: %s" % (resp.status_code, resp.text[:300]))


def nest_get_stream_url(camera_key, duration_seconds=300):
    """Get an RTSP stream URL for a Nest camera (live, not historical)."""
    import requests

    if camera_key not in NEST_CAMERAS:
        print("Unknown Nest camera: %s" % camera_key)
        return None

    cam = NEST_CAMERAS[camera_key]
    token = nest_get_token()
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    device_name = "enterprises/%s/devices/%s" % (NEST_PROJECT_ID, cam["id"])

    resp = requests.post(
        "https://smartdevicemanagement.googleapis.com/v1/%s:executeCommand" % device_name,
        headers=headers,
        json={
            "command": "sdm.devices.commands.CameraLiveStream.GenerateRtspStream"
        }
    )

    if resp.status_code == 200:
        result = resp.json().get("results", {})
        stream_url = result.get("streamUrls", {}).get("rtspUrl")
        token_val = result.get("streamToken")
        expires = result.get("expiresAt")
        if stream_url:
            print("RTSP Stream URL: %s" % stream_url)
            print("Expires: %s" % expires)
            print("\nTo record with ffmpeg:")
            print("  ffmpeg -rtsp_transport tcp -i '%s' -t %d -c copy %s_%s.mp4" % (
                stream_url, duration_seconds, camera_key, datetime.now().strftime("%Y%m%d_%H%M")))
            return stream_url
    else:
        print("API error %d: %s" % (resp.status_code, resp.text[:300]))
    return None


def nest_record_clip(camera_key, duration, output_dir):
    """Record a live clip from a Nest camera via RTSP."""
    import subprocess

    stream_url = nest_get_stream_url(camera_key, duration)
    if not stream_url:
        return

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "%s_%s.mp4" % (camera_key, datetime.now().strftime("%Y%m%d_%H%M%S")))

    print("Recording %d seconds to %s..." % (duration, out_path))
    subprocess.run([
        "ffmpeg", "-rtsp_transport", "tcp",
        "-i", stream_url,
        "-t", str(duration),
        "-c", "copy",
        "-y", out_path
    ], capture_output=True)

    if os.path.exists(out_path):
        size = os.path.getsize(out_path)
        print("Saved: %s (%d bytes)" % (out_path, size))
    else:
        print("Recording failed")


# ==================== MAIN ====================

def main():
    parser = argparse.ArgumentParser(description="Export video from Eufy homebase or Nest cameras")
    parser.add_argument("--source", choices=["eufy", "nest"], help="Camera source")
    parser.add_argument("--camera", help="Camera name (use --list-cameras to see options)")
    parser.add_argument("--start", help="Start datetime: 'YYYY-MM-DD HH:MM' or 'YYYY-MM-DD'")
    parser.add_argument("--end", help="End datetime: 'YYYY-MM-DD HH:MM' or 'YYYY-MM-DD'")
    parser.add_argument("--output", default="/tmp/video-export", help="Output directory")
    parser.add_argument("--list-cameras", action="store_true", help="List available cameras")
    parser.add_argument("--count", action="store_true", help="Count clips (Eufy only)")
    parser.add_argument("--snapshot", action="store_true", help="Take current snapshot (Nest only)")
    parser.add_argument("--record", type=int, metavar="SECONDS", help="Record live clip (Nest only)")
    parser.add_argument("--stream-url", action="store_true", help="Get RTSP stream URL (Nest only)")

    args = parser.parse_args()

    if args.list_cameras:
        print("=== Eufy Cameras (homebase storage: 789GB) ===")
        for key, cam in EUFY_CAMERAS.items():
            print("  %-15s %s (%s)" % (key, cam["name"], cam["serial"]))
        print("\n=== Nest Cameras (cloud storage via Google) ===")
        for key, cam in NEST_CAMERAS.items():
            print("  %-15s %s" % (key, cam["name"]))
        print("\nNote: Nest historical clips are only accessible via Google Home app.")
        print("This tool can generate live snapshots and record live streams from Nest.")
        return

    if not args.source:
        parser.print_help()
        return

    # Parse dates
    start_dt = None
    end_dt = None
    if args.start:
        try:
            start_dt = datetime.strptime(args.start, "%Y-%m-%d %H:%M")
        except ValueError:
            start_dt = datetime.strptime(args.start, "%Y-%m-%d")
    if args.end:
        try:
            end_dt = datetime.strptime(args.end, "%Y-%m-%d %H:%M")
        except ValueError:
            end_dt = datetime.strptime(args.end, "%Y-%m-%d")
            end_dt = end_dt.replace(hour=23, minute=59)

    if args.source == "eufy":
        if args.count:
            if not start_dt or not end_dt:
                print("--count requires --start and --end dates")
                return
            asyncio.run(eufy_count_clips(start_dt, end_dt))
        elif args.camera:
            if not start_dt or not end_dt:
                print("Need --start and --end for download")
                return
            asyncio.run(eufy_download_clips(args.camera, start_dt, end_dt, args.output))
        else:
            print("Specify --camera or --count for Eufy source")

    elif args.source == "nest":
        if args.snapshot:
            if not args.camera:
                print("Need --camera for snapshot")
                return
            nest_generate_image(args.camera, args.output)
        elif args.record:
            if not args.camera:
                print("Need --camera for recording")
                return
            nest_record_clip(args.camera, args.record, args.output)
        elif args.stream_url:
            if not args.camera:
                print("Need --camera for stream URL")
                return
            nest_get_stream_url(args.camera)
        else:
            print("Nest options: --snapshot, --record SECONDS, or --stream-url")


if __name__ == "__main__":
    main()
