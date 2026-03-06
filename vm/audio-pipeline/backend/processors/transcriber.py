import os, math
from faster_whisper import WhisperModel

_models = {}
_model_order = []
MAX_CACHED_MODELS = 2

AVAILABLE_MODELS = ["tiny", "base", "small", "medium", "large-v3"]


def get_model(model_name=None):
    global _models, _model_order
    if model_name is None:
        model_name = os.getenv("WHISPER_MODEL", "large-v3")

    if model_name in _models:
        return _models[model_name]

    # Evict oldest if at capacity
    while len(_models) >= MAX_CACHED_MODELS:
        oldest = _model_order.pop(0)
        del _models[oldest]
        print(f"Evicted Whisper model: {oldest}")

    print(f"Loading Whisper model: {model_name}...")
    _models[model_name] = WhisperModel(
        model_name,
        device="cpu",
        compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8")
    )
    _model_order.append(model_name)
    return _models[model_name]


def _do_transcribe(model, audio_path, beam_size):
    """Try transcription with auto-detect, fall back to English on failure."""
    try:
        return model.transcribe(
            audio_path,
            language=None,
            word_timestamps=True,
            vad_filter=True,
            beam_size=beam_size,
            vad_parameters={"min_silence_duration_ms": 500}
        )
    except ValueError:
        # Language detection failed (empty sequence) — retry with explicit English
        return model.transcribe(
            audio_path,
            language="en",
            word_timestamps=True,
            vad_filter=True,
            beam_size=beam_size,
            vad_parameters={"min_silence_duration_ms": 500}
        )


def transcribe(audio_path, beam_size=5, model_name=None):
    model = get_model(model_name)
    segments, info = _do_transcribe(model, audio_path, beam_size)

    result_segments = []
    for seg in segments:
        confidence = math.exp(max(seg.avg_logprob, -10))
        result_segments.append({
            "start": round(seg.start, 3),
            "end":   round(seg.end, 3),
            "text":  seg.text.strip(),
            "confidence": round(confidence, 3),
            "no_speech_prob": round(seg.no_speech_prob, 3),
            "words": [
                {
                    "word":  w.word,
                    "start": round(w.start, 3),
                    "end":   round(w.end, 3),
                    "prob":  round(w.probability, 3)
                }
                for w in (seg.words or [])
            ]
        })

    return {
        "language":             info.language,
        "language_probability": round(info.language_probability, 3),
        "duration":             round(info.duration, 3),
        "segments":             result_segments,
        "full_text":            " ".join(s["text"] for s in result_segments),
        "word_count":           sum(len(s["words"]) for s in result_segments),
        "model":                model_name or os.getenv("WHISPER_MODEL", "large-v3"),
    }


def transcribe_streaming(audio_path, beam_size=5, model_name=None):
    """Generator that yields segments one at a time for WebSocket streaming."""
    model = get_model(model_name)
    segments, info = _do_transcribe(model, audio_path, beam_size)

    yield {
        "type": "info",
        "language": info.language,
        "language_probability": round(info.language_probability, 3),
        "duration": round(info.duration, 3),
    }

    result_segments = []
    for seg in segments:
        confidence = math.exp(max(seg.avg_logprob, -10))
        seg_data = {
            "start": round(seg.start, 3),
            "end":   round(seg.end, 3),
            "text":  seg.text.strip(),
            "confidence": round(confidence, 3),
            "no_speech_prob": round(seg.no_speech_prob, 3),
            "words": [
                {
                    "word":  w.word,
                    "start": round(w.start, 3),
                    "end":   round(w.end, 3),
                    "prob":  round(w.probability, 3)
                }
                for w in (seg.words or [])
            ]
        }
        result_segments.append(seg_data)
        yield {
            "type": "segment",
            "segment": seg_data,
            "progress": round(seg.end / info.duration, 3) if info.duration > 0 else 0,
        }

    yield {
        "type": "complete",
        "language": info.language,
        "language_probability": round(info.language_probability, 3),
        "duration": round(info.duration, 3),
        "segments": result_segments,
        "full_text": " ".join(s["text"] for s in result_segments),
        "word_count": sum(len(s["words"]) for s in result_segments),
        "model": model_name or os.getenv("WHISPER_MODEL", "large-v3"),
    }
