#!/home/chris/uptonx-homelab/tools/venv-voice-clean/bin/python3
"""
AI Voice Cleaner — Interactive real-time audio processing GUI.

Load audio, play it, move sliders, hear changes live.
Uses neural network denoising + real-time DSP filters.

Usage:
  ./ai-voice-clean.py                  # Opens GUI
  ./ai-voice-clean.py recording.wav    # Opens GUI with file pre-loaded
"""

import sys
import os
import time
import threading
import numpy as np
import warnings
warnings.filterwarnings("ignore")

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import sounddevice as sd

# --- Audio I/O ---

def load_audio(path):
    try:
        import soundfile as sf
        data, sr = sf.read(path, dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        return data, sr
    except Exception:
        pass
    try:
        import torchaudio
        waveform, sr = torchaudio.load(path)
        data = waveform.mean(dim=0).numpy()
        return data, sr
    except Exception as e:
        return None, str(e)


def save_audio(path, data, sr):
    import soundfile as sf
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    sf.write(path, data, sr, subtype="PCM_16")


# --- DSP Filters (real-time capable) ---

def apply_highpass(audio, sr, freq):
    if freq <= 20:
        return audio
    from scipy.signal import butter, sosfilt
    freq = min(freq, sr / 2 - 1)
    sos = butter(4, freq, btype="highpass", fs=sr, output="sos")
    return sosfilt(sos, audio).astype(np.float32)


def apply_lowpass(audio, sr, freq):
    if freq >= sr / 2 - 1:
        return audio
    from scipy.signal import butter, sosfilt
    sos = butter(4, freq, btype="lowpass", fs=sr, output="sos")
    return sosfilt(sos, audio).astype(np.float32)


def apply_notch(audio, sr, freq, q=30):
    if freq <= 0:
        return audio
    from scipy.signal import iirnotch, lfilter
    b, a = iirnotch(freq, q, sr)
    return lfilter(b, a, audio).astype(np.float32)


def apply_gate(audio, sr, threshold_db, reduction_db):
    if threshold_db <= -80:
        return audio
    threshold = 10 ** (threshold_db / 20)
    reduction = 10 ** (reduction_db / 20)
    from scipy.ndimage import maximum_filter1d, uniform_filter1d

    # Fast vectorized envelope
    frame_len = max(1, int(0.01 * sr))
    envelope = maximum_filter1d(np.abs(audio), size=frame_len)
    envelope = uniform_filter1d(envelope, size=int(0.05 * sr))

    gain = np.where(envelope < threshold, reduction, 1.0).astype(np.float32)
    gain = uniform_filter1d(gain, size=int(0.01 * sr))
    return (audio * gain).astype(np.float32)


def apply_compression(audio, sr, threshold_db, ratio):
    if ratio <= 1.0:
        return audio
    threshold = 10 ** (threshold_db / 20)
    from scipy.ndimage import uniform_filter1d

    envelope = np.abs(audio)
    envelope = uniform_filter1d(envelope, size=int(0.005 * sr))

    gain = np.ones_like(envelope)
    mask = envelope > threshold
    gain[mask] = threshold * (envelope[mask] / threshold) ** (1.0 / ratio - 1.0)
    gain = uniform_filter1d(gain, size=int(0.01 * sr))

    return (audio * gain).astype(np.float32)


def apply_eq_presence(audio, sr, boost_db):
    if abs(boost_db) < 0.5:
        return audio
    from scipy.signal import butter, sosfilt
    # Boost/cut 2-5kHz presence range
    low = min(2000, sr / 2 - 1)
    high = min(5000, sr / 2 - 1)
    if low >= high:
        return audio
    sos = butter(2, [low, high], btype="bandpass", fs=sr, output="sos")
    presence = sosfilt(sos, audio).astype(np.float32)
    gain = 10 ** (boost_db / 20) - 1.0
    return (audio + presence * gain).astype(np.float32)


def apply_normalize(audio, target_db=-1.0):
    peak = np.max(np.abs(audio))
    if peak < 1e-8:
        return audio
    target = 10 ** (target_db / 20)
    return (audio * (target / peak)).astype(np.float32)


# --- AI Denoise (pre-computed, not real-time) ---

def denoise_noisereduce(audio, sr, strength=1.0):
    import noisereduce as nr
    return nr.reduce_noise(
        y=audio, sr=sr, stationary=False,
        prop_decrease=min(strength, 1.0),
        n_fft=2048, freq_mask_smooth_hz=500,
        time_mask_smooth_ms=50,
    )


def denoise_facebook(audio, sr):
    try:
        import torch
        from denoiser import pretrained
        from scipy.signal import resample

        model = pretrained.dns64()
        model.eval()

        if sr != 16000:
            audio_16k = resample(audio, int(len(audio) * 16000 / sr)).astype(np.float32)
        else:
            audio_16k = audio

        wav = torch.from_numpy(audio_16k).unsqueeze(0).unsqueeze(0)
        with torch.no_grad():
            denoised = model(wav)
        result = denoised.squeeze().numpy()

        if sr != 16000:
            result = resample(result, int(len(result) * sr / 16000)).astype(np.float32)
        return result
    except ImportError:
        return denoise_noisereduce(audio, sr, strength=1.0)


def denoise_demucs(audio, sr):
    try:
        import torch
        import torchaudio
        from demucs.pretrained import get_model
        from demucs.apply import apply_model
        from scipy.signal import resample

        model = get_model("htdemucs")
        model.eval()

        wav = torch.from_numpy(audio).float().unsqueeze(0)
        if wav.dim() == 2:
            wav = wav.unsqueeze(0)
        if wav.shape[1] == 1:
            wav = wav.repeat(1, 2, 1)

        if sr != 44100:
            wav = torchaudio.functional.resample(wav.squeeze(0), sr, 44100).unsqueeze(0)

        with torch.no_grad():
            sources = apply_model(model, wav)

        vocals = sources[0, 3].mean(dim=0).numpy()

        if sr != 44100:
            vocals = resample(vocals, int(len(vocals) * sr / 44100)).astype(np.float32)
        return vocals
    except ImportError:
        return denoise_noisereduce(audio, sr, strength=1.0)


# --- GUI ---

class VoiceCleanApp:
    def __init__(self, root, initial_file=None):
        self.root = root
        self.root.title("AI Voice Cleaner")
        self.root.geometry("900x820")

        # Colors
        BG = "#1e1e2e"
        SURFACE = "#313244"
        TEXT = "#cdd6f4"
        SUBTEXT = "#a6adc8"
        BLUE = "#89b4fa"
        GREEN = "#a6e3a1"
        RED = "#f38ba8"
        PEACH = "#fab387"
        MAUVE = "#cba6f7"
        YELLOW = "#f9e2af"

        self.BG = BG
        self.SURFACE = SURFACE
        self.TEXT = TEXT
        self.BLUE = BLUE
        self.GREEN = GREEN
        self.RED = RED
        self.PEACH = PEACH

        root.configure(bg=BG)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT, font=("JetBrains Mono", 10))
        style.configure("Header.TLabel", background=BG, foreground=BLUE, font=("JetBrains Mono", 14, "bold"))
        style.configure("Sub.TLabel", background=BG, foreground=SUBTEXT, font=("JetBrains Mono", 9))
        style.configure("Value.TLabel", background=BG, foreground=PEACH, font=("JetBrains Mono", 10, "bold"))
        style.configure("TButton", background=SURFACE, foreground=TEXT, font=("JetBrains Mono", 10), padding=6)
        style.map("TButton", background=[("active", "#45475a")])
        style.configure("Accent.TButton", background=BLUE, foreground="#1e1e2e", font=("JetBrains Mono", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#74c7ec")])
        style.configure("Play.TButton", background=GREEN, foreground="#1e1e2e", font=("JetBrains Mono", 11, "bold"))
        style.map("Play.TButton", background=[("active", "#94e2d5")])
        style.configure("Stop.TButton", background=RED, foreground="#1e1e2e", font=("JetBrains Mono", 11, "bold"))
        style.map("Stop.TButton", background=[("active", "#eba0ac")])
        style.configure("AI.TButton", background=MAUVE, foreground="#1e1e2e", font=("JetBrains Mono", 10, "bold"))
        style.map("AI.TButton", background=[("active", "#b4befe")])
        style.configure("Save.TButton", background=GREEN, foreground="#1e1e2e", font=("JetBrains Mono", 10, "bold"))
        style.map("Save.TButton", background=[("active", "#94e2d5")])
        style.configure("TLabelframe", background=BG, foreground=MAUVE, font=("JetBrains Mono", 10, "bold"))
        style.configure("TLabelframe.Label", background=BG, foreground=MAUVE, font=("JetBrains Mono", 10, "bold"))
        style.configure("Horizontal.TScale", background=BG, troughcolor=SURFACE)

        # State
        self.original = None
        self.processed = None
        self.sr = None
        self.playing = False
        self.play_pos = 0
        self.stream = None
        self.use_processed = True
        self.ai_denoised = None    # Cache for AI-denoised version
        self.needs_reprocess = True

        # --- Header ---
        hdr = ttk.Frame(root)
        hdr.pack(fill=tk.X, padx=15, pady=(10, 5))
        ttk.Label(hdr, text="AI Voice Cleaner", style="Header.TLabel").pack(side=tk.LEFT)

        # --- File ---
        file_frame = ttk.LabelFrame(root, text="File")
        file_frame.pack(fill=tk.X, padx=15, pady=(0, 5))

        self.path_var = tk.StringVar(value=initial_file or "")
        tk.Entry(file_frame, textvariable=self.path_var, bg=SURFACE, fg=TEXT,
                 font=("JetBrains Mono", 10), insertbackground=TEXT, borderwidth=0
                 ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=5)

        # Start browse at /media/chris if mounted drives exist, else home
        MEDIA_DIR = "/media/chris"
        if not os.path.isdir(MEDIA_DIR) or not os.listdir(MEDIA_DIR):
            MEDIA_DIR = os.path.expanduser("~")

        def browse():
            path = filedialog.askopenfilename(
                initialdir=MEDIA_DIR,
                filetypes=[("Audio", "*.wav *.mp3 *.m4a *.flac *.ogg *.wma *.aac"), ("All", "*.*")])
            if path:
                self.path_var.set(path)
                self.load_file(path)

        ttk.Button(file_frame, text="Browse", command=browse).pack(side=tk.RIGHT, padx=5, pady=5)
        ttk.Button(file_frame, text="Load", style="Accent.TButton",
                   command=lambda: self.load_file(self.path_var.get())).pack(side=tk.RIGHT, padx=2, pady=5)

        # --- Waveform ---
        wave_frame = ttk.LabelFrame(root, text="Waveform")
        wave_frame.pack(fill=tk.X, padx=15, pady=(0, 5))

        self.canvas = tk.Canvas(wave_frame, height=80, bg=SURFACE, highlightthickness=0)
        self.canvas.pack(fill=tk.X, padx=5, pady=5)
        self.canvas.bind("<Button-1>", self.seek)

        # --- Transport ---
        transport = ttk.Frame(root)
        transport.pack(fill=tk.X, padx=15, pady=(0, 5))

        self.play_btn = ttk.Button(transport, text="Play", style="Play.TButton", command=self.toggle_play)
        self.play_btn.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(transport, text="Stop", style="Stop.TButton", command=self.stop).pack(side=tk.LEFT, padx=(0, 10))

        self.ab_var = tk.BooleanVar(value=True)
        self.ab_btn = tk.Checkbutton(transport, text="Processed", variable=self.ab_var,
                                      command=self.toggle_ab,
                                      bg=BG, fg=GREEN, selectcolor=SURFACE,
                                      activebackground=BG, activeforeground=GREEN,
                                      font=("JetBrains Mono", 10, "bold"), indicatoron=True)
        self.ab_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.pos_var = tk.StringVar(value="0:00 / 0:00")
        ttk.Label(transport, textvariable=self.pos_var, style="Value.TLabel").pack(side=tk.LEFT)

        self.info_var = tk.StringVar(value="No file loaded")
        ttk.Label(transport, textvariable=self.info_var, style="Sub.TLabel").pack(side=tk.RIGHT)

        # Volume — goes up to 20x for very faint audio
        self.volume = tk.DoubleVar(value=1.0)
        ttk.Label(transport, text="Vol:", style="Value.TLabel").pack(side=tk.RIGHT, padx=(10, 0))
        vol_scale = ttk.Scale(transport, from_=0, to=20.0, variable=self.volume,
                               orient=tk.HORIZONTAL, length=150)
        vol_scale.pack(side=tk.RIGHT, padx=(0, 5))

        # --- Sliders ---
        sliders_frame = ttk.LabelFrame(root, text="Live Effects (move sliders while playing)")
        sliders_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 5))

        canvas_s = tk.Canvas(sliders_frame, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(sliders_frame, orient=tk.VERTICAL, command=canvas_s.yview)
        inner = ttk.Frame(canvas_s)
        inner.bind("<Configure>", lambda e: canvas_s.configure(scrollregion=canvas_s.bbox("all")))
        canvas_s.create_window((0, 0), window=inner, anchor=tk.NW)
        canvas_s.configure(yscrollcommand=scrollbar.set)
        canvas_s.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        # Mouse wheel scrolling
        def on_mousewheel(event):
            canvas_s.yview_scroll(-1 * (event.delta // 120 or (1 if event.num == 4 else -1)), "units")
        canvas_s.bind_all("<Button-4>", on_mousewheel)
        canvas_s.bind_all("<Button-5>", on_mousewheel)

        # High-Pass
        self.hp_freq = self._slider(inner, "High-Pass Filter (Hz)", 20, 500, 20,
                                     fmt="{:.0f} Hz")
        # Low-Pass
        self.lp_freq = self._slider(inner, "Low-Pass Filter (Hz)", 2000, 16000, 16000,
                                     fmt="{:.0f} Hz")
        # Notch 60Hz
        self.notch_60 = self._slider(inner, "60Hz Hum Removal", 0, 1, 0,
                                      fmt=lambda v: "ON" if v > 0.5 else "OFF")
        # Notch 120Hz
        self.notch_120 = self._slider(inner, "120Hz Hum Removal", 0, 1, 0,
                                       fmt=lambda v: "ON" if v > 0.5 else "OFF")
        # Noise Gate
        self.gate_thresh = self._slider(inner, "Noise Gate Threshold (dB)", -80, 0, -80,
                                         fmt="{:.0f} dB")
        self.gate_reduce = self._slider(inner, "Noise Gate Reduction (dB)", -60, 0, -24,
                                         fmt="{:.0f} dB")
        # Compressor
        self.comp_thresh = self._slider(inner, "Compressor Threshold (dB)", -60, 0, 0,
                                         fmt="{:.0f} dB")
        self.comp_ratio = self._slider(inner, "Compressor Ratio", 1.0, 10.0, 1.0,
                                        fmt="{:.1f}:1")
        # Presence EQ
        self.eq_presence = self._slider(inner, "Presence Boost (2-5kHz, dB)", -6, 12, 0,
                                         fmt="{:.1f} dB")
        # Normalize
        self.norm_peak = self._slider(inner, "Normalize Peak (dB)", -6, 0, -1,
                                       fmt="{:.1f} dB")

        # --- AI Section ---
        ai_frame = ttk.LabelFrame(root, text="AI Denoise (pre-process, then use sliders on top)")
        ai_frame.pack(fill=tk.X, padx=15, pady=(0, 5))

        ai_btns = ttk.Frame(ai_frame)
        ai_btns.pack(fill=tk.X, padx=5, pady=5)

        ttk.Button(ai_btns, text="Spectral Denoise", style="AI.TButton",
                   command=lambda: self.run_ai("spectral")).pack(side=tk.LEFT, padx=2)
        ttk.Button(ai_btns, text="Neural Denoise (DNS64)", style="AI.TButton",
                   command=lambda: self.run_ai("facebook")).pack(side=tk.LEFT, padx=2)
        ttk.Button(ai_btns, text="Source Separation (Demucs)", style="AI.TButton",
                   command=lambda: self.run_ai("demucs")).pack(side=tk.LEFT, padx=2)
        ttk.Button(ai_btns, text="Reset to Original",
                   command=self.reset_ai).pack(side=tk.LEFT, padx=10)

        self.ai_status = tk.StringVar(value="No AI processing applied")
        ttk.Label(ai_frame, textvariable=self.ai_status, style="Sub.TLabel").pack(padx=5, pady=(0, 5), anchor=tk.W)

        # --- Speech Clarity Meter ---
        clarity_frame = ttk.LabelFrame(root, text="Speech Clarity")
        clarity_frame.pack(fill=tk.X, padx=15, pady=(0, 5))

        meter_row = ttk.Frame(clarity_frame)
        meter_row.pack(fill=tk.X, padx=5, pady=5)

        self.clarity_bar = tk.Canvas(meter_row, height=24, bg=SURFACE, highlightthickness=0)
        self.clarity_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))

        self.clarity_var = tk.StringVar(value="Load a file to analyze")
        ttk.Label(meter_row, textvariable=self.clarity_var, style="Value.TLabel", width=35).pack(side=tk.RIGHT)

        # --- Bottom ---
        bot = ttk.Frame(root)
        bot.pack(fill=tk.X, padx=15, pady=(0, 10))

        ttk.Button(bot, text="Save Processed", style="Save.TButton",
                   command=self.save).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(bot, text="Save As...", command=self.save_as).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(bot, text="Transcribe", style="AI.TButton",
                   command=self.open_transcriber).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(bot, text="Reset Everything", style="Stop.TButton",
                   command=self.reset_all).pack(side=tk.RIGHT)
        ttk.Button(bot, text="Reset Sliders", command=self.reset_sliders).pack(side=tk.RIGHT, padx=(0, 5))

        # Reprocess timer
        self._reprocess_after_id = None

        # Auto-load
        if initial_file and os.path.isfile(initial_file):
            self.root.after(100, lambda: self.load_file(initial_file))

    def _slider(self, parent, label, from_, to, default, fmt="{:.1f}"):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, padx=5, pady=2)

        ttk.Label(frame, text=label, width=30).pack(side=tk.LEFT)

        var = tk.DoubleVar(value=default)
        scale = ttk.Scale(frame, from_=from_, to=to, variable=var, orient=tk.HORIZONTAL)
        scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        if callable(fmt):
            val_label = ttk.Label(frame, text=fmt(default), width=8, style="Value.TLabel")
        else:
            val_label = ttk.Label(frame, text=fmt.format(default), width=8, style="Value.TLabel")

        val_label.pack(side=tk.LEFT)

        def on_change(*_):
            v = var.get()
            if callable(fmt):
                val_label.config(text=fmt(v))
            else:
                val_label.config(text=fmt.format(v))
            self.schedule_reprocess()
        var.trace_add("write", on_change)

        return var

    def schedule_reprocess(self):
        if self._reprocess_after_id:
            self.root.after_cancel(self._reprocess_after_id)
        self._reprocess_after_id = self.root.after(200, self._reprocess_bg)

    # --- File Loading ---

    def load_file(self, path):
        path = path.strip()
        if not path or not os.path.isfile(path):
            messagebox.showerror("Error", "File not found.")
            return

        self.stop()
        self.info_var.set("Loading...")
        self.root.update_idletasks()

        def go():
            data, sr = load_audio(path)
            if data is None:
                self.root.after(0, lambda: messagebox.showerror("Error", f"Cannot load: {sr}"))
                return

            self.original = data
            self.sr = sr
            self.ai_denoised = None
            self.ai_status.set("No AI processing applied")
            self.play_pos = 0

            self.root.after(0, lambda: self._on_loaded(path, data, sr))

        threading.Thread(target=go, daemon=True).start()

    def _on_loaded(self, path, data, sr):
        duration = len(data) / sr
        self.info_var.set(f"{os.path.basename(path)}  |  {duration:.1f}s  |  {sr}Hz")
        self.pos_var.set(f"0:00 / {int(duration)//60}:{int(duration)%60:02d}")
        self.draw_waveform()
        self._reprocess_bg()

    # --- Processing ---

    def _reprocess_bg(self):
        """Kick off reprocessing in background thread."""
        if self.original is None:
            return
        if hasattr(self, '_processing') and self._processing:
            # Already processing, reschedule
            self.schedule_reprocess()
            return
        self._processing = True
        threading.Thread(target=self._do_reprocess, daemon=True).start()

    def _do_reprocess(self):
        """Run DSP chain in background thread."""
        try:
            audio = self.ai_denoised.copy() if self.ai_denoised is not None else self.original.copy()
            sr = self.sr

            # Read slider values (thread-safe reads from tk vars)
            hp = self.hp_freq.get()
            lp = self.lp_freq.get()
            n60 = self.notch_60.get()
            n120 = self.notch_120.get()
            gt = self.gate_thresh.get()
            gr = self.gate_reduce.get()
            ct = self.comp_thresh.get()
            cr = self.comp_ratio.get()
            eq = self.eq_presence.get()
            np_ = self.norm_peak.get()

            audio = apply_highpass(audio, sr, hp)
            audio = apply_lowpass(audio, sr, lp)
            if n60 > 0.5:
                audio = apply_notch(audio, sr, 60, 30)
            if n120 > 0.5:
                audio = apply_notch(audio, sr, 120, 30)
            audio = apply_gate(audio, sr, gt, gr)
            audio = apply_compression(audio, sr, ct, cr)
            audio = apply_eq_presence(audio, sr, eq)
            audio = apply_normalize(audio, np_)

            self.processed = audio
            self.root.after(0, self.draw_waveform)
            self.root.after(0, lambda: self.update_clarity(audio, sr))
        finally:
            self._processing = False

    def reprocess(self):
        """Synchronous reprocess for initial load."""
        self._do_reprocess()

    def update_clarity(self, audio, sr):
        """Estimate speech transcribability: SNR + voice band energy + dynamic range."""
        from scipy.signal import butter, sosfilt

        # Use first 30s max for speed
        chunk = audio[:min(len(audio), sr * 30)]

        # Voice band energy (300Hz - 3kHz) vs full band
        voice_lo = min(300, sr / 2 - 1)
        voice_hi = min(3000, sr / 2 - 1)
        if voice_lo < voice_hi:
            sos = butter(3, [voice_lo, voice_hi], btype="bandpass", fs=sr, output="sos")
            voice = sosfilt(sos, chunk).astype(np.float32)
        else:
            voice = chunk

        voice_rms = np.sqrt(np.mean(voice ** 2))
        full_rms = np.sqrt(np.mean(chunk ** 2))

        # Noise floor estimate — vectorized strided frames
        frame_len = int(0.025 * sr)
        n_frames = max(1, (len(chunk) - frame_len) // frame_len)
        trimmed = chunk[:n_frames * frame_len]
        frames = trimmed.reshape(n_frames, frame_len)
        frame_rms = np.sqrt(np.mean(frames ** 2, axis=1))
        frame_rms.sort()
        noise_floor = np.mean(frame_rms[:max(1, len(frame_rms) // 10)])

        # SNR
        if noise_floor > 1e-8:
            snr = 20 * np.log10(voice_rms / noise_floor)
        else:
            snr = 60.0
        snr = max(0, min(60, snr))

        # Voice band ratio
        if full_rms > 1e-8:
            voice_ratio = voice_rms / full_rms
        else:
            voice_ratio = 0

        # Dynamic range (peak to noise)
        peak = np.max(np.abs(chunk))
        if noise_floor > 1e-8:
            dyn_range = 20 * np.log10(peak / noise_floor)
        else:
            dyn_range = 60.0

        # Composite score 0-100
        snr_score = min(snr / 40, 1.0) * 40
        voice_score = min(voice_ratio / 0.6, 1.0) * 30
        dyn_score = min(dyn_range / 50, 1.0) * 30
        score = snr_score + voice_score + dyn_score

        if score >= 75:
            rating = "Excellent — easily transcribable"
            color = "#a6e3a1"
        elif score >= 55:
            rating = "Good — transcribable with minor issues"
            color = "#f9e2af"
        elif score >= 35:
            rating = "Fair — some words may be unclear"
            color = "#fab387"
        else:
            rating = "Poor — difficult to transcribe"
            color = "#f38ba8"

        self.clarity_var.set(f"SNR:{snr:.0f}dB  Score:{score:.0f}/100  {rating}")

        self.clarity_bar.delete("all")
        w = self.clarity_bar.winfo_width()
        if w < 10:
            w = 500
        h = 24
        fill_w = int(score / 100 * w)
        self.clarity_bar.create_rectangle(0, 0, fill_w, h, fill=color, outline="")
        self.clarity_bar.create_rectangle(fill_w, 0, w, h, fill="#313244", outline="")

    def run_ai(self, mode):
        if self.original is None:
            messagebox.showinfo("No file", "Load an audio file first.")
            return

        self.stop()
        self.ai_status.set(f"Running {mode} AI denoise... (this may take a moment)")
        self.root.update_idletasks()

        def go():
            t0 = time.time()
            if mode == "spectral":
                result = denoise_noisereduce(self.original, self.sr, strength=1.0)
                label = "Spectral Denoise"
            elif mode == "facebook":
                result = denoise_facebook(self.original, self.sr)
                label = "Neural Denoise (DNS64)"
            elif mode == "demucs":
                result = denoise_demucs(self.original, self.sr)
                label = "Source Separation (Demucs)"
            else:
                return

            dt = time.time() - t0
            self.ai_denoised = result.astype(np.float32)
            self.root.after(0, lambda: self.ai_status.set(f"{label} applied ({dt:.1f}s) — sliders now process on top of this"))
            self.root.after(0, self._reprocess_bg)

        threading.Thread(target=go, daemon=True).start()

    def reset_ai(self):
        self.ai_denoised = None
        self.ai_status.set("Reset to original — no AI processing")
        self._reprocess_bg()

    def reset_all(self):
        """Reset everything — sliders, AI denoise, volume, back to original."""
        self.stop()
        self.ai_denoised = None
        self.ai_status.set("Reset to original — no AI processing")
        self.volume.set(1.0)
        self.play_pos = 0
        self.reset_sliders()  # triggers schedule_reprocess via slider trace

    def reset_sliders(self):
        self.hp_freq.set(20)
        self.lp_freq.set(16000)
        self.notch_60.set(0)
        self.notch_120.set(0)
        self.gate_thresh.set(-80)
        self.gate_reduce.set(-24)
        self.comp_thresh.set(0)
        self.comp_ratio.set(1.0)
        self.eq_presence.set(0)
        self.norm_peak.set(-1)

    # --- Waveform ---

    def draw_waveform(self):
        self.canvas.delete("all")
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 10:
            w = 870
        if self.original is None:
            return

        mid = h // 2

        # Draw original (dim)
        self._draw_wave(self.original, w, h, mid, "#585b70", 1)

        # Draw processed (bright)
        if self.processed is not None and self.use_processed:
            self._draw_wave(self.processed, w, h, mid, self.BLUE, 1)

        # Playhead
        if self.original is not None and len(self.original) > 0:
            px = int(self.play_pos / len(self.original) * w)
            self.canvas.create_line(px, 0, px, h, fill=self.GREEN, width=2)

    def _draw_wave(self, audio, w, h, mid, color, width):
        step = max(1, len(audio) // w)
        points = []
        for i in range(0, min(len(audio), w * step), step):
            x = i // step
            chunk = audio[i:i + step]
            if len(chunk) == 0:
                continue
            val = np.max(np.abs(chunk))
            y_top = mid - int(val * mid * 0.9)
            y_bot = mid + int(val * mid * 0.9)
            self.canvas.create_line(x, y_top, x, y_bot, fill=color, width=width)

    def seek(self, event):
        if self.original is None:
            return
        w = self.canvas.winfo_width()
        frac = event.x / w
        self.play_pos = int(frac * len(self.original))
        self.draw_waveform()

    # --- Playback ---

    def toggle_play(self):
        if self.playing:
            self.pause()
        else:
            self.play()

    def play(self):
        if self.original is None:
            return
        if self.playing:
            return

        self.playing = True
        self.play_btn.config(text="Pause")

        audio = self.processed if (self.use_processed and self.processed is not None) else self.original

        # Reset position if at end
        if self.play_pos >= len(audio) - 1:
            self.play_pos = 0

        pos = [self.play_pos]
        current_audio = [audio]

        def callback(outdata, frames, time_info, status):
            start = pos[0]
            a = current_audio[0]
            vol = self.volume.get()
            end = min(start + frames, len(a))
            n = end - start

            if n <= 0:
                outdata[:] = 0
                self.root.after(0, self.stop)
                return

            outdata[:n, 0] = a[start:end] * vol
            if n < frames:
                outdata[n:] = 0
                self.root.after(0, self.stop)

            pos[0] = end

        self.stream = sd.OutputStream(
            samplerate=self.sr, channels=1, callback=callback,
            blocksize=2048, dtype="float32"
        )
        self.stream.start()

        # UI update thread
        def update_ui():
            while self.playing:
                self.play_pos = pos[0]
                total = len(self.original)
                cur_s = self.play_pos / self.sr
                tot_s = total / self.sr
                self.pos_var.set(f"{int(cur_s)//60}:{int(cur_s)%60:02d} / {int(tot_s)//60}:{int(tot_s)%60:02d}")

                # Update what audio the callback uses (for live slider changes)
                a = self.processed if (self.use_processed and self.processed is not None) else self.original
                current_audio[0] = a

                self.draw_waveform()
                time.sleep(0.05)

        threading.Thread(target=update_ui, daemon=True).start()

    def pause(self):
        self.playing = False
        self.play_btn.config(text="Play")
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

    def stop(self):
        was_playing = self.playing
        self.playing = False
        self.play_btn.config(text="Play")
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        if was_playing:
            self.play_pos = 0
            self.draw_waveform()

    def toggle_ab(self):
        self.use_processed = self.ab_var.get()
        self.draw_waveform()

    # --- Save ---

    def save(self):
        if self.processed is None:
            messagebox.showinfo("Nothing to save", "Load and process a file first.")
            return
        path = self.path_var.get().strip()
        base = os.path.splitext(os.path.basename(path))[0] if path else "cleaned"
        out_dir = os.path.expanduser("~/Desktop/Claude Output/Voice Clean - Output")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{base}_cleaned.wav")
        save_audio(out_path, self.processed, self.sr)
        messagebox.showinfo("Saved", f"Saved to:\n{out_path}")

    def open_transcriber(self):
        """Save processed audio and launch the transcriber with it."""
        if self.processed is None:
            messagebox.showinfo("Nothing to transcribe", "Load and process a file first.")
            return
        # Save processed to temp file
        path = self.path_var.get().strip()
        base = os.path.splitext(os.path.basename(path))[0] if path else "cleaned"
        out_dir = os.path.expanduser("~/Desktop/Claude Output/Voice Clean - Output")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{base}_cleaned.wav")
        save_audio(out_path, self.processed, self.sr)

        # Launch transcriber
        script_dir = os.path.dirname(os.path.abspath(__file__))
        transcriber = os.path.join(script_dir, "transcribe.py")
        if os.path.isfile(transcriber):
            import subprocess
            subprocess.Popen([transcriber, out_path])
        else:
            messagebox.showerror("Not found", f"Transcriber not found at:\n{transcriber}")

    def save_as(self):
        if self.processed is None:
            messagebox.showinfo("Nothing to save", "Load and process a file first.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".wav",
            filetypes=[("WAV", "*.wav")],
            initialdir=os.path.expanduser("~/Desktop/Claude Output/Voice Clean - Output"),
        )
        if path:
            save_audio(path, self.processed, self.sr)
            messagebox.showinfo("Saved", f"Saved to:\n{path}")


def main():
    initial = sys.argv[1] if len(sys.argv) > 1 else None
    root = tk.Tk()
    app = VoiceCleanApp(root, initial)
    root.mainloop()


if __name__ == "__main__":
    main()
