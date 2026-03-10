#!/usr/bin/env python3
"""
Eufy P2P → TCP bridge for go2rtc/Frigate (motion-triggered).

Connects to eufy-security-ws, listens for motion events,
and starts P2P livestream for the triggered camera.
Higher priority cameras preempt lower ones.

Each camera gets a video port (base_port + index*2) and audio port (base_port + index*2 + 1).
"""
import os
import sys
import json
import asyncio
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("eufy-bridge")

EUFY_WS_URL = os.getenv("EUFY_WS_URL", "ws://127.0.0.1:3100")
BASE_PORT = int(os.getenv("BASE_PORT", "63336"))
# Comma-separated serials in PRIORITY ORDER (highest first)
CAMERA_SERIALS = [s.strip() for s in os.getenv("CAMERA_SERIALS", "").split(",") if s.strip()]
# How long to keep streaming after last motion event (seconds)
STREAM_TIMEOUT = int(os.getenv("STREAM_TIMEOUT", "30"))
SCHEMA_VERSION = 21


class CameraBridge:
    def __init__(self, serial, name, priority, video_port, audio_port):
        self.serial = serial
        self.name = name
        self.priority = priority  # lower number = higher priority
        self.video_port = video_port
        self.audio_port = audio_port
        self.video_clients = []
        self.audio_clients = []
        self.streaming = False
        self.motion_active = False
        self.last_motion_time = 0
        self.stream_requested = False

    async def handle_video_client(self, reader, writer):
        addr = writer.get_extra_info("peername")
        log.info(f"[{self.name}] Video client connected from {addr}")
        self.video_clients.append(writer)
        try:
            while not reader.at_eof():
                await asyncio.sleep(1)
        except Exception:
            pass
        finally:
            if writer in self.video_clients:
                self.video_clients.remove(writer)
            try:
                writer.close()
            except Exception:
                pass
            log.info(f"[{self.name}] Video client disconnected")

    async def handle_audio_client(self, reader, writer):
        addr = writer.get_extra_info("peername")
        log.info(f"[{self.name}] Audio client connected from {addr}")
        self.audio_clients.append(writer)
        try:
            while not reader.at_eof():
                await asyncio.sleep(1)
        except Exception:
            pass
        finally:
            if writer in self.audio_clients:
                self.audio_clients.remove(writer)
            try:
                writer.close()
            except Exception:
                pass
            log.info(f"[{self.name}] Audio client disconnected")

    def send_video(self, data):
        for client in list(self.video_clients):
            try:
                client.write(data)
            except Exception:
                pass

    def send_audio(self, data):
        for client in list(self.audio_clients):
            try:
                client.write(data)
            except Exception:
                pass

    @property
    def wants_stream(self):
        """Camera wants a stream if motion is active or recently ended."""
        if self.motion_active:
            return True
        if self.last_motion_time > 0:
            elapsed = time.time() - self.last_motion_time
            return elapsed < STREAM_TIMEOUT
        return False


