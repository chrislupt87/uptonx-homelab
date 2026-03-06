import os

_pipeline = None

def is_available() -> bool:
    return bool(os.getenv("HF_TOKEN"))


def get_pipeline():
    global _pipeline
    if _pipeline is None:
        from pyannote.audio import Pipeline
        _pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=os.getenv("HF_TOKEN")
        )
    return _pipeline


def diarize(audio_path: str) -> list[dict]:
    """Returns list of {speaker, start, end} dicts."""
    if not is_available():
        return []
    try:
        pipeline = get_pipeline()
        diarization = pipeline(audio_path)
        turns = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            turns.append({
                "speaker": speaker,
                "start":   round(turn.start, 3),
                "end":     round(turn.end, 3),
            })
        return turns
    except Exception as e:
        print(f"Diarization error: {e}")
        return []


def merge_with_transcript(segments: list, turns: list) -> list:
    """Assign speaker labels to transcript segments by overlap."""
    if not turns:
        return segments
    for seg in segments:
        best_speaker, best_overlap = "UNKNOWN", 0.0
        for turn in turns:
            overlap = min(seg["end"], turn["end"]) - max(seg["start"], turn["start"])
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = turn["speaker"]
        seg["speaker"] = best_speaker
    return segments
