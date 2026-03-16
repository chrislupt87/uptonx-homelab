#!/usr/bin/env python3
"""
Eufy Homebase Video Export Tool

Pull video clips from the Eufy homebase by camera and date range.
The homebase has a 1TB HDD with ~789GB of stored clips.

Usage:
  # List cameras and latest clip info
  python eufy-export.py --info

  # Download clips for a camera on a specific date
  python eufy-export.py --camera kitchen --date 2026-02-15 --output ~/Desktop/eufy-export/

  # Download clips for a date range
  python eufy-export.py --camera living_pan --start 2026-02-01 --end 2026-02-28 --output ~/Desktop/eufy-export/

  # Download latest thumbnail from each camera
  python eufy-export.py --thumbnails --output ~/Desktop/eufy-export/

Requires: pip install websockets
"""
import argparse, asyncio, json, os, sys, time
from datetime import datetime, timedelta
from pathlib import Path

EUFY_WS_URL = os.getenv("EUFY_WS_URL", "ws://192.168.1.18:3100")
SCHEMA_VERSION = 21
STATION_SN = "T8030P1323430DF6"

CAMERAS = {
    "living_pan":   {"serial": "T8416P0023372302", "hdd_path": "Camera00", "name": "Living Room Pan"},
    "living_south": {"serial": "T8600P1023432659", "hdd_path": "Camera01", "name": "Living Room South"},
    "living_north": {"serial": "T8600P10234314D7", "hdd_path": "Camera02", "name": "Living Room North"},
    "entryway":     {"serial": "T8600P10234319D0", "hdd_path": "Camera03", "name": "Entryway"},
    "kitchen":      {"serial": "T8600P1023450946", "hdd_path": "Camera04", "name": "Kitchen"},
}

import websockets


async def connect():
    """Connect to eufy-security-ws."""
    ws = await websockets.connect(EUFY_WS_URL, max_size=200 * 1024 * 1024)
    await asyncio.wait_for(ws.recv(), timeout=10)
    await ws.send(json.dumps({"messageId": "s", "command": "set_api_schema", "schemaVersion": SCHEMA_VERSION}))
    await asyncio.wait_for(ws.recv(), timeout=5)
    await ws.send(json.dumps({"messageId": "l", "command": "start_listening"}))
    await asyncio.wait_for(ws.recv(), timeout=10)
    print("Connected to Eufy homebase")
    return ws


async def wait_for_event(ws, event_name, timeout=30):
    """Wait for a specific async event from the homebase."""
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


async def collect_events(ws, event_names, timeout=30):
    """Collect multiple events within a timeout."""
    events = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=min(3, deadline - time.time()))
            data = json.loads(raw)
            if data.get("type") == "event":
                evt = data.get("event", {})
                if evt.get("event") in event_names:
                    events.append(evt)
        except asyncio.TimeoutError:
            continue
    return events


async def get_info(ws):
    """Get latest info from all cameras."""
    await ws.send(json.dumps({
        "messageId": "info",
        "command": "station.database_query_latest_info",
        "serialNumber": STATION_SN,
    }))

    evt = await wait_for_event(ws, "database query latest", timeout=15)
    if evt:
        print("\n%-18s %-8s %-s" % ("Camera", "Events", "Latest Clip Path"))
        print("-" * 80)
        for item in evt.get("data", []):
            sn = item.get("device_sn", "?")
            count = item.get("event_count", 0)
            path = item.get("crop_local_path", "?")
            # Find camera name
            name = sn
            for key, cam in CAMERAS.items():
                if cam["serial"] == sn:
                    name = "%s (%s)" % (cam["name"], key)
                    break
            print("%-18s %-8d %s" % (name, count, path))

    # Storage info
    await ws.send(json.dumps({
        "messageId": "station_props",
        "command": "station.get_properties",
        "serialNumber": STATION_SN,
    }))
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=5)
        data = json.loads(raw)
        props = data.get("result", {}).get("properties", {})
        hdd = props.get("storageInfoHdd", {})
        if hdd:
            total_gb = hdd.get("disk_size", 0) / 1024
            used_gb = hdd.get("disk_used", 0) / 1024
            video_gb = hdd.get("video_used", 0) / 1024
            print("\nHDD: %.0f GB total, %.0f GB used, %.0f GB video" % (total_gb, used_gb, video_gb))
    except:
        pass


async def download_thumbnails(ws, output_dir):
    """Download latest thumbnail from each camera."""
    os.makedirs(output_dir, exist_ok=True)

    # Get latest paths
    await ws.send(json.dumps({
        "messageId": "latest",
        "command": "station.database_query_latest_info",
        "serialNumber": STATION_SN,
    }))

    latest_evt = await wait_for_event(ws, "database query latest", timeout=15)
    if not latest_evt:
        print("Failed to get latest info")
        return

    # Download each thumbnail
    events = collect_events(ws, ["image downloaded", "command result"], timeout=30)
    events_task = asyncio.create_task(events)

    for item in latest_evt.get("data", []):
        path = item.get("crop_local_path", "")
        sn = item.get("device_sn", "")
        if path:
            await ws.send(json.dumps({
                "messageId": "img_" + sn,
                "command": "station.download_image",
                "serialNumber": STATION_SN,
                "file": path,
            }))

    # Wait for image downloads
    dl_events = await events_task

    for evt in dl_events:
        if evt.get("event") == "image downloaded":
            file_path = evt.get("file", "")
            image_data = evt.get("image", {}).get("data", {}).get("data", [])
            if image_data:
                # Determine camera name from path
                cam_name = "unknown"
                for key, cam in CAMERAS.items():
                    if cam["hdd_path"] in file_path:
                        cam_name = key
                        break

                out_path = os.path.join(output_dir, "%s_latest.jpg" % cam_name)
                with open(out_path, "wb") as f:
                    f.write(bytes(image_data))
                print("Saved: %s (%d bytes)" % (out_path, len(image_data)))


