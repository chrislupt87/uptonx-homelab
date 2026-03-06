import noisereduce as nr
import numpy as np


def denoise(audio: np.ndarray, sr: int, params: dict) -> np.ndarray:
    mode = params.get("denoise_mode", "spectral")   # spectral | neural | both
    amount = params.get("noise_reduction", 30) / 100.0
    profile_secs = params.get("noise_profile_seconds", 1.5)

    if amount < 0.01:
        return audio

    profile_samples = int(sr * profile_secs)
    noise_clip = audio[:min(profile_samples, len(audio))]

    if mode in ("spectral", "both"):
        audio = nr.reduce_noise(
            y=audio,
            sr=sr,
            y_noise=noise_clip,
            prop_decrease=amount,
            stationary=False,
            n_fft=2048
        )

    if mode in ("neural", "both") and amount > 0.1:
        try:
            from df.enhance import enhance, init_df
            import torch, torchaudio
            model, df_state, _ = init_df()
            target_sr = df_state.sr()
            t = torch.from_numpy(audio.astype(np.float32)).unsqueeze(0)
            if sr != target_sr:
                t = torchaudio.functional.resample(t, sr, target_sr)
            enhanced = enhance(model, df_state, t)
            if sr != target_sr:
                enhanced = torchaudio.functional.resample(enhanced, target_sr, sr)
            audio = enhanced.squeeze(0).numpy()
        except Exception as e:
            print(f"DeepFilterNet3 error (falling back): {e}")

    return audio
