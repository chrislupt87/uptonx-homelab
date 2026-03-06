import os, uuid, shutil, hashlib, json, io, base64
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
import librosa
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import librosa.display

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse

from processors.analyzer  import extract_features
from processors.enhancer  import denoise
from processors.equalizer import full_pipeline
from processors.transcriber import transcribe, transcribe_streaming, get_model, AVAILABLE_MODELS
from processors.diarizer  import diarize, merge_with_transcript, is_available as diar_available
from processors.recommender import recommend

import pyloudnorm as pyln
from db import init_db, save_job, update_job_processing, update_job_transcript, get_job, list_jobs

from starlette.formparsers import MultiPartParser
MultiPartParser.max_file_size = 200 * 1024 * 1024  # 200 MB

app = FastAPI(title="UptonX Forensic Audio Pipeline", version="2.1")

app.add_middleware(CORSMiddleware,
    allow_origins=["https://audio.uptonx.com", "http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"], allow_headers=["*"])

TMP = Path("/tmp/audio")
TMP.mkdir(parents=True, exist_ok=True)

MAX_MB = int(os.getenv("MAX_UPLOAD_MB", 150))
LUFS_TARGET = float(os.getenv("LUFS_TARGET", -16))

# Initialize SQLite on startup
init_db()


def save_spectrogram(audio: np.ndarray, sr: int, job_id: str) -> str:
    fig, ax = plt.subplots(figsize=(10, 3), facecolor="#ffffff")
    S = librosa.feature.melspectrogram(y=audio, sr=sr, n_mels=128, fmax=8000)
    S_db = librosa.power_to_db(S, ref=np.max)
    img = librosa.display.specshow(S_db, sr=sr, x_axis="time", y_axis="mel",
                                    ax=ax, cmap="viridis")
    ax.set_facecolor("#ffffff")
    plt.colorbar(img, ax=ax, format="%+2.0f dB")
    ax.set_title("")
    plt.tight_layout(pad=0.3)
    out = TMP / f"spec_{job_id}.png"
    plt.savefig(str(out), dpi=100, bbox_inches="tight", facecolor="white")
    plt.close()
    return f"/api/spectrogram/{job_id}"


def lufs_normalize(audio: np.ndarray, sr: int, target_lufs: float) -> np.ndarray:
    meter = pyln.Meter(sr)
    try:
        loudness = meter.integrated_loudness(audio)
        if np.isinf(loudness) or np.isnan(loudness):
            return audio
        return pyln.normalize.loudness(audio, loudness, target_lufs)
    except Exception:
        return audio


def file_hashes(path: str) -> dict:
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            md5.update(chunk)
            sha256.update(chunk)
    return {"md5": md5.hexdigest(), "sha256": sha256.hexdigest()}


@app.get("/api/health")
def health():
    try:
        m = get_model()
        whisper_ok = True
        whisper_model = os.getenv("WHISPER_MODEL", "large-v3")
    except Exception:
        whisper_ok = False
        whisper_model = "error"

    df_ok = False
    try:
        from df.enhance import init_df
        df_ok = True
    except Exception:
        pass

    return {
        "status": "ok",
        "whisper_model": whisper_model if whisper_ok else "not loaded",
        "whisper_loaded": whisper_ok,
        "deepfilter_enabled": df_ok,
        "diarization_enabled": diar_available(),
        "available_models": AVAILABLE_MODELS,
        "version": "2.1"
    }


@app.get("/api/models")
def get_models():
    default = os.getenv("WHISPER_MODEL", "large-v3")
    return {
        "models": AVAILABLE_MODELS,
        "default": default,
        "loaded": list(_models_loaded()),
    }


