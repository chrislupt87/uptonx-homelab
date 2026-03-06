import numpy as np
from scipy import signal as sp


def apply_eq_band(audio, sr, freq, gain_db, filter_type="peaking", Q=1.41):
    """Apply a single EQ band using scipy IIR biquad."""
    if abs(gain_db) < 0.1:
        return audio
    w0 = 2 * np.pi * freq / sr
    A = 10 ** (gain_db / 40)
    alpha = np.sin(w0) / (2 * Q)

    if filter_type == "peaking":
        b = [1 + alpha*A, -2*np.cos(w0), 1 - alpha*A]
        a = [1 + alpha/A, -2*np.cos(w0), 1 - alpha/A]
    elif filter_type == "lowshelf":
        b = [A*((A+1)-(A-1)*np.cos(w0)+2*np.sqrt(A)*alpha),
             2*A*((A-1)-(A+1)*np.cos(w0)),
             A*((A+1)-(A-1)*np.cos(w0)-2*np.sqrt(A)*alpha)]
        a = [(A+1)+(A-1)*np.cos(w0)+2*np.sqrt(A)*alpha,
             -2*((A-1)+(A+1)*np.cos(w0)),
             (A+1)+(A-1)*np.cos(w0)-2*np.sqrt(A)*alpha]
    elif filter_type == "highshelf":
        b = [A*((A+1)+(A-1)*np.cos(w0)+2*np.sqrt(A)*alpha),
             -2*A*((A-1)+(A+1)*np.cos(w0)),
             A*((A+1)+(A-1)*np.cos(w0)-2*np.sqrt(A)*alpha)]
        a = [(A+1)-(A-1)*np.cos(w0)+2*np.sqrt(A)*alpha,
             2*((A-1)-(A+1)*np.cos(w0)),
             (A+1)-(A-1)*np.cos(w0)-2*np.sqrt(A)*alpha]
    else:
        return audio

    sos = sp.tf2sos(b, a)
    return sp.sosfilt(sos, audio).astype(np.float32)


def apply_rms_compressor(audio, sr, threshold_db, ratio, attack_ms, release_ms, knee_db):
    """RMS envelope follower compressor."""
    threshold = 10 ** (threshold_db / 20)
    attack  = np.exp(-1 / (sr * attack_ms / 1000))
    release = np.exp(-1 / (sr * release_ms / 1000))
    knee    = 10 ** (knee_db / 20)

    envelope = np.zeros(len(audio))
    env = 0.0
    for i, s in enumerate(np.abs(audio)):
        if s > env:
            env = attack * env + (1 - attack) * s
        else:
            env = release * env + (1 - release) * s
        envelope[i] = env

    gain = np.ones(len(audio))
    mask = envelope > threshold / knee
    over = envelope[mask]
    # Soft knee gain reduction
    gain[mask] = (threshold * (over / threshold) ** (1.0 / ratio)) / over
    return (audio * gain).astype(np.float32)


def apply_noise_gate(audio, sr, threshold_db, enabled):
    if not enabled:
        return audio
    threshold = 10 ** (threshold_db / 20)
    frame_len, hop = 2048, 512
    import librosa
    rms = librosa.feature.rms(y=audio, frame_length=frame_len, hop_length=hop)[0]
    mask_frames = (rms > threshold).astype(float)
    # Smooth mask to avoid clicks
    from scipy.ndimage import uniform_filter1d
    mask_frames = uniform_filter1d(mask_frames, size=5)
    mask = np.repeat(mask_frames, hop)[:len(audio)]
    return (audio * mask).astype(np.float32)


def apply_harmonic_exciter(audio, sr, amount):
    """Generate and blend subtle harmonics for thin/compressed recordings."""
    if amount < 1:
        return audio
    amt = amount / 100.0
    # Soft saturation on high-passed signal
    sos = sp.butter(4, 3000 / (sr / 2), btype='high', output='sos')
    hi = sp.sosfilt(sos, audio)
    excited = np.tanh(hi * (1 + amt * 3)) * amt * 0.15
    return np.clip(audio + excited, -1.0, 1.0).astype(np.float32)


def full_pipeline(audio: np.ndarray, sr: int, params: dict) -> np.ndarray:
    """Main processing chain — called by /api/process."""
    eq   = params.get("eq", {})
    comp = params.get("comp", {})
    gate = params.get("gate", {})

    # 1. DC offset removal
    audio = audio - np.mean(audio)

    # 2. Soft de-clipper
    audio = np.tanh(audio * 1.15) / 1.15

    # 3. Noise gate
    audio = apply_noise_gate(audio, sr,
        gate.get("threshold", -55),
        gate.get("enabled", True))

    # 4-5. Noise reduction (spectral + optional neural) — called from main.py
    # (enhancer.py handles this step before full_pipeline is called)

    # 6. Parametric EQ — 6 bands
    EQ_BANDS = [
        ("sub",  60,    "lowshelf"),
        ("low",  200,   "peaking"),
        ("lmid", 500,   "peaking"),
        ("mid",  2000,  "peaking"),
        ("hmid", 5000,  "peaking"),
        ("high", 12000, "highshelf"),
    ]
    for key, freq, ftype in EQ_BANDS:
        audio = apply_eq_band(audio, sr, freq, eq.get(key, 0), ftype)

    # 7. Voice enhancement chain
    ve = params.get("voice_enhance", 0) / 100.0
    if ve > 0:
        audio = apply_eq_band(audio, sr, 120,  -ve * 1.5, "lowshelf")   # de-boom
        audio = apply_eq_band(audio, sr, 350,  -ve * 2.5, "peaking")    # de-mud
        audio = apply_eq_band(audio, sr, 2800,  ve * 5.0, "peaking",  Q=0.9)  # presence
        audio = apply_eq_band(audio, sr, 9000,  ve * 2.5, "highshelf")  # air

    # 8. Harmonic exciter
    audio = apply_harmonic_exciter(audio, sr, params.get("harmonic_enhance", 0))

    # 9. Compressor
    audio = apply_rms_compressor(audio, sr,
        comp.get("threshold", -24),
        comp.get("ratio", 4),
        comp.get("attack", 3),
        comp.get("release", 250),
        comp.get("knee", 30))

    # 10. Output gain
    gain_db = params.get("gain_db", 0)
    audio = audio * (10 ** (gain_db / 20))

    # 11. Hard limiter
    audio = np.clip(audio, -0.99, 0.99)

    return audio.astype(np.float32)