async def main():
    import websockets

    cameras = {}  # serial -> CameraBridge
    active_serial = None  # which camera is currently streaming

    while True:
        try:
            log.info(f"Connecting to eufy-security-ws at {EUFY_WS_URL}")
            async with websockets.connect(EUFY_WS_URL, max_size=10 * 1024 * 1024) as ws:
                # Get version
                version_msg = await asyncio.wait_for(ws.recv(), timeout=10)
                log.info(f"Connected: {version_msg[:200]}")

                # Set API schema
                await ws.send(json.dumps({
                    "messageId": "schema",
                    "command": "set_api_schema",
                    "schemaVersion": SCHEMA_VERSION,
                }))
                await asyncio.wait_for(ws.recv(), timeout=5)

                # Start listening
                await ws.send(json.dumps({
                    "messageId": "listen",
                    "command": "start_listening",
                }))
                state_resp = await asyncio.wait_for(ws.recv(), timeout=10)
                state = json.loads(state_resp)
                device_serials = state.get("result", {}).get("state", {}).get("devices", [])

                # Set up camera bridges in priority order
                for idx, serial in enumerate(CAMERA_SERIALS):
                    if serial not in device_serials:
                        log.warning(f"Camera {serial} not found, skipping")
                        continue

                    await ws.send(json.dumps({
                        "messageId": f"props_{serial}",
                        "command": "device.get_properties",
                        "serialNumber": serial,
                    }))
                    resp = await asyncio.wait_for(ws.recv(), timeout=5)
                    props = json.loads(resp).get("result", {}).get("properties", {})
                    name = props.get("name", serial)

                    vport = BASE_PORT + idx * 2
                    aport = BASE_PORT + idx * 2 + 1

                    cam = CameraBridge(serial, name, idx, vport, aport)
                    cameras[serial] = cam

                    # Start TCP servers
                    await asyncio.start_server(cam.handle_video_client, "0.0.0.0", vport)
                    await asyncio.start_server(cam.handle_audio_client, "0.0.0.0", aport)
                    log.info(f"[{name}] priority={idx} serial={serial} video=:{vport} audio=:{aport}")

                log.info(f"Listening for motion events on {len(cameras)} cameras...")
                log.info(f"Stream timeout: {STREAM_TIMEOUT}s after last motion")

                active_serial = None

                async def pick_best_camera():
                    """Find the highest priority camera that wants a stream."""
                    best = None
                    for serial, cam in cameras.items():
                        if cam.wants_stream:
                            if best is None or cam.priority < cameras[best].priority:
                                best = serial
                    return best

                async def switch_stream(ws, target_serial):
                    """Switch the active stream to the target camera."""
                    nonlocal active_serial

                    if active_serial == target_serial:
                        return

                    # Stop current stream
                    if active_serial and active_serial in cameras:
                        old_cam = cameras[active_serial]
                        if old_cam.streaming:
                            await ws.send(json.dumps({
                                "messageId": f"stop_{active_serial}",
                                "command": "device.stop_livestream",
                                "serialNumber": active_serial,
                            }))
                            log.info(f"[{old_cam.name}] Stopping stream")

                    # Start new stream
                    if target_serial and target_serial in cameras:
                        new_cam = cameras[target_serial]
                        await ws.send(json.dumps({
                            "messageId": f"start_{target_serial}",
                            "command": "device.start_livestream",
                            "serialNumber": target_serial,
                        }))
                        new_cam.stream_requested = True
                        log.info(f"[{new_cam.name}] Starting stream (priority={new_cam.priority})")

                    active_serial = target_serial

                # Main event loop
                last_check = time.time()
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5)
                        msg = json.loads(raw)

                        if msg.get("type") == "event":
                            evt = msg.get("event", {})
                            event_name = evt.get("event", "")
                            serial = evt.get("serialNumber", "")
                            cam = cameras.get(serial)

                            # Motion events
                            if event_name in ("motion detected", "person detected"):
                                if cam:
                                    was_active = cam.motion_active
                                    cam.motion_active = True
                                    cam.last_motion_time = time.time()
                                    if not was_active:
                                        log.info(f"[{cam.name}] Motion detected!")

                                    # Check if this camera should preempt the current stream
                                    best = await pick_best_camera()
                                    if best != active_serial:
                                        await switch_stream(ws, best)

                            elif event_name == "motion detection":
                                # This event has a "state" field
                                if cam:
                                    motion_state = evt.get("state", False)
                                    cam.motion_active = motion_state
                                    if motion_state:
                                        cam.last_motion_time = time.time()
                                        log.info(f"[{cam.name}] Motion started")
                                    else:
                                        cam.last_motion_time = time.time()
                                        log.info(f"[{cam.name}] Motion ended, keeping stream for {STREAM_TIMEOUT}s")

                            elif event_name == "person detected":
                                if cam:
                                    person_state = evt.get("state", False)
                                    if person_state:
                                        cam.motion_active = True
                                        cam.last_motion_time = time.time()
                                        log.info(f"[{cam.name}] Person detected!")
                                        best = await pick_best_camera()
                                        if best != active_serial:
                                            await switch_stream(ws, best)

                            # Livestream data
                            elif event_name == "livestream started":
                                if cam:
                                    cam.streaming = True
                                    log.info(f"[{cam.name}] Livestream active")

                            elif event_name == "livestream stopped":
                                if cam:
                                    cam.streaming = False
                                    cam.stream_requested = False
                                    if serial == active_serial:
                                        active_serial = None
                                    log.info(f"[{cam.name}] Livestream stopped")

                            elif event_name == "livestream video data":
                                if cam:
                                    buf = evt.get("buffer", {}).get("data", [])
                                    if buf:
                                        cam.send_video(bytes(buf))

                            elif event_name == "livestream audio data":
                                if cam:
                                    buf = evt.get("buffer", {}).get("data", [])
                                    if buf:
                                        cam.send_audio(bytes(buf))

                            # Property change events (some cams use these for motion)
                            elif event_name == "property changed":
                                prop_name = evt.get("name", "")
                                prop_value = evt.get("value", "")
                                if prop_name in ("motionDetected", "personDetected") and cam:
                                    cam.motion_active = bool(prop_value)
                                    if prop_value:
                                        cam.last_motion_time = time.time()
                                        log.info(f"[{cam.name}] {prop_name}={prop_value}")
                                        best = await pick_best_camera()
                                        if best != active_serial:
                                            await switch_stream(ws, best)
                                    else:
                                        cam.last_motion_time = time.time()

                    except asyncio.TimeoutError:
                        pass

                    # Periodic check — stop streams that are no longer needed
                    now = time.time()
                    if now - last_check > 5:
                        last_check = now
                        best = await pick_best_camera()
                        if best != active_serial:
                            if best is None:
                                # No cameras need streaming
                                await switch_stream(ws, None)
                            else:
                                await switch_stream(ws, best)

        except Exception as e:
            log.error(f"Connection error: {e}, reconnecting in 10s...")
            active_serial = None
            for cam in cameras.values():
                cam.streaming = False
                cam.stream_requested = False
            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