def _models_loaded():
    from processors.transcriber import _models
    return list(_models.keys())


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...)):
    if file.size and file.size > MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {MAX_MB}MB limit")

    job_id = str(uuid.uuid4())[:8]
    tmp_path = TMP / f"raw_{job_id}{Path(file.filename).suffix}"

    try:
        with open(tmp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        hashes = file_hashes(str(tmp_path))
        features = extract_features(str(tmp_path))
        spec_url = None

        try:
            audio, sr = librosa.load(str(tmp_path), sr=16000, mono=True)
            spec_url = save_spectrogram(audio, sr, f"orig_{job_id}")
        except Exception as e:
            print(f"Spectrogram error: {e}")

        features["spectrogram_url"] = spec_url
        features["job_id"] = job_id
        features["file_hashes"] = hashes

        # Auto-recommend processing params based on analysis
        recommendation = recommend(features)
        features["recommended"] = recommendation

        # Save to DB
        save_job(job_id, file.filename, file.size, features, hashes)

        return JSONResponse(features)

    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@app.post("/api/process")
async def process(
    file: UploadFile = File(...),
    params: str = Form("{}"),
    job_id: Optional[str] = Form(None)
):
    p = json.loads(params)

    if not job_id:
        job_id = str(uuid.uuid4())[:8]

    tmp_in  = TMP / f"in_{job_id}{Path(file.filename).suffix}"
    tmp_out = TMP / f"out_{job_id}.wav"

    try:
        with open(tmp_in, "wb") as f:
            shutil.copyfileobj(file.file, f)

        audio, sr = librosa.load(str(tmp_in), sr=16000, mono=True)
        audio = denoise(audio, sr, p)
        audio = full_pipeline(audio, sr, p)

        lufs = p.get("lufs_target", LUFS_TARGET)
        audio = lufs_normalize(audio, sr, lufs)

        sf.write(str(tmp_out), audio, sr, subtype="PCM_16")
        spec_url = save_spectrogram(audio, sr, f"proc_{job_id}")
        features = extract_features(str(tmp_out))
        features["spectrogram_url"] = spec_url

        with open(tmp_out, "rb") as f:
            wav_b64 = base64.b64encode(f.read()).decode()

        # Save to DB
        update_job_processing(job_id, p, features)

        return JSONResponse({
            "job_id": job_id,
            "processed_wav_b64": wav_b64,
            "analysis": features,
        })

    finally:
        for p_ in [tmp_in, tmp_out]:
            if p_.exists():
                p_.unlink()


@app.post("/api/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    beam_size: int = 5,
    model: Optional[str] = None,
    enable_diarization: bool = True,
    job_id: Optional[str] = None
):
    if not job_id:
        job_id = str(uuid.uuid4())[:8]
    tmp_path = TMP / f"trans_{job_id}.wav"

    try:
        with open(tmp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        result = transcribe(str(tmp_path), beam_size=beam_size, model_name=model)

        if enable_diarization and diar_available():
            turns = diarize(str(tmp_path))
            result["segments"] = merge_with_transcript(result["segments"], turns)
            result["speakers"] = list({t["speaker"] for t in turns})
            result["diarization_turns"] = turns
        else:
            result["speakers"] = []
            result["diarization_turns"] = []

        # Save to DB
        update_job_transcript(job_id, result)

        return JSONResponse(result)

    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@app.websocket("/api/ws/transcribe")
async def ws_transcribe(websocket: WebSocket):
    await websocket.accept()
    try:
        # 1. Receive config as JSON text message
        config_raw = await websocket.receive_text()
        config = json.loads(config_raw)
        beam_size = config.get("beam_size", 5)
        model_name = config.get("model", None)
        enable_diarization = config.get("enable_diarization", True)
        job_id = config.get("job_id", str(uuid.uuid4())[:8])

        # 2. Receive audio as binary message
        audio_bytes = await websocket.receive_bytes()

        tmp_path = TMP / f"ws_{job_id}.wav"
        with open(tmp_path, "wb") as f:
            f.write(audio_bytes)

        await websocket.send_json({"type": "started", "job_id": job_id})

        # 3. Stream transcription segments
        result_segments = []
        info_data = {}
        for event in transcribe_streaming(str(tmp_path), beam_size=beam_size, model_name=model_name):
            if event["type"] == "info":
                info_data = event
                await websocket.send_json(event)
            elif event["type"] == "segment":
                result_segments.append(event["segment"])
                await websocket.send_json(event)
            elif event["type"] == "complete":
                final = event
                # Handle diarization
                if enable_diarization and diar_available():
                    turns = diarize(str(tmp_path))
                    final["segments"] = merge_with_transcript(final["segments"], turns)
                    final["speakers"] = list({t["speaker"] for t in turns})
                    final["diarization_turns"] = turns
                else:
                    final["speakers"] = []
                    final["diarization_turns"] = []

                update_job_transcript(job_id, final)
                await websocket.send_json(final)

        # Cleanup
        if tmp_path.exists():
            tmp_path.unlink()

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


# Job history endpoints
@app.get("/api/jobs")
def jobs_list(limit: int = Query(50, le=200), offset: int = Query(0, ge=0)):
    return list_jobs(limit, offset)


@app.get("/api/jobs/{job_id}")
def jobs_detail(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


# Operations endpoints
@app.get("/api/ops/status")
def ops_status():
    """System status for the ops panel."""
    import psutil
    import subprocess
    import time

    # Disk usage for volumes
    disk = psutil.disk_usage("/data")
    tmp_disk = psutil.disk_usage("/tmp")

    # DB size
    db_size = 0
    db_path = Path(os.getenv("AUDIO_DB_PATH", "/data/audio_pipeline.db"))
    if db_path.exists():
        db_size = db_path.stat().st_size

    # Count jobs
    from db import get_db
    conn = get_db()
    job_count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    conn.close()

    # Memory
    mem = psutil.virtual_memory()
    proc = psutil.Process()
    proc_mem = proc.memory_info()

    return {
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "memory": {
            "total_gb": round(mem.total / 1e9, 1),
            "used_gb": round(mem.used / 1e9, 1),
            "percent": mem.percent,
            "api_process_mb": round(proc_mem.rss / 1e6, 0),
        },
        "disk": {
            "data_total_gb": round(disk.total / 1e9, 1),
            "data_used_gb": round(disk.used / 1e9, 1),
            "data_percent": round(disk.percent, 1),
            "tmp_used_mb": round((tmp_disk.total - tmp_disk.free) / 1e6, 0),
        },
        "database": {
            "size_kb": round(db_size / 1024, 1),
            "job_count": job_count,
        },
        "whisper_models_loaded": list(_models_loaded()),
        "uptime_seconds": round(time.time() - proc.create_time(), 0),
    }


@app.post("/api/ops/clear-tmp")
def ops_clear_tmp():
    """Clear temporary audio files."""
    count = 0
    for f in TMP.iterdir():
        if f.is_file():
            f.unlink()
            count += 1
    return {"cleared": count}


@app.post("/api/ops/unload-model")
def ops_unload_model(model: str = Query(...)):
    """Unload a Whisper model from memory."""
    from processors.transcriber import _models, _model_order
    if model in _models:
        del _models[model]
        if model in _model_order:
            _model_order.remove(model)
        return {"unloaded": model}
    raise HTTPException(404, f"Model {model} not loaded")


@app.get("/api/ops/logs")
def ops_logs(lines: int = Query(100, le=500)):
    """Get recent API logs from stderr/stdout."""
    import subprocess
    # Read from Docker log file if available, otherwise return message
    try:
        result = subprocess.run(
            ["tail", "-n", str(lines), "/proc/1/fd/2"],
            capture_output=True, text=True, timeout=5
        )
        log_lines = result.stdout or result.stderr or "No logs available"
    except Exception:
        log_lines = "Log access not available in this environment"
    return {"logs": log_lines}


@app.get("/api/spectrogram/{spec_id}")
def get_spectrogram(spec_id: str):
    path = TMP / f"spec_{spec_id}.png"
    if not path.exists():
        raise HTTPException(404, "Spectrogram not found or expired")
    return FileResponse(str(path), media_type="image/png")
