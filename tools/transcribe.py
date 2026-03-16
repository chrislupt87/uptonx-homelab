#!/home/chris/uptonx-homelab/tools/venv-voice-clean/bin/python3
"""
Speech Transcriber — Whisper-based English transcription at 3 quality levels.

Usage:
  ./transcribe.py                          # GUI mode
  ./transcribe.py cleaned_audio.wav        # GUI with file pre-loaded
  ./transcribe.py audio.wav --level high   # CLI mode
"""

import sys
import os
import time
import threading
import argparse
import warnings
warnings.filterwarnings("ignore")

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# Model sizes mapped to levels
LEVELS = {
    "low": {
        "model": "base",
        "label": "Low (Base)",
        "desc": "Fast, basic accuracy — good for clear speech",
        "icon": "~2 min/min of audio",
    },
    "medium": {
        "model": "small",
        "label": "Medium (Small)",
        "desc": "Balanced speed/accuracy — handles moderate noise",
        "icon": "~5 min/min of audio",
    },
    "high": {
        "model": "large-v3",
        "label": "High (Large-v3)",
        "desc": "Best accuracy — handles noise, accents, faint speech",
        "icon": "~15 min/min of audio (CPU)",
    },
}


def transcribe_audio(path, level="medium", progress_cb=None):
    """Transcribe audio file using Whisper. Returns dict with text, segments, etc."""
    import whisper

    info = LEVELS[level]
    model_name = info["model"]

    if progress_cb:
        progress_cb(f"Loading Whisper model: {model_name}...")

    model = whisper.load_model(model_name)

    if progress_cb:
        progress_cb(f"Transcribing with {info['label']}...")

    result = model.transcribe(
        path,
        language="en",
        task="transcribe",
        verbose=False,
        fp16=False,
    )

    return result


