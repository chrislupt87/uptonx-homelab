"""Auto-recommend processing parameters based on audio analysis features."""


def recommend(features: dict) -> dict:
    """Given analysis features, return recommended processing params + reasoning."""

    snr = features.get("snr_estimate_db", 20)
    noise_floor = features.get("noise_floor_db", -60)
    rms_db = features.get("rms_db", -20)
    peak_db = features.get("peak_db", -3)
    dynamic_range = features.get("dynamic_range_db", 15)
    centroid = features.get("spectral_centroid_hz", 2000)
    rolloff = features.get("spectral_rolloff_hz", 4000)
    flatness = features.get("spectral_flatness", 0.1)
    speech = features.get("speech_likelihood_heuristic", 0.5)
    pitch = features.get("pitch_fundamental_hz", None)
    clipping = features.get("clipping_detected", False)
    silence_ratio = features.get("silence_ratio", 0.1)
    zcr = features.get("zero_crossing_rate", 100)

    reasons = []

    # --- Noise reduction ---
    if snr < 8:
        nr_amount = 70
        nr_mode = "both"
        reasons.append(f"Low SNR ({snr:.0f} dB) - aggressive noise reduction with spectral + neural")
    elif snr < 15:
        nr_amount = 40
        nr_mode = "spectral"
        reasons.append(f"Moderate SNR ({snr:.0f} dB) - medium spectral noise reduction")
    elif snr < 25:
        nr_amount = 20
        nr_mode = "spectral"
        reasons.append(f"Decent SNR ({snr:.0f} dB) - light noise reduction")
    else:
        nr_amount = 5
        nr_mode = "spectral"
        reasons.append(f"Good SNR ({snr:.0f} dB) - minimal noise reduction")

    if noise_floor > -35:
        nr_amount = min(nr_amount + 20, 90)
        reasons.append(f"High noise floor ({noise_floor:.0f} dB) - increased reduction")

    # --- EQ ---
    eq = {"sub": 0, "low": 0, "lmid": 0, "mid": 0, "hmid": 0, "high": 0}

    if speech > 0.5:
        # Speech-optimized EQ
        if centroid < 1200:
            eq["low"] = -3
            eq["lmid"] = -2
            eq["mid"] = 3
            eq["hmid"] = 2
            reasons.append(f"Muddy speech (centroid {centroid:.0f} Hz) - cutting lows, boosting presence")
        elif centroid > 3500:
            eq["low"] = 2
            eq["mid"] = -1
            eq["hmid"] = -2
            eq["high"] = -3
            reasons.append(f"Harsh/tinny speech (centroid {centroid:.0f} Hz) - warming lows, taming highs")
        else:
            eq["lmid"] = -1
            eq["mid"] = 1.5
            eq["hmid"] = 1
            reasons.append("Balanced speech - subtle clarity boost at 2-5 kHz")

        if pitch and pitch < 150:
            eq["sub"] = -2
            eq["low"] = max(eq["low"] - 1, -6)
            reasons.append(f"Deep voice ({pitch:.0f} Hz) - reducing low-end rumble")
        elif pitch and pitch > 250:
            eq["low"] = min(eq["low"] + 1.5, 6)
            reasons.append(f"Higher voice ({pitch:.0f} Hz) - adding warmth")
    else:
        reasons.append("Non-speech audio detected - using neutral EQ")
        if centroid < 800:
            eq["mid"] = 2
            eq["hmid"] = 1
            reasons.append("Dark recording - boosting mids for clarity")
        elif centroid > 4000:
            eq["high"] = -2
            eq["hmid"] = -1
            reasons.append("Bright recording - taming highs")

    # --- Compressor ---
    if dynamic_range > 30:
        comp_threshold = -30
        comp_ratio = 6
        reasons.append(f"Very wide dynamic range ({dynamic_range:.0f} dB) - heavy compression")
    elif dynamic_range > 20:
        comp_threshold = -24
        comp_ratio = 4
        reasons.append(f"Wide dynamic range ({dynamic_range:.0f} dB) - moderate compression")
    elif dynamic_range > 10:
        comp_threshold = -20
        comp_ratio = 3
        reasons.append(f"Normal dynamic range ({dynamic_range:.0f} dB) - gentle compression")
    else:
        comp_threshold = -18
        comp_ratio = 2
        reasons.append(f"Narrow dynamic range ({dynamic_range:.0f} dB) - light compression")

    if speech > 0.5:
        comp_attack = 5
        comp_release = 150
        reasons.append("Speech detected - fast attack, quick release for intelligibility")
    else:
        comp_attack = 10
        comp_release = 300

    # --- Noise gate ---
    gate_enabled = True
    if noise_floor > -40:
        gate_threshold = noise_floor + 5
        reasons.append(f"Noise floor at {noise_floor:.0f} dB - gate set to {gate_threshold:.0f} dB")
    elif noise_floor > -55:
        gate_threshold = -50
        reasons.append("Moderate noise floor - standard gate at -50 dB")
    else:
        gate_threshold = -60
        reasons.append("Low noise floor - relaxed gate at -60 dB")

    # --- Voice enhancement ---
    if speech > 0.7:
        voice_enhance = 60
        reasons.append(f"Strong speech signal ({speech*100:.0f}%) - significant voice enhancement")
    elif speech > 0.4:
        voice_enhance = 35
        reasons.append(f"Moderate speech ({speech*100:.0f}%) - moderate voice enhancement")
    else:
        voice_enhance = 0
        reasons.append("Low speech likelihood - voice enhancement disabled")

    # --- Harmonic exciter ---
    if rolloff < 3000:
        harmonic = 40
        reasons.append(f"Dull recording (rolloff {rolloff:.0f} Hz) - harmonic exciter to add brightness")
    elif rolloff < 5000:
        harmonic = 15
        reasons.append("Moderate brightness - light harmonic enhancement")
    else:
        harmonic = 0
        reasons.append("Already bright recording - no harmonic exciter needed")

    # --- Gain / LUFS ---
    if rms_db < -30:
        gain_db = 6
        lufs = -14
        reasons.append(f"Very quiet audio ({rms_db:.0f} dB RMS) - boosting gain, targeting -14 LUFS")
    elif rms_db < -22:
        gain_db = 3
        lufs = -16
        reasons.append(f"Quiet audio ({rms_db:.0f} dB RMS) - moderate gain boost")
    elif rms_db > -10:
        gain_db = -3
        lufs = -18
        reasons.append(f"Loud audio ({rms_db:.0f} dB RMS) - reducing gain to avoid distortion")
    else:
        gain_db = 0
        lufs = -16

    if clipping:
        gain_db = min(gain_db, 0)
        reasons.append("Clipping detected - no additional gain applied")

    params = {
        "denoise_mode": nr_mode,
        "noise_reduction": nr_amount,
        "noise_profile_seconds": 1.5,
        "eq": eq,
        "comp": {
            "threshold": comp_threshold,
            "ratio": comp_ratio,
            "attack": comp_attack,
            "release": comp_release,
            "knee": 30,
        },
        "gate": {
            "enabled": gate_enabled,
            "threshold": round(gate_threshold),
        },
        "voice_enhance": voice_enhance,
        "harmonic_enhance": harmonic,
        "gain_db": gain_db,
        "lufs_target": lufs,
    }

    return {
        "params": params,
        "reasons": reasons,
    }
