#!/usr/bin/env python3
"""
Eufy P2P → TCP bridge for go2rtc/Frigate (continuous streaming).

Connects to eufy-security-ws and keeps all cameras streaming continuously.
When a stream drops, it restarts after a short delay. Each camera gets its
own video and audio TCP port that go2rtc/Frigate connects to.

Each camera gets a video port (base_port + index*2) and audio port (base_port + index*2 + 1).

Set STREAM_MODE=motion to revert to the old motion-triggered behavior.
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
# How long to keep streaming after last motion event (motion mode only)
STREAM_TIMEOUT = int(os.getenv("STREAM_TIMEOUT", "30"))
# continuous = stream all cameras simultaneously; motion = only on motion events
# round-robin = rotate through cameras one at a time (legacy)
STREAM_MODE = os.getenv("STREAM_MODE", "continuous")
# Delay before restarting a dropped stream
RESTART_DELAY = int(os.getenv("RESTART_DELAY", "3"))
# How long each camera gets in round-robin mode (seconds)
ROTATION_INTERVAL = int(os.getenv("ROTATION_INTERVAL", "60"))
SCHEMA_VERSION = 21

# MediaMTX RTSP relay
MEDIAMTX_URL = os.getenv("MEDIAMTX_URL", "")
CAMERA_NAMES = [s.strip() for s in os.getenv("CAMERA_NAMES", "").split(",") if s.strip()]

import subprocess as _subprocess


class CameraBridge:
    def __init__(self, serial, name, priority, video_port, audio_port, rtsp_name=""):
        self.serial = serial
        self.name = name
        self.priority = priority
        self.video_port = video_port
        self.audio_port = audio_port
        self.video_clients = []
        self.audio_clients = []
        self.streaming = False
        self.motion_active = False
        self.last_motion_time = 0
        self.rtsp_name = rtsp_name  # e.g. "eufy_kitchen"
        self.ffmpeg_proc = None     # ffmpeg process pushing to mediamtx
        self.stream_requested = False
        self.last_video_time = 0
        self.bytes_received = 0

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
        self.last_video_time = time.time()
        self.bytes_received += len(data)
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

    def start_rtsp_push(self):
        """Spawn ffmpeg to push TCP stream to mediamtx RTSP server."""
        if not MEDIAMTX_URL or not self.rtsp_name:
            return
        self.stop_rtsp_push()
        rtsp_url = f"{MEDIAMTX_URL}/{self.rtsp_name}"
        cmd = [
            "ffmpeg",
            "-probesize", "50000000",
            "-analyzeduration", "50000000",
            "-f", "hevc", "-i", f"tcp://127.0.0.1:{self.video_port}",
            "-c:v", "copy", "-an",
            "-f", "rtsp", "-rtsp_transport", "tcp",
            rtsp_url,
        ]
        try:
            self.ffmpeg_proc = _subprocess.Popen(
                cmd, stdout=_subprocess.DEVNULL, stderr=_subprocess.DEVNULL
            )
            log.info(f"[{self.name}] RTSP push started → {rtsp_url} (pid={self.ffmpeg_proc.pid})")
        except Exception as e:
            log.error(f"[{self.name}] Failed to start RTSP push: {e}")

    def stop_rtsp_push(self):
        """Kill the ffmpeg RTSP push process."""
        if self.ffmpeg_proc and self.ffmpeg_proc.poll() is None:
            self.ffmpeg_proc.terminate()
            try:
                self.ffmpeg_proc.wait(timeout=5)
            except _subprocess.TimeoutExpired:
                self.ffmpeg_proc.kill()
            log.info(f"[{self.name}] RTSP push stopped")
        self.ffmpeg_proc = None

    @property
    def wants_stream(self):
        """Camera wants a stream if motion is active or recently ended."""
        if self.motion_active:
            return True
        if self.last_motion_time > 0:
            elapsed = time.time() - self.last_motion_time
            return elapsed < STREAM_TIMEOUT
        return False


async def start_camera_stream(ws, cam):
    """Send the start_livestream command for a camera."""
    await ws.send(json.dumps({
        "messageId": f"start_{cam.serial}",
        "command": "device.start_livestream",
        "serialNumber": cam.serial,
    }))
    cam.stream_requested = True
    log.info(f"[{cam.name}] Starting stream")


async def stop_camera_stream(ws, cam):
    """Send the stop_livestream command for a camera."""
    if cam.streaming or cam.stream_requested:
        await ws.send(json.dumps({
            "messageId": f"stop_{cam.serial}",
            "command": "device.stop_livestream",
            "serialNumber": cam.serial,
        }))
        log.info(f"[{cam.name}] Stopping stream")


async def main():
    import websockets

    cameras = {}  # serial -> CameraBridge

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

                # Set up camera bridges
                need_tcp_setup = len(cameras) == 0
                for idx, serial in enumerate(CAMERA_SERIALS):
                    if serial not in device_serials:
                        log.warning(f"Camera {serial} not found in device list, will try anyway")

                    vport = BASE_PORT + idx * 2
                    aport = BASE_PORT + idx * 2 + 1

                    if need_tcp_setup:
                        await ws.send(json.dumps({
                            "messageId": f"props_{serial}",
                            "command": "device.get_properties",
                            "serialNumber": serial,
                        }))
                        resp = await asyncio.wait_for(ws.recv(), timeout=5)
                        props = json.loads(resp).get("result", {}).get("properties", {})
                        name = props.get("name", serial)

                        rtsp_name = CAMERA_NAMES[idx] if idx < len(CAMERA_NAMES) else f"eufy_{idx}"
                        cam = CameraBridge(serial, name, idx, vport, aport, rtsp_name)
                        cameras[serial] = cam

                        await asyncio.start_server(cam.handle_video_client, "0.0.0.0", vport)
                        await asyncio.start_server(cam.handle_audio_client, "0.0.0.0", aport)
                        log.info(f"[{name}] priority={idx} serial={serial} video=:{vport} audio=:{aport}")
                    else:
                        # Reconnect — reset stream state but keep TCP servers
                        cam = cameras.get(serial)
                        if cam:
                            cam.streaming = False
                            cam.stream_requested = False

                log.info(f"Mode: {STREAM_MODE} | Cameras: {len(cameras)}")

                # Round-robin state (only used in round-robin mode)
                cam_order = list(cameras.keys())
                current_cam_idx = 0
                rotation_start = time.time()
                active_serial = None

                # In continuous mode, start all cameras (requires hub that supports it)
                if STREAM_MODE == "continuous" and cam_order:
                    for serial in cam_order:
                        await start_camera_stream(ws, cameras[serial])
                        await asyncio.sleep(1)
                    log.info(f"Continuous: streaming all {len(cam_order)} cameras simultaneously")
                elif STREAM_MODE in ("round-robin", "rotation") and cam_order:
                    active_serial = cam_order[0]
                    await start_camera_stream(ws, cameras[active_serial])
                    log.info(f"Round-robin: starting with {cameras[active_serial].name} ({ROTATION_INTERVAL}s per camera)")

                # Main event loop
                last_health_check = time.time()

                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5)
                        msg = json.loads(raw)

                        if msg.get("type") == "event":
                            evt = msg.get("event", {})
                            event_name = evt.get("event", "")
                            serial = evt.get("serialNumber", "")
                            cam = cameras.get(serial)

                            # Livestream data
                            if event_name == "livestream video data":
                                if cam:
                                    buf = evt.get("buffer", {}).get("data", [])
                                    if buf:
                                        cam.send_video(bytes(buf))

                            elif event_name == "livestream audio data":
                                if cam:
                                    buf = evt.get("buffer", {}).get("data", [])
                                    if buf:
                                        cam.send_audio(bytes(buf))

                            elif event_name == "livestream started":
                                if cam:
                                    cam.streaming = True
                                    cam.bytes_received = 0
                                    log.info(f"[{cam.name}] Livestream active")
                                    cam.start_rtsp_push()

                            elif event_name == "livestream stopped":
                                if cam:
                                    cam.stop_rtsp_push()
                                    cam.streaming = False
                                    cam.stream_requested = False
                                    log.info(f"[{cam.name}] Livestream stopped (received {cam.bytes_received:,} bytes)")

                                    # In continuous mode, restart this camera immediately
                                    if STREAM_MODE == "continuous":
                                        log.info(f"[{cam.name}] Restarting in {RESTART_DELAY}s...")
                                        await asyncio.sleep(RESTART_DELAY)
                                        await start_camera_stream(ws, cam)
                                    # In round-robin mode, only restart if it's the active camera
                                    elif STREAM_MODE == "round-robin" and serial == active_serial:
                                        log.info(f"[{cam.name}] Restarting in {RESTART_DELAY}s...")
                                        await asyncio.sleep(RESTART_DELAY)
                                        await start_camera_stream(ws, cam)

                            # Motion events (still tracked for logging)
                            elif event_name in ("motion detected", "person detected",
                                                 "motion detection"):
                                if cam:
                                    motion_state = evt.get("state", True)
                                    cam.motion_active = bool(motion_state)
                                    if motion_state:
                                        cam.last_motion_time = time.time()
                                        log.info(f"[{cam.name}] {event_name}")

                                    # In motion mode, manage streams based on motion
                                    if STREAM_MODE == "motion":
                                        if motion_state and not cam.streaming and not cam.stream_requested:
                                            await start_camera_stream(ws, cam)

                            elif event_name == "property changed":
                                prop_name = evt.get("name", "")
                                prop_value = evt.get("value", "")
                                if prop_name in ("motionDetected", "personDetected") and cam:
                                    cam.motion_active = bool(prop_value)
                                    if prop_value:
                                        cam.last_motion_time = time.time()
                                        log.info(f"[{cam.name}] {prop_name}={prop_value}")
                                        if STREAM_MODE == "motion" and not cam.streaming and not cam.stream_requested:
                                            await start_camera_stream(ws, cam)

                    except asyncio.TimeoutError:
                        pass

                    # Health check + rotation
                    now = time.time()
                    if now - last_health_check > 10:
                        last_health_check = now

                        if STREAM_MODE == "continuous" and cam_order:
                            # Check ALL cameras — restart any that stopped
                            for serial in cam_order:
                                cam = cameras[serial]
                                if not cam.streaming and not cam.stream_requested:
                                    log.info(f"[{cam.name}] Not streaming, restarting...")
                                    await start_camera_stream(ws, cam)

                                # Check for stale stream (no data for 30s)
                                if cam.streaming and cam.last_video_time > 0:
                                    stale = now - cam.last_video_time
                                    if stale > 30:
                                        log.warning(f"[{cam.name}] No video data for {stale:.0f}s, restarting...")
                                        await stop_camera_stream(ws, cam)
                                        await asyncio.sleep(RESTART_DELAY)
                                        await start_camera_stream(ws, cam)

                        elif STREAM_MODE == "round-robin" and cam_order:
                            # Rotate to next camera after ROTATION_INTERVAL
                            if now - rotation_start >= ROTATION_INTERVAL:
                                old_cam = cameras.get(active_serial)
                                if old_cam:
                                    await stop_camera_stream(ws, old_cam)

                                current_cam_idx = (current_cam_idx + 1) % len(cam_order)
                                active_serial = cam_order[current_cam_idx]
                                new_cam = cameras[active_serial]
                                rotation_start = now
                                await asyncio.sleep(RESTART_DELAY)
                                await start_camera_stream(ws, new_cam)
                                log.info(f"Round-robin: rotated to {new_cam.name}")

                            # Restart if active camera died
                            active_cam = cameras.get(active_serial)
                            if active_cam and not active_cam.streaming and not active_cam.stream_requested:
                                log.info(f"[{active_cam.name}] Not streaming, restarting...")
                                await start_camera_stream(ws, active_cam)

                            # Check for stale stream
                            if active_cam and active_cam.streaming and active_cam.last_video_time > 0:
                                stale = now - active_cam.last_video_time
                                if stale > 30:
                                    log.warning(f"[{active_cam.name}] No video data for {stale:.0f}s, restarting...")
                                    await stop_camera_stream(ws, active_cam)
                                    await asyncio.sleep(RESTART_DELAY)
                                    await start_camera_stream(ws, active_cam)

                        elif STREAM_MODE == "motion":
                            for serial, cam in cameras.items():
                                if cam.streaming and not cam.wants_stream:
                                    await stop_camera_stream(ws, cam)

        except Exception as e:
            log.error(f"Connection error: {e}, reconnecting in 10s...")
            for cam in cameras.values():
                cam.streaming = False
                cam.stream_requested = False
            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