def format_timestamp(seconds):
    """Format seconds as HH:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def format_transcript(result, include_timestamps=True):
    """Format Whisper result into readable text."""
    if not include_timestamps:
        return result["text"].strip()

    lines = []
    for seg in result.get("segments", []):
        ts = format_timestamp(seg["start"])
        text = seg["text"].strip()
        if text:
            lines.append(f"[{ts}]  {text}")

    return "\n".join(lines)


# --- GUI ---

class TranscribeApp:
    def __init__(self, root, initial_file=None):
        self.root = root
        self.root.title("Speech Transcriber")
        self.root.geometry("850x750")

        BG = "#1e1e2e"
        SURFACE = "#313244"
        TEXT = "#cdd6f4"
        SUBTEXT = "#a6adc8"
        BLUE = "#89b4fa"
        GREEN = "#a6e3a1"
        RED = "#f38ba8"
        MAUVE = "#cba6f7"
        PEACH = "#fab387"
        YELLOW = "#f9e2af"

        self.BG = BG
        self.SURFACE = SURFACE
        self.TEXT = TEXT

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
        style.configure("Low.TButton", background=GREEN, foreground="#1e1e2e", font=("JetBrains Mono", 10, "bold"))
        style.map("Low.TButton", background=[("active", "#94e2d5")])
        style.configure("Med.TButton", background=YELLOW, foreground="#1e1e2e", font=("JetBrains Mono", 10, "bold"))
        style.map("Med.TButton", background=[("active", "#f9e2af")])
        style.configure("High.TButton", background=PEACH, foreground="#1e1e2e", font=("JetBrains Mono", 10, "bold"))
        style.map("High.TButton", background=[("active", "#fab387")])
        style.configure("Save.TButton", background=GREEN, foreground="#1e1e2e", font=("JetBrains Mono", 10, "bold"))
        style.map("Save.TButton", background=[("active", "#94e2d5")])
        style.configure("TLabelframe", background=BG, foreground=MAUVE, font=("JetBrains Mono", 10, "bold"))
        style.configure("TLabelframe.Label", background=BG, foreground=MAUVE, font=("JetBrains Mono", 10, "bold"))

        self.result = None
        self.transcribing = False

        # --- Header ---
        ttk.Label(root, text="Speech Transcriber", style="Header.TLabel").pack(padx=15, pady=(10, 2), anchor=tk.W)
        ttk.Label(root, text="Whisper AI — English transcription at 3 quality levels",
                  style="Sub.TLabel").pack(padx=15, anchor=tk.W)

        # --- File ---
        file_frame = ttk.LabelFrame(root, text="Audio File")
        file_frame.pack(fill=tk.X, padx=15, pady=(10, 5))

        self.path_var = tk.StringVar(value=initial_file or "")
        tk.Entry(file_frame, textvariable=self.path_var, bg=SURFACE, fg=TEXT,
                 font=("JetBrains Mono", 10), insertbackground=TEXT, borderwidth=0
                 ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=5)

        def browse():
            # Start at /media/chris for Zoom recorders
            out_dir = "/media/chris"
            if not os.path.isdir(out_dir):
                out_dir = os.path.expanduser("~/Desktop/Claude Output/Voice Clean - Output")
            if not os.path.isdir(out_dir):
                out_dir = os.path.expanduser("~")
            path = filedialog.askopenfilename(
                initialdir=out_dir,
                filetypes=[("Audio", "*.wav *.mp3 *.m4a *.flac *.ogg *.wma *.aac"), ("All", "*.*")])
            if path:
                self.path_var.set(path)

        ttk.Button(file_frame, text="Browse", command=browse).pack(side=tk.RIGHT, padx=5, pady=5)
        ttk.Button(file_frame, text="Analyze", style="Accent.TButton",
                   command=self.analyze_file).pack(side=tk.RIGHT, padx=2, pady=5)

        # --- Speech Analysis ---
        analysis_frame = ttk.LabelFrame(root, text="Speech Analysis (analyze before transcribing)")
        analysis_frame.pack(fill=tk.X, padx=15, pady=(0, 5))

        self.analysis_progress = ttk.Progressbar(analysis_frame, mode="determinate", maximum=100)
        self.analysis_progress.pack(fill=tk.X, padx=5, pady=(5, 2))

        self.analysis_bar = tk.Canvas(analysis_frame, height=24, bg=SURFACE, highlightthickness=0)
        self.analysis_bar.pack(fill=tk.X, padx=5, pady=(0, 2))

        self.analysis_var = tk.StringVar(value="Click Analyze to check speech quality")
        ttk.Label(analysis_frame, textvariable=self.analysis_var, style="Value.TLabel").pack(
            padx=5, pady=(0, 2), anchor=tk.W)

        self.analysis_detail = tk.StringVar(value="")
        ttk.Label(analysis_frame, textvariable=self.analysis_detail, style="Sub.TLabel").pack(
            padx=5, pady=(0, 5), anchor=tk.W)

        # --- Quality Level ---
        level_frame = ttk.LabelFrame(root, text="Transcription Quality")
        level_frame.pack(fill=tk.X, padx=15, pady=(0, 5))

        btn_row = ttk.Frame(level_frame)
        btn_row.pack(fill=tk.X, padx=5, pady=5)

        self.level_var = tk.StringVar(value="medium")

        for key, info, btn_style in [("low", LEVELS["low"], "Low.TButton"),
                                      ("medium", LEVELS["medium"], "Med.TButton"),
                                      ("high", LEVELS["high"], "High.TButton")]:
            col = ttk.Frame(btn_row)
            col.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=3)

            rb = tk.Radiobutton(col, text=info["label"], variable=self.level_var, value=key,
                                bg=BG, fg=TEXT, selectcolor=SURFACE,
                                activebackground=BG, activeforeground=TEXT,
                                font=("JetBrains Mono", 11, "bold"), anchor=tk.W)
            rb.pack(anchor=tk.W)
            ttk.Label(col, text=info["desc"], style="Sub.TLabel", wraplength=250).pack(anchor=tk.W, padx=18)
            ttk.Label(col, text=info["icon"], style="Sub.TLabel").pack(anchor=tk.W, padx=18)

        # Transcribe button
        action_row = ttk.Frame(level_frame)
        action_row.pack(fill=tk.X, padx=5, pady=(5, 8))

        self.transcribe_btn = ttk.Button(action_row, text="Transcribe", style="Accent.TButton",
                                          command=self.start_transcribe)
        self.transcribe_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(action_row, textvariable=self.status_var, style="Value.TLabel").pack(side=tk.LEFT)

        # Progress
        self.progress = ttk.Progressbar(level_frame, mode="indeterminate")
        self.progress.pack(fill=tk.X, padx=5, pady=(0, 5))

        # --- Options ---
        opt_row = ttk.Frame(root)
        opt_row.pack(fill=tk.X, padx=15, pady=(0, 5))

        self.timestamps_var = tk.BooleanVar(value=True)
        tk.Checkbutton(opt_row, text="Include timestamps", variable=self.timestamps_var,
                       command=self.reformat,
                       bg=BG, fg=TEXT, selectcolor=SURFACE,
                       activebackground=BG, activeforeground=TEXT,
                       font=("JetBrains Mono", 10)).pack(side=tk.LEFT)

        # --- Transcript Output ---
        text_frame = ttk.LabelFrame(root, text="Transcript")
        text_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 5))

        self.text_box = scrolledtext.ScrolledText(
            text_frame, bg=SURFACE, fg=TEXT,
            font=("JetBrains Mono", 11), insertbackground=TEXT,
            borderwidth=0, wrap=tk.WORD, spacing1=2, spacing3=2
        )
        self.text_box.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # --- Bottom ---
        bot = ttk.Frame(root)
        bot.pack(fill=tk.X, padx=15, pady=(0, 10))

        ttk.Button(bot, text="Save Transcript", style="Save.TButton",
                   command=self.save).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(bot, text="Save As...", command=self.save_as).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(bot, text="Copy All", command=self.copy_all).pack(side=tk.LEFT, padx=(0, 5))

        # Word count
        self.wc_var = tk.StringVar(value="")
        ttk.Label(bot, textvariable=self.wc_var, style="Sub.TLabel").pack(side=tk.RIGHT)

        # Auto-load if file provided
        if initial_file and os.path.isfile(initial_file):
            self.path_var.set(initial_file)

    def analyze_file(self):
        path = self.path_var.get().strip()
        if not path or not os.path.isfile(path):
            messagebox.showerror("Error", "Select a valid audio file first.")
            return
        if self.transcribing:
            return

        self.analysis_var.set("Analyzing...")
        self.analysis_detail.set("")
        self.analysis_bar.delete("all")
        self.analysis_progress["value"] = 0

        def run_analysis():
            try:
                import numpy as np
                import soundfile as sf
                from scipy.signal import butter, sosfilt

                self.root.after(0, lambda: self.analysis_progress.configure(value=10))

                # Load audio — cap at 60s for speed
                info = sf.info(path)
                max_frames = int(min(info.frames, info.samplerate * 60))
                data, sr = sf.read(path, dtype="float32", frames=max_frames)
                if data.ndim > 1:
                    data = data.mean(axis=1)

                duration = info.frames / info.samplerate

                # Normalize
                peak = np.max(np.abs(data))
                if peak > 0:
                    data = data / peak

                self.root.after(0, lambda: self.analysis_progress.configure(value=25))

                # 1. SNR estimation — vectorized strided frames
                frame_len = int(0.025 * sr)  # 25ms
                hop = int(0.010 * sr)  # 10ms
                n_frames = max(1, (len(data) - frame_len) // hop)
                # Strided view — no Python loop
                strides = data.strides[0]
                frames = np.lib.stride_tricks.as_strided(
                    data, shape=(n_frames, frame_len),
                    strides=(hop * strides, strides))
                frame_rms = np.sqrt(np.mean(frames ** 2, axis=1))
                frame_db = 20 * np.log10(frame_rms + 1e-10)

                sorted_db = np.sort(frame_db)
                noise_floor = np.mean(sorted_db[:max(1, int(n_frames * 0.2))])
                signal_level = np.mean(sorted_db[max(0, int(n_frames * 0.7)):])
                snr = signal_level - noise_floor

                self.root.after(0, lambda: self.analysis_progress.configure(value=50))

                # 2. Voice band energy ratio (300Hz-3kHz vs total)
                nyq = sr / 2
                lo = min(300, nyq * 0.9)
                hi = min(3000, nyq * 0.9)
                if hi > lo:
                    sos_bp = butter(4, [lo, hi], btype="bandpass", fs=sr, output="sos")
                    voice_band = sosfilt(sos_bp, data)
                    voice_energy = np.sum(voice_band ** 2)
                else:
                    voice_energy = np.sum(data ** 2) * 0.5
                total_energy = np.sum(data ** 2) + 1e-10
                voice_ratio = voice_energy / total_energy

                self.root.after(0, lambda: self.analysis_progress.configure(value=70))

                # 3. Speech activity detection — frames above noise floor + 6dB
                speech_threshold = noise_floor + 6
                speech_pct = np.sum(frame_db > speech_threshold) / max(1, n_frames) * 100

                self.root.after(0, lambda: self.analysis_progress.configure(value=85))

                # 4. Spectral flatness (first 10s only)
                chunk = data[:min(len(data), sr * 10)]
                fft_data = np.abs(np.fft.rfft(chunk))
                fft_data = fft_data[1:]
                geo_mean = np.exp(np.mean(np.log(fft_data + 1e-10)))
                arith_mean = np.mean(fft_data) + 1e-10
                spectral_flatness = geo_mean / arith_mean

                self.root.after(0, lambda: self.analysis_progress.configure(value=95))

                # Composite score (0-100)
                # SNR: 0-40dB mapped to 0-35 points
                snr_score = min(35, max(0, snr / 40 * 35))
                # Voice ratio: 0-0.8 mapped to 0-25 points
                voice_score = min(25, max(0, voice_ratio / 0.8 * 25))
                # Speech activity: 0-100% mapped to 0-25 points
                activity_score = min(25, max(0, speech_pct / 100 * 25))
                # Spectral flatness: lower = more tonal = better for speech (0-15 points)
                flat_score = min(15, max(0, (1 - spectral_flatness) * 15))

                score = snr_score + voice_score + activity_score + flat_score
                score = max(0, min(100, score))

                # Recommendation
                if score >= 75:
                    verdict = "Excellent — high likelihood of accurate transcription"
                    rec_level = "low"
                elif score >= 55:
                    verdict = "Good — should transcribe well, medium quality recommended"
                    rec_level = "medium"
                elif score >= 35:
                    verdict = "Fair — noisy or faint, use high quality for best results"
                    rec_level = "high"
                elif score >= 20:
                    verdict = "Poor — difficult audio, use high quality, expect errors"
                    rec_level = "high"
                else:
                    verdict = "Very poor — unlikely to produce useful transcription"
                    rec_level = "high"

                detail = (
                    f"SNR: {snr:.1f}dB  |  Voice band: {voice_ratio * 100:.0f}%  |  "
                    f"Speech activity: {speech_pct:.0f}%  |  Duration: {duration:.1f}s"
                )

                self.root.after(0, lambda: self._show_analysis(score, verdict, detail, rec_level))

            except Exception as e:
                self.root.after(0, lambda: self._show_analysis_error(str(e)))

        threading.Thread(target=run_analysis, daemon=True).start()

    def _show_analysis(self, score, verdict, detail, rec_level):
        self.analysis_progress["value"] = 100

        # Draw colored score bar
        self.analysis_bar.delete("all")
        self.analysis_bar.update_idletasks()
        w = self.analysis_bar.winfo_width()
        h = 24
        bar_w = int(w * score / 100)

        # Color gradient: red → yellow → green
        if score < 35:
            color = "#f38ba8"  # red
        elif score < 55:
            color = "#fab387"  # peach
        elif score < 75:
            color = "#f9e2af"  # yellow
        else:
            color = "#a6e3a1"  # green

        self.analysis_bar.create_rectangle(0, 0, bar_w, h, fill=color, outline="")
        self.analysis_bar.create_text(w // 2, h // 2, text=f"{score:.0f}/100",
                                       fill="#1e1e2e", font=("JetBrains Mono", 11, "bold"))

        self.analysis_var.set(f"Score: {score:.0f}/100 — {verdict}")
        self.analysis_detail.set(detail)

        # Auto-select recommended quality level
        self.level_var.set(rec_level)

    def _show_analysis_error(self, error):
        self.analysis_progress["value"] = 0
        self.analysis_var.set(f"Analysis error: {error}")
        self.analysis_detail.set("")

    def start_transcribe(self):
        path = self.path_var.get().strip()
        if not path or not os.path.isfile(path):
            messagebox.showerror("Error", "Select a valid audio file first.")
            return
        if self.transcribing:
            return

        level = self.level_var.get()
        self.transcribing = True
        self.transcribe_btn.config(state="disabled")
        self.progress.start()
        self.text_box.delete("1.0", tk.END)
        self.text_box.insert(tk.END, "Transcribing... please wait.\n")

        def go():
            try:
                t0 = time.time()
                result = transcribe_audio(
                    path, level,
                    progress_cb=lambda msg: self.root.after(0, lambda m=msg: self.status_var.set(m))
                )
                dt = time.time() - t0
                self.result = result

                text = format_transcript(result, self.timestamps_var.get())
                words = len(result["text"].split())
                segments = len(result.get("segments", []))

                self.root.after(0, lambda: self._show_result(text, dt, words, segments))
            except Exception as e:
                self.root.after(0, lambda: self._show_error(str(e)))

        threading.Thread(target=go, daemon=True).start()

    def _show_result(self, text, dt, words, segments):
        self.transcribing = False
        self.transcribe_btn.config(state="normal")
        self.progress.stop()
        self.status_var.set(f"Done in {dt:.1f}s")
        self.wc_var.set(f"{words} words  |  {segments} segments")

        self.text_box.delete("1.0", tk.END)
        self.text_box.insert(tk.END, text)

    def _show_error(self, error):
        self.transcribing = False
        self.transcribe_btn.config(state="normal")
        self.progress.stop()
        self.status_var.set("Error")
        self.text_box.delete("1.0", tk.END)
        self.text_box.insert(tk.END, f"Error: {error}")

    def reformat(self):
        if self.result is None:
            return
        text = format_transcript(self.result, self.timestamps_var.get())
        self.text_box.delete("1.0", tk.END)
        self.text_box.insert(tk.END, text)

    def save(self):
        if self.result is None:
            messagebox.showinfo("Nothing to save", "Transcribe a file first.")
            return
        path = self.path_var.get().strip()
        base = os.path.splitext(os.path.basename(path))[0] if path else "transcript"
        out_dir = os.path.expanduser("~/Desktop/Claude Output/Voice Clean - Output")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{base}_transcript.txt")

        text = self.text_box.get("1.0", tk.END).strip()
        with open(out_path, "w") as f:
            f.write(text + "\n")
        messagebox.showinfo("Saved", f"Saved to:\n{out_path}")

    def save_as(self):
        if self.result is None:
            messagebox.showinfo("Nothing to save", "Transcribe a file first.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text", "*.txt"), ("All", "*.*")],
            initialdir=os.path.expanduser("~/Desktop/Claude Output/Voice Clean - Output"),
        )
        if path:
            text = self.text_box.get("1.0", tk.END).strip()
            with open(path, "w") as f:
                f.write(text + "\n")
            messagebox.showinfo("Saved", f"Saved to:\n{path}")

    def copy_all(self):
        text = self.text_box.get("1.0", tk.END).strip()
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status_var.set("Copied to clipboard")


# --- CLI Mode ---

def cli_transcribe(path, level, output=None):
    if not os.path.isfile(path):
        print(f"Error: File not found: {path}")
        sys.exit(1)

    info = LEVELS[level]
    print(f"Speech Transcriber")
    print(f"  File:  {path}")
    print(f"  Level: {info['label']}")
    print()

    t0 = time.time()
    result = transcribe_audio(path, level, progress_cb=lambda msg: print(f"  {msg}"))
    dt = time.time() - t0

    text = format_transcript(result, include_timestamps=True)
    words = len(result["text"].split())

    print(f"\n{'='*60}")
    print(text)
    print(f"{'='*60}")
    print(f"\n{words} words  |  {dt:.1f}s")

    if output:
        out_path = output
    else:
        base = os.path.splitext(os.path.basename(path))[0]
        out_dir = os.path.expanduser("~/Desktop/Claude Output/Voice Clean - Output")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{base}_transcript.txt")

    with open(out_path, "w") as f:
        f.write(text + "\n")
    print(f"Saved: {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Speech Transcriber — Whisper AI English transcription")
    parser.add_argument("input", nargs="?", help="Audio file to transcribe")
    parser.add_argument("-l", "--level", default="medium", choices=["low", "medium", "high"])
    parser.add_argument("-o", "--output", help="Output text file path")
    parser.add_argument("--cli", action="store_true", help="CLI mode (no GUI)")

    args = parser.parse_args()

    if args.cli and args.input:
        cli_transcribe(args.input, args.level, args.output)
    else:
        root = tk.Tk()
        app = TranscribeApp(root, args.input)
        root.mainloop()


if __name__ == "__main__":
    main()
