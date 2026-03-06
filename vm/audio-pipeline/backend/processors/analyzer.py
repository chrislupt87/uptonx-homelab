import numpy as np
import librosa
import soundfile as sf


def extract_features(audio_path: str) -> dict:
    # Get original channel count from file metadata
    info = sf.info(audio_path)
    channels = info.channels

    # Load as mono 16kHz for analysis
    audio, sr = librosa.load(audio_path, sr=16000, mono=True)
    duration = len(audio) / sr

    # RMS and peak
    rms = np.sqrt(np.mean(audio ** 2))
    peak = np.max(np.abs(audio))
    rms_db = 20 * np.log10(max(rms, 1e-10))
    peak_db = 20 * np.log10(max(peak, 1e-10))

    # Dynamic range across segments
    n_segments = 20
    seg_len = len(audio) // n_segments
    seg_rms = []
    for i in range(n_segments):
        seg = audio[i * seg_len:(i + 1) * seg_len]
        seg_rms_val = np.sqrt(np.mean(seg ** 2))
        seg_rms.append(20 * np.log10(max(seg_rms_val, 1e-10)))
    dynamic_range_db = max(seg_rms) - min(seg_rms)

    # Zero crossing rate
    zcr = librosa.feature.zero_crossing_rate(audio)[0]
    zcr_mean = float(np.mean(zcr) * sr)

    # SNR estimate
    snr_estimate_db = peak_db - rms_db

    # Spectral features
    spectral_centroid = librosa.feature.spectral_centroid(y=audio, sr=sr)[0]
    spectral_rolloff = librosa.feature.spectral_rolloff(y=audio, sr=sr)[0]
    spectral_flatness = librosa.feature.spectral_flatness(y=audio)[0]

    centroid_hz = float(np.mean(spectral_centroid))
    rolloff_hz = float(np.mean(spectral_rolloff))
    flatness = float(np.mean(spectral_flatness))

    # Pitch (YIN)
    fmin = 50
    fmax = 500
    f0 = librosa.yin(audio, fmin=fmin, fmax=fmax, sr=sr)
    voiced = f0[(f0 > fmin) & (f0 < fmax)]
    pitch_hz = float(np.mean(voiced)) if len(voiced) > 0 else None
    pitch_confidence = float(len(voiced) / max(len(f0), 1))

    # Clipping
    clipping = bool(np.any(np.abs(audio) > 0.995))

    # DC offset
    dc = np.mean(audio)
    dc_offset_db = 20 * np.log10(max(abs(dc), 1e-10))

    # Silence ratio
    frame_length = 2048
    hop_length = 512
    rms_frames = librosa.feature.rms(y=audio, frame_length=frame_length, hop_length=hop_length)[0]
    rms_frames_db = 20 * np.log10(np.maximum(rms_frames, 1e-10))
    silence_ratio = float(np.mean(rms_frames_db < -50))

    # Noise floor (10th percentile)
    noise_floor_db = float(np.percentile(rms_frames_db, 10))

    # Speech likelihood heuristic
    speech_score = 0.0
    if 40 <= zcr_mean <= 350:
        speech_score += 0.30
    elif 15 <= zcr_mean <= 500:
        speech_score += 0.10
    if 500 <= centroid_hz <= 4000:
        speech_score += 0.20
    if pitch_confidence > 0.4:
        speech_score += 0.20
    if snr_estimate_db > 5:
        speech_score += 0.15
    if dynamic_range_db > 8:
        speech_score += 0.15
    speech_score = max(0.0, min(1.0, speech_score))

    # Transcribability
    snr_bonus = 0.1 if snr_estimate_db > 10 else (-0.3 if snr_estimate_db < 3 else 0)
    transcribability = max(0.0, min(1.0, speech_score * (1.0 + snr_bonus)))

    # Noise estimate ratio
    noise_estimate_ratio = max(0.0, min(1.0, flatness))

    # Energy segments
    energy_segments = [round(v, 2) for v in seg_rms]

    return {
        "duration": round(duration, 3),
        "sample_rate": sr,
        "channels": channels,
        "rms_db": round(rms_db, 2),
        "peak_db": round(peak_db, 2),
        "dynamic_range_db": round(dynamic_range_db, 2),
        "zero_crossing_rate": round(zcr_mean, 2),
        "snr_estimate_db": round(snr_estimate_db, 2),
        "spectral_centroid_hz": round(centroid_hz, 2),
        "spectral_rolloff_hz": round(rolloff_hz, 2),
        "spectral_flatness": round(flatness, 4),
        "pitch_fundamental_hz": round(pitch_hz, 2) if pitch_hz else None,
        "pitch_confidence": round(pitch_confidence, 3),
        "clipping_detected": clipping,
        "dc_offset_db": round(dc_offset_db, 2),
        "silence_ratio": round(silence_ratio, 3),
        "noise_floor_db": round(noise_floor_db, 2),
        "speech_likelihood_heuristic": round(speech_score, 3),
        "transcribability_heuristic": round(transcribability, 3),
        "noise_estimate_ratio": round(noise_estimate_ratio, 4),
        "energy_segments": energy_segments,
        "spectrogram_url": None,
    }