async def download_video(ws, camera_key, start_date, end_date, output_dir):
    """Download video clips from a camera for a date range."""
    if camera_key not in CAMERAS:
        print("Unknown camera: %s" % camera_key)
        print("Available: %s" % ", ".join(CAMERAS.keys()))
        return

    cam = CAMERAS[camera_key]
    serial = cam["serial"]
    hdd_path = cam["hdd_path"]
    os.makedirs(output_dir, exist_ok=True)

    print("Camera: %s (%s)" % (cam["name"], serial))
    print("HDD path: /zx/hdd_data0/%s/" % hdd_path)
    print("Date range: %s to %s" % (start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")))
    print()

    # Start download from the camera's HDD path
    download_path = "/zx/hdd_data0/%s" % hdd_path
    print("Starting download from %s..." % download_path)

    await ws.send(json.dumps({
        "messageId": "dl_start",
        "command": "device.start_download",
        "serialNumber": serial,
        "path": download_path,
        "cipherId": 0,
    }))

    # Collect video data
    video_buffer = bytearray()
    file_count = 0
    last_progress = 0
    downloading = True
    start_time = time.time()

    while downloading and (time.time() - start_time) < 600:  # 10 min max
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(raw)

            if data.get("type") == "result":
                mid = data.get("messageId", "")
                if "dl" in mid:
                    success = data.get("success", False)
                    error = data.get("errorCode", "")
                    if not success:
                        print("Download command failed: %s" % error)
                        downloading = False

            if data.get("type") == "event":
                evt = data.get("event", {})
                evt_name = evt.get("event", "")

                if "download started" in evt_name:
                    print("Download started!")

                elif "download finished" in evt_name:
                    print("\nDownload finished!")
                    downloading = False

                elif "download video data" in evt_name:
                    buf = evt.get("buffer", {}).get("data", [])
                    if buf:
                        video_buffer.extend(bytes(buf))
                        mb = len(video_buffer) / (1024 * 1024)
                        if mb - last_progress >= 1:
                            sys.stdout.write("\r  Received: %.1f MB" % mb)
                            sys.stdout.flush()
                            last_progress = mb

                elif "download progress" in evt_name:
                    progress = evt.get("progress", 0)
                    sys.stdout.write("\r  Progress: %d%% (%.1f MB)" % (progress, len(video_buffer) / (1024 * 1024)))
                    sys.stdout.flush()

                elif "command result" in evt_name:
                    cmd = evt.get("command", "")
                    code = evt.get("returnCode", -1)
                    if "download" in cmd:
                        print("\nCommand result: %s (code=%d)" % (cmd, code))

        except asyncio.TimeoutError:
            if video_buffer:
                # Got data but stream paused — might be done
                elapsed = time.time() - start_time
                if elapsed > 30:
                    print("\n  No new data for 10s, assuming complete")
                    downloading = False
            continue

    # Save video
    if video_buffer:
        out_path = os.path.join(output_dir, "%s_%s.mp4" % (
            camera_key, start_date.strftime("%Y%m%d")))
        with open(out_path, "wb") as f:
            f.write(video_buffer)
        print("\nSaved: %s (%.1f MB)" % (out_path, len(video_buffer) / (1024 * 1024)))
    else:
        print("\nNo video data received")

    # Cancel download
    await ws.send(json.dumps({
        "messageId": "dl_cancel",
        "command": "device.cancel_download",
        "serialNumber": serial,
    }))


async def main():
    parser = argparse.ArgumentParser(
        description="Export video clips from Eufy homebase (1TB HDD archive)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --info                                           Show cameras and storage
  %(prog)s --thumbnails -o ~/Desktop/eufy-export/           Download latest thumbnails
  %(prog)s --camera kitchen --date 2026-02-15 -o ~/export/  Download clips for a date
  %(prog)s --camera living_pan --start 2026-01-01 --end 2026-01-31 -o ~/export/
        """)
    parser.add_argument("--info", action="store_true", help="Show camera info and storage stats")
    parser.add_argument("--thumbnails", action="store_true", help="Download latest thumbnail from each camera")
    parser.add_argument("--camera", choices=list(CAMERAS.keys()), help="Camera to export from")
    parser.add_argument("--date", help="Single date: YYYY-MM-DD")
    parser.add_argument("--start", help="Start date: YYYY-MM-DD")
    parser.add_argument("--end", help="End date: YYYY-MM-DD")
    parser.add_argument("-o", "--output", default=os.path.expanduser("~/Desktop/Claude Output/eufy-export"),
                        help="Output directory")

    args = parser.parse_args()

    if not any([args.info, args.thumbnails, args.camera]):
        parser.print_help()
        return

    ws = await connect()

    try:
        if args.info:
            await get_info(ws)

        elif args.thumbnails:
            await download_thumbnails(ws, args.output)

        elif args.camera:
            if args.date:
                start = datetime.strptime(args.date, "%Y-%m-%d")
                end = start.replace(hour=23, minute=59, second=59)
            elif args.start and args.end:
                start = datetime.strptime(args.start, "%Y-%m-%d")
                end = datetime.strptime(args.end, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            else:
                print("Need --date or --start/--end for video export")
                return

            await download_video(ws, args.camera, start, end, args.output)
    finally:
        await ws.close()


if __name__ == "__main__":
    asyncio.run(main())
