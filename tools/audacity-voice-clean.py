#!/home/chris/uptonx-homelab/tools/venv-voice-clean/bin/python3
"""
Audacity Voice Cleaning — GUI with noise reduction & voice isolation.

Prerequisites:
  1. Open Audacity
  2. Enable mod-script-pipe:
     Edit -> Preferences -> Modules -> mod-script-pipe = Enabled
  3. Restart Audacity
  4. Open your audio file in Audacity
  5. Run: ./audacity-voice-clean.py
"""

import sys
import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext

# --- Audacity Pipe Interface ---

if sys.platform == "linux":
    TONAME = "/tmp/audacity_script_pipe.to." + str(os.getuid())
    FROMNAME = "/tmp/audacity_script_pipe.from." + str(os.getuid())
elif sys.platform == "darwin":
    TONAME = "/tmp/audacity_script_pipe.to." + str(os.getuid())
    FROMNAME = "/tmp/audacity_script_pipe.from." + str(os.getuid())
elif sys.platform == "win32":
    TONAME = r"\\.\pipe\ToSrvPipe"
    FROMNAME = r"\\.\pipe\FromSrvPipe"
else:
    TONAME = FROMNAME = None

TOFILE = None
FROMFILE = None
CONNECTED = False


def connect():
    global TOFILE, FROMFILE, CONNECTED
    try:
        TOFILE = open(TONAME, "w")
        FROMFILE = open(FROMNAME, "r")
        CONNECTED = True
        return True
    except (FileNotFoundError, TypeError):
        CONNECTED = False
        return False


def send_command(cmd):
    TOFILE.write(cmd + "\n")
    TOFILE.flush()
    response = ""
    while True:
        line = FROMFILE.readline()
        response += line
        if line == "\n":
            break
    return response.strip()


def do_command(cmd):
    result = send_command(cmd)
    failed = "BatchCommand finished: Failed!" in result
    return not failed, result


# --- Effect Wrappers ---

def select_all():
    do_command("SelectAll:")


def fx_noise_reduction_profile(reduction_db, sensitivity, freq_smoothing):
    return do_command(
        f'NoiseReduction: Use_Preset="<p>'
        f'<param index="0" name="0" value="{reduction_db}"/>'
        f'<param index="1" name="1" value="{sensitivity}"/>'
        f'<param index="2" name="2" value="{freq_smoothing}"/>'
        f'<param index="3" name="3" value="3"/>'
        f'<param index="4" name="4" value="0"/>'
        f'<param index="5" name="5" value="0"/>'
        f'</p>"'
    )


def fx_noise_reduction_apply(reduction_db, sensitivity, freq_smoothing):
    return do_command(
        f'NoiseReduction: Use_Preset="<p>'
        f'<param index="0" name="0" value="{reduction_db}"/>'
        f'<param index="1" name="1" value="{sensitivity}"/>'
        f'<param index="2" name="2" value="{freq_smoothing}"/>'
        f'<param index="3" name="3" value="3"/>'
        f'<param index="4" name="4" value="1"/>'
        f'<param index="5" name="5" value="0"/>'
        f'</p>"'
    )


def fx_noise_gate(threshold, attack, hold, release, reduction):
    select_all()
    return do_command(
        f"NoiseGate: gate-freq=0 level-reduction={reduction} "
        f"threshold={threshold} attack={attack} hold={hold} "
        f"decay={release} mode=0"
    )


def fx_highpass(freq, rolloff=2):
    select_all()
    return do_command(f"HighPassFilter: frequency={freq} rolloff={rolloff}")


def fx_lowpass(freq, rolloff=1):
    select_all()
    return do_command(f"LowPassFilter: frequency={freq} rolloff={rolloff}")


def fx_notch(freq, q):
    select_all()
    return do_command(f"NotchFilter: frequency={freq} q={q}")


def fx_compressor(threshold, noise_floor, ratio, attack, release):
    select_all()
    return do_command(
        f"Compressor: Threshold={threshold} NoiseFloor={noise_floor} "
        f'Ratio={ratio} AttackTime={attack} ReleaseTime={release} '
        f"Normalize=yes"
    )


def fx_normalize(peak):
    select_all()
    return do_command(
        f"Normalize: PeakLevel={peak} ApplyGain=1 RemoveDcOffset=1"
    )


def fx_voice_eq():
    select_all()
    return do_command(
        "FilterCurve: FilterLength=8191 InterpolateMeth=B-spline "
        "InterpolateLinear=0 "
        'CurveName="" '
        "f0=20 f1=100 f2=250 f3=500 f4=1000 f5=3000 f6=5000 f7=8000 f8=16000 "
        "v0=0 v1=0 v2=-3 v3=0 v4=0 v5=3 v6=2 v7=0 v8=-2"
    )


def fx_truncate_silence(threshold, min_dur, trunc_to):
    select_all()
    return do_command(
        f"TruncateSilence: Threshold={threshold} Action=1 "
        f"Minimum={min_dur} Truncate={trunc_to} Compress=50"
    )


def fx_amplify():
    select_all()
    return do_command("Amplify:")


def fx_undo():
    return do_command("Undo:")


# --- Preset Definitions ---

PRESETS = {
    "Light Clean": {
        "desc": "Gentle noise reduction + high-pass + normalize\nGood for podcasts, interviews, clean recordings",
        "steps": [
            ("Noise Reduction (6dB)", "nr", {"reduction_db": 6, "sensitivity": 4.0, "freq_smoothing": 3}),
            ("High-Pass 80Hz", "hp", {"freq": 80}),
            ("Normalize -1dB", "norm", {"peak": -1.0}),
        ]
    },
    "Standard Voice": {
        "desc": "Noise reduction + gate + EQ + compression + normalize\nAll-purpose voice cleaning",
        "steps": [
            ("Noise Reduction (12dB)", "nr", {"reduction_db": 12, "sensitivity": 6.0, "freq_smoothing": 3}),
            ("Noise Gate (-40dB)", "ng", {"threshold": -40, "attack": 10, "hold": 50, "release": 100, "reduction": -24}),
            ("High-Pass 80Hz", "hp", {"freq": 80}),
            ("Voice EQ", "eq", {}),
            ("Compression (3:1)", "comp", {"threshold": -12, "noise_floor": -40, "ratio": "3:1", "attack": 0.2, "release": 1.0}),
            ("Normalize -1dB", "norm", {"peak": -1.0}),
        ]
    },
    "Heavy Clean": {
        "desc": "Aggressive NR + gate + band-pass + hum removal\nFor noisy environments, phone recordings",
        "steps": [
            ("Noise Reduction (18dB)", "nr", {"reduction_db": 18, "sensitivity": 8.0, "freq_smoothing": 6}),
            ("Noise Gate (-35dB)", "ng", {"threshold": -35, "attack": 5, "hold": 30, "release": 50, "reduction": -30}),
            ("High-Pass 100Hz", "hp", {"freq": 100}),
            ("Low-Pass 7kHz", "lp", {"freq": 7000}),
            ("Notch 60Hz hum", "notch", {"freq": 60, "q": 10}),
            ("Compression (4:1)", "comp", {"threshold": -15, "noise_floor": -40, "ratio": "4:1", "attack": 0.2, "release": 1.0}),
            ("Normalize -1dB", "norm", {"peak": -1.0}),
        ]
    },
    "Forensic Isolation": {
        "desc": "Maximum voice isolation for difficult recordings\nHeavy filtering, multi-notch, tight band-pass",
        "steps": [
            ("Noise Reduction (24dB)", "nr", {"reduction_db": 24, "sensitivity": 10.0, "freq_smoothing": 6}),
            ("Noise Gate (-30dB)", "ng", {"threshold": -30, "attack": 5, "hold": 20, "release": 30, "reduction": -40}),
            ("High-Pass 150Hz", "hp", {"freq": 150}),
            ("Low-Pass 6kHz", "lp", {"freq": 6000}),
            ("Notch 60Hz", "notch", {"freq": 60, "q": 15}),
            ("Notch 120Hz", "notch", {"freq": 120, "q": 15}),
            ("Voice EQ", "eq", {}),
            ("Compression (5:1)", "comp", {"threshold": -18, "noise_floor": -40, "ratio": "5:1", "attack": 0.1, "release": 0.5}),
            ("Normalize -1dB", "norm", {"peak": -1.0}),
        ]
    },
}


# --- GUI Application ---

class VoiceCleanApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Audacity Voice Cleaner")
        self.root.geometry("820x700")
        self.root.configure(bg="#1e1e2e")

        style = ttk.Style()
        style.theme_use("clam")

        # Dark theme colors (Catppuccin Mocha inspired)
        BG = "#1e1e2e"
        SURFACE = "#313244"
        TEXT = "#cdd6f4"
        SUBTEXT = "#a6adc8"
        BLUE = "#89b4fa"
        GREEN = "#a6e3a1"
        RED = "#f38ba8"
        PEACH = "#fab387"
        MAUVE = "#cba6f7"

        style.configure("TFrame", background=BG)
        style.configure("Surface.TFrame", background=SURFACE)
        style.configure("TLabel", background=BG, foreground=TEXT, font=("JetBrains Mono", 10))
        style.configure("Header.TLabel", background=BG, foreground=BLUE, font=("JetBrains Mono", 14, "bold"))
        style.configure("Sub.TLabel", background=BG, foreground=SUBTEXT, font=("JetBrains Mono", 9))
        style.configure("Surface.TLabel", background=SURFACE, foreground=TEXT, font=("JetBrains Mono", 10))
        style.configure("TButton", background=SURFACE, foreground=TEXT, font=("JetBrains Mono", 10),
                         borderwidth=0, padding=8)
        style.map("TButton", background=[("active", "#45475a")])
        style.configure("Accent.TButton", background=BLUE, foreground="#1e1e2e",
                         font=("JetBrains Mono", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#74c7ec")])
        style.configure("Danger.TButton", background=RED, foreground="#1e1e2e",
                         font=("JetBrains Mono", 10))
        style.map("Danger.TButton", background=[("active", "#eba0ac")])
        style.configure("Green.TButton", background=GREEN, foreground="#1e1e2e",
                         font=("JetBrains Mono", 10, "bold"))
        style.map("Green.TButton", background=[("active", "#94e2d5")])
        style.configure("TLabelframe", background=BG, foreground=MAUVE,
                         font=("JetBrains Mono", 10, "bold"))
        style.configure("TLabelframe.Label", background=BG, foreground=MAUVE,
                         font=("JetBrains Mono", 10, "bold"))
        style.configure("TNotebook", background=BG)
        style.configure("TNotebook.Tab", background=SURFACE, foreground=TEXT,
                         font=("JetBrains Mono", 10), padding=[12, 4])
        style.map("TNotebook.Tab", background=[("selected", BLUE)],
                  foreground=[("selected", "#1e1e2e")])
        style.configure("Horizontal.TScale", background=BG, troughcolor=SURFACE)

        self.BG = BG
        self.SURFACE = SURFACE
        self.TEXT = TEXT
        self.GREEN = GREEN
        self.RED = RED

        # Connection status
        top_frame = ttk.Frame(root)
        top_frame.pack(fill=tk.X, padx=15, pady=(10, 5))

        ttk.Label(top_frame, text="Audacity Voice Cleaner", style="Header.TLabel").pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="Disconnected")
        self.status_label = ttk.Label(top_frame, textvariable=self.status_var, style="Sub.TLabel")
        self.status_label.pack(side=tk.RIGHT)

        self.connect_btn = ttk.Button(top_frame, text="Connect", style="Accent.TButton",
                                       command=self.try_connect)
        self.connect_btn.pack(side=tk.RIGHT, padx=(0, 10))

        # Notebook (tabs)
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)

        self._build_presets_tab()
        self._build_individual_tab()
        self._build_chain_tab()

        # Log area
        log_frame = ttk.LabelFrame(root, text="Log")
        log_frame.pack(fill=tk.X, padx=15, pady=(0, 10))

        self.log = scrolledtext.ScrolledText(log_frame, height=8, bg=SURFACE, fg=TEXT,
                                              font=("JetBrains Mono", 9), insertbackground=TEXT,
                                              borderwidth=0, wrap=tk.WORD)
        self.log.pack(fill=tk.X, padx=5, pady=5)

        # Bottom buttons
        bot_frame = ttk.Frame(root)
        bot_frame.pack(fill=tk.X, padx=15, pady=(0, 10))

        ttk.Button(bot_frame, text="Undo", style="Danger.TButton",
                   command=self.undo).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(bot_frame, text="Export WAV", style="Green.TButton",
                   command=self.export).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(bot_frame, text="Select All", command=self.select_all_cmd).pack(side=tk.LEFT)

        self.log_msg("Ready. Click 'Connect' to link to Audacity.")

    # --- Tab Builders ---

    def _build_presets_tab(self):
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text=" Presets ")

        ttk.Label(frame, text="Choose a preset pipeline and click Run.",
                  style="Sub.TLabel").pack(anchor=tk.W, padx=10, pady=(10, 5))

        self.preset_var = tk.StringVar(value=list(PRESETS.keys())[0])

        for name, info in PRESETS.items():
            rf = ttk.Frame(frame)
            rf.pack(fill=tk.X, padx=10, pady=3)

            rb = tk.Radiobutton(rf, text=name, variable=self.preset_var, value=name,
                                bg=self.BG, fg=self.TEXT, selectcolor=self.SURFACE,
                                activebackground=self.BG, activeforeground=self.TEXT,
                                font=("JetBrains Mono", 11, "bold"),
                                anchor=tk.W)
            rb.pack(anchor=tk.W)

            ttk.Label(rf, text=info["desc"], style="Sub.TLabel",
                      wraplength=700).pack(anchor=tk.W, padx=25)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, padx=10, pady=15)

        self.step_mode_var = tk.BooleanVar(value=False)
        cb = tk.Checkbutton(btn_frame, text="Step-by-step (confirm each effect)",
                            variable=self.step_mode_var,
                            bg=self.BG, fg=self.TEXT, selectcolor=self.SURFACE,
                            activebackground=self.BG, activeforeground=self.TEXT,
                            font=("JetBrains Mono", 10))
        cb.pack(side=tk.LEFT)

        ttk.Button(btn_frame, text="Run Preset", style="Accent.TButton",
                   command=self.run_preset).pack(side=tk.RIGHT)

    def _build_individual_tab(self):
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text=" Individual Effects ")

        canvas = tk.Canvas(frame, bg=self.BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Noise Reduction
        nrf = ttk.LabelFrame(inner, text="Noise Reduction")
        nrf.pack(fill=tk.X, padx=10, pady=5)

        self.nr_db = self._slider(nrf, "Reduction (dB)", 0, 48, 12)
        self.nr_sens = self._slider(nrf, "Sensitivity", 0, 24, 6)
        self.nr_smooth = self._slider(nrf, "Freq Smoothing", 0, 12, 3)

        nr_btns = ttk.Frame(nrf)
        nr_btns.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(nr_btns, text="1. Get Noise Profile",
                   command=self.nr_profile).pack(side=tk.LEFT, padx=2)
        ttk.Button(nr_btns, text="2. Apply Reduction", style="Accent.TButton",
                   command=self.nr_apply).pack(side=tk.LEFT, padx=2)
        ttk.Label(nr_btns, text="Select noise-only section before step 1",
                  style="Sub.TLabel").pack(side=tk.LEFT, padx=10)

        # Noise Gate
        ngf = ttk.LabelFrame(inner, text="Noise Gate")
        ngf.pack(fill=tk.X, padx=10, pady=5)

        self.ng_thresh = self._slider(ngf, "Threshold (dB)", -80, 0, -40)
        self.ng_reduction = self._slider(ngf, "Reduction (dB)", -80, 0, -24)

        ttk.Button(ngf, text="Apply Noise Gate", style="Accent.TButton",
                   command=self.apply_noise_gate).pack(padx=5, pady=5, anchor=tk.W)

        # Filters
        ff = ttk.LabelFrame(inner, text="Filters")
        ff.pack(fill=tk.X, padx=10, pady=5)

        self.hp_freq = self._slider(ff, "High-Pass (Hz)", 20, 500, 80)
        ttk.Button(ff, text="Apply High-Pass", style="Accent.TButton",
                   command=self.apply_highpass).pack(padx=5, pady=(0, 5), anchor=tk.W)

        self.lp_freq = self._slider(ff, "Low-Pass (Hz)", 2000, 16000, 8000)
        ttk.Button(ff, text="Apply Low-Pass", style="Accent.TButton",
                   command=self.apply_lowpass).pack(padx=5, pady=(0, 5), anchor=tk.W)

        self.notch_freq = self._slider(ff, "Notch Freq (Hz)", 20, 500, 60)
        self.notch_q = self._slider(ff, "Notch Q", 1, 50, 10)
        ttk.Button(ff, text="Apply Notch Filter", style="Accent.TButton",
                   command=self.apply_notch).pack(padx=5, pady=(0, 5), anchor=tk.W)

        # Dynamics
        df = ttk.LabelFrame(inner, text="Dynamics")
        df.pack(fill=tk.X, padx=10, pady=5)

        self.comp_thresh = self._slider(df, "Compressor Threshold (dB)", -60, 0, -12)
        self.comp_ratio = tk.StringVar(value="3:1")

        ratio_frame = ttk.Frame(df)
        ratio_frame.pack(fill=tk.X, padx=5)
        ttk.Label(ratio_frame, text="Ratio:").pack(side=tk.LEFT)
        for r in ["2:1", "3:1", "4:1", "5:1", "10:1"]:
            rb = tk.Radiobutton(ratio_frame, text=r, variable=self.comp_ratio, value=r,
                                bg=self.BG, fg=self.TEXT, selectcolor=self.SURFACE,
                                activebackground=self.BG, activeforeground=self.TEXT,
                                font=("JetBrains Mono", 9))
            rb.pack(side=tk.LEFT, padx=3)

        ttk.Button(df, text="Apply Compression", style="Accent.TButton",
                   command=self.apply_compression).pack(padx=5, pady=5, anchor=tk.W)

        self.norm_peak = self._slider(df, "Normalize Peak (dB)", -6, 0, -1)
        ttk.Button(df, text="Normalize", style="Accent.TButton",
                   command=self.apply_normalize).pack(padx=5, pady=(0, 5), anchor=tk.W)

        # EQ
        eqf = ttk.LabelFrame(inner, text="Equalization")
        eqf.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(eqf, text="Apply Voice EQ (cut mud, boost presence)", style="Accent.TButton",
                   command=self.apply_voice_eq).pack(padx=5, pady=5, anchor=tk.W)

        # Amplify
        ttk.Button(inner, text="Amplify to Max (no clip)", style="Accent.TButton",
                   command=self.apply_amplify).pack(padx=10, pady=5, anchor=tk.W)

    def _build_chain_tab(self):
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text=" Chain Builder ")

        ttk.Label(frame, text="Drag effects from Available to Chain, then run.",
                  style="Sub.TLabel").pack(anchor=tk.W, padx=10, pady=(10, 5))

        lists_frame = ttk.Frame(frame)
        lists_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Available
        left_frame = ttk.Frame(lists_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        ttk.Label(left_frame, text="Available Effects:").pack(anchor=tk.W)

        self.avail_list = tk.Listbox(left_frame, bg=self.SURFACE, fg=self.TEXT,
                                      font=("JetBrains Mono", 10), selectbackground="#585b70",
                                      borderwidth=0, height=12)
        self.avail_list.pack(fill=tk.BOTH, expand=True)

        effect_names = [
            "Noise Reduction", "Noise Gate", "High-Pass Filter", "Low-Pass Filter",
            "Notch Filter (60Hz)", "Notch Filter (120Hz)", "Voice EQ",
            "Compression", "Normalize", "Amplify"
        ]
        for name in effect_names:
            self.avail_list.insert(tk.END, name)

        # Buttons
        mid_frame = ttk.Frame(lists_frame)
        mid_frame.pack(side=tk.LEFT, padx=5)
        ttk.Button(mid_frame, text=">>", command=self.chain_add).pack(pady=3)
        ttk.Button(mid_frame, text="<<", command=self.chain_remove).pack(pady=3)
        ttk.Button(mid_frame, text="Up", command=self.chain_up).pack(pady=3)
        ttk.Button(mid_frame, text="Dn", command=self.chain_down).pack(pady=3)

        # Chain
        right_frame = ttk.Frame(lists_frame)
        right_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))
        ttk.Label(right_frame, text="Effect Chain:").pack(anchor=tk.W)

        self.chain_list = tk.Listbox(right_frame, bg=self.SURFACE, fg=self.TEXT,
                                      font=("JetBrains Mono", 10), selectbackground="#585b70",
                                      borderwidth=0, height=12)
        self.chain_list.pack(fill=tk.BOTH, expand=True)

        # Run chain
        chain_btns = ttk.Frame(frame)
        chain_btns.pack(fill=tk.X, padx=10, pady=10)
        ttk.Button(chain_btns, text="Clear Chain", command=self.chain_clear).pack(side=tk.LEFT)
        ttk.Button(chain_btns, text="Run Chain", style="Accent.TButton",
                   command=self.run_chain).pack(side=tk.RIGHT)

    def _slider(self, parent, label, from_, to, default):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, padx=5, pady=2)

        ttk.Label(frame, text=label, width=25).pack(side=tk.LEFT)

        var = tk.DoubleVar(value=default)
        scale = ttk.Scale(frame, from_=from_, to=to, variable=var, orient=tk.HORIZONTAL)
        scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        val_label = ttk.Label(frame, text=str(default), width=6)
        val_label.pack(side=tk.LEFT)

        def update_label(*_):
            val_label.config(text=f"{var.get():.1f}")
        var.trace_add("write", update_label)

        return var

    # --- Logging ---

    def log_msg(self, msg):
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)

    # --- Connection ---

    def try_connect(self):
        if connect():
            self.status_var.set("Connected")
            self.status_label.configure(foreground=self.GREEN)
            self.log_msg("Connected to Audacity.")
        else:
            self.status_var.set("Failed")
            self.status_label.configure(foreground=self.RED)
            messagebox.showerror("Connection Failed",
                                 "Cannot connect to Audacity.\n\n"
                                 "1. Open Audacity\n"
                                 "2. Edit -> Preferences -> Modules\n"
                                 "3. Set mod-script-pipe = Enabled\n"
                                 "4. Restart Audacity")

    def _require_connection(self):
        if not CONNECTED:
            messagebox.showwarning("Not Connected", "Connect to Audacity first.")
            return False
        return True

    # --- Run in thread to keep GUI responsive ---

    def _run_bg(self, func, *args):
        if not self._require_connection():
            return
        def wrapper():
            try:
                func(*args)
            except Exception as e:
                self.root.after(0, lambda: self.log_msg(f"ERROR: {e}"))
        threading.Thread(target=wrapper, daemon=True).start()

    # --- Individual effect commands ---

    def select_all_cmd(self):
        self._run_bg(lambda: (select_all(), self.root.after(0, lambda: self.log_msg("Selected all."))))

    def undo(self):
        self._run_bg(lambda: (fx_undo(), self.root.after(0, lambda: self.log_msg("Undo."))))

    def nr_profile(self):
        def go():
            ok, _ = fx_noise_reduction_profile(
                int(self.nr_db.get()), self.nr_sens.get(), int(self.nr_smooth.get()))
            status = "Got noise profile." if ok else "FAILED to get noise profile."
            self.root.after(0, lambda: self.log_msg(status))
        self._run_bg(go)

    def nr_apply(self):
        def go():
            select_all()
            ok, _ = fx_noise_reduction_apply(
                int(self.nr_db.get()), self.nr_sens.get(), int(self.nr_smooth.get()))
            status = f"Noise reduction applied ({int(self.nr_db.get())}dB)." if ok else "FAILED."
            self.root.after(0, lambda: self.log_msg(status))
        self._run_bg(go)

    def apply_noise_gate(self):
        def go():
            ok, _ = fx_noise_gate(int(self.ng_thresh.get()), 10, 50, 100, int(self.ng_reduction.get()))
            self.root.after(0, lambda: self.log_msg(
                f"Noise gate applied (thresh={int(self.ng_thresh.get())}dB)." if ok else "FAILED."))
        self._run_bg(go)

    def apply_highpass(self):
        def go():
            ok, _ = fx_highpass(int(self.hp_freq.get()))
            self.root.after(0, lambda: self.log_msg(
                f"High-pass at {int(self.hp_freq.get())}Hz." if ok else "FAILED."))
        self._run_bg(go)

    def apply_lowpass(self):
        def go():
            ok, _ = fx_lowpass(int(self.lp_freq.get()))
            self.root.after(0, lambda: self.log_msg(
                f"Low-pass at {int(self.lp_freq.get())}Hz." if ok else "FAILED."))
        self._run_bg(go)

    def apply_notch(self):
        def go():
            ok, _ = fx_notch(int(self.notch_freq.get()), int(self.notch_q.get()))
            self.root.after(0, lambda: self.log_msg(
                f"Notch at {int(self.notch_freq.get())}Hz." if ok else "FAILED."))
        self._run_bg(go)

    def apply_compression(self):
        def go():
            ok, _ = fx_compressor(int(self.comp_thresh.get()), -40,
                                   self.comp_ratio.get(), 0.2, 1.0)
            self.root.after(0, lambda: self.log_msg(
                f"Compression ({self.comp_ratio.get()})." if ok else "FAILED."))
        self._run_bg(go)

    def apply_normalize(self):
        def go():
            ok, _ = fx_normalize(self.norm_peak.get())
            self.root.after(0, lambda: self.log_msg(
                f"Normalized to {self.norm_peak.get():.1f}dB." if ok else "FAILED."))
        self._run_bg(go)

    def apply_voice_eq(self):
        def go():
            ok, _ = fx_voice_eq()
            self.root.after(0, lambda: self.log_msg("Voice EQ applied." if ok else "FAILED."))
        self._run_bg(go)

    def apply_amplify(self):
        def go():
            ok, _ = fx_amplify()
            self.root.after(0, lambda: self.log_msg("Amplified to max." if ok else "FAILED."))
        self._run_bg(go)

    def export(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".wav",
            filetypes=[("WAV files", "*.wav"), ("All files", "*.*")],
            initialdir=os.path.expanduser("~/Desktop/Claude Output"),
            initialfile="cleaned.wav"
        )
        if not path:
            return

        def go():
            ok, _ = do_command(f'Export2: Filename="{path}" NumChannels=1')
            self.root.after(0, lambda: self.log_msg(
                f"Exported to {path}" if ok else f"Export FAILED."))
        self._run_bg(go)

    # --- Preset runner ---

    def run_preset(self):
        if not self._require_connection():
            return
        name = self.preset_var.get()
        preset = PRESETS[name]
        step_by_step = self.step_mode_var.get()

        def go():
            self.root.after(0, lambda: self.log_msg(f"\n--- Running preset: {name} ---"))

            # For noise reduction, we need user to select noise first
            need_nr = any(s[1] == "nr" for s in preset["steps"])
            if need_nr:
                self.root.after(0, lambda: messagebox.showinfo(
                    "Noise Profile Required",
                    "Select a noise-only section in Audacity\n"
                    "(a quiet part with only background noise),\n"
                    "then click OK to continue."
                ))

            for i, (label, fx_type, params) in enumerate(preset["steps"]):
                if step_by_step and i > 0:
                    result = [None]
                    def ask():
                        result[0] = messagebox.askyesno(
                            f"Step {i+1}/{len(preset['steps'])}",
                            f"Apply: {label}?\n\nListen to current result first if needed.")
                    self.root.after(0, ask)
                    import time
                    while result[0] is None:
                        time.sleep(0.1)
                    if not result[0]:
                        self.root.after(0, lambda l=label: self.log_msg(f"  Skipped: {l}"))
                        continue

                self.root.after(0, lambda l=label: self.log_msg(f"  Applying: {l}..."))
                ok = self._run_effect(fx_type, params)
                status = "OK" if ok else "FAILED"
                self.root.after(0, lambda l=label, s=status: self.log_msg(f"  {l}: {s}"))

            self.root.after(0, lambda: self.log_msg(f"--- Preset complete: {name} ---\n"))

        threading.Thread(target=go, daemon=True).start()

    def _run_effect(self, fx_type, params):
        if fx_type == "nr":
            fx_noise_reduction_profile(params["reduction_db"], params["sensitivity"], params["freq_smoothing"])
            select_all()
            ok, _ = fx_noise_reduction_apply(params["reduction_db"], params["sensitivity"], params["freq_smoothing"])
        elif fx_type == "ng":
            ok, _ = fx_noise_gate(params["threshold"], params["attack"], params["hold"],
                                   params["release"], params["reduction"])
        elif fx_type == "hp":
            ok, _ = fx_highpass(params["freq"])
        elif fx_type == "lp":
            ok, _ = fx_lowpass(params["freq"])
        elif fx_type == "notch":
            ok, _ = fx_notch(params["freq"], params["q"])
        elif fx_type == "comp":
            ok, _ = fx_compressor(params["threshold"], params["noise_floor"],
                                   params["ratio"], params["attack"], params["release"])
        elif fx_type == "norm":
            ok, _ = fx_normalize(params["peak"])
        elif fx_type == "eq":
            ok, _ = fx_voice_eq()
        elif fx_type == "amp":
            ok, _ = fx_amplify()
        else:
            ok = False
        return ok

    # --- Chain builder ---

    def chain_add(self):
        sel = self.avail_list.curselection()
        if sel:
            name = self.avail_list.get(sel[0])
            self.chain_list.insert(tk.END, name)

    def chain_remove(self):
        sel = self.chain_list.curselection()
        if sel:
            self.chain_list.delete(sel[0])

    def chain_up(self):
        sel = self.chain_list.curselection()
        if sel and sel[0] > 0:
            idx = sel[0]
            item = self.chain_list.get(idx)
            self.chain_list.delete(idx)
            self.chain_list.insert(idx - 1, item)
            self.chain_list.selection_set(idx - 1)

    def chain_down(self):
        sel = self.chain_list.curselection()
        if sel and sel[0] < self.chain_list.size() - 1:
            idx = sel[0]
            item = self.chain_list.get(idx)
            self.chain_list.delete(idx)
            self.chain_list.insert(idx + 1, item)
            self.chain_list.selection_set(idx + 1)

    def chain_clear(self):
        self.chain_list.delete(0, tk.END)

    def run_chain(self):
        if not self._require_connection():
            return
        items = list(self.chain_list.get(0, tk.END))
        if not items:
            messagebox.showinfo("Empty Chain", "Add effects to the chain first.")
            return

        EFFECT_MAP = {
            "Noise Reduction": ("nr", {"reduction_db": 12, "sensitivity": 6, "freq_smoothing": 3}),
            "Noise Gate": ("ng", {"threshold": -40, "attack": 10, "hold": 50, "release": 100, "reduction": -24}),
            "High-Pass Filter": ("hp", {"freq": 80}),
            "Low-Pass Filter": ("lp", {"freq": 8000}),
            "Notch Filter (60Hz)": ("notch", {"freq": 60, "q": 10}),
            "Notch Filter (120Hz)": ("notch", {"freq": 120, "q": 10}),
            "Voice EQ": ("eq", {}),
            "Compression": ("comp", {"threshold": -12, "noise_floor": -40, "ratio": "3:1", "attack": 0.2, "release": 1.0}),
            "Normalize": ("norm", {"peak": -1.0}),
            "Amplify": ("amp", {}),
        }

        need_nr = "Noise Reduction" in items
        if need_nr:
            messagebox.showinfo("Noise Profile",
                                "Select a noise-only section in Audacity, then click OK.")

        def go():
            self.root.after(0, lambda: self.log_msg(f"\n--- Running chain ({len(items)} effects) ---"))
            for name in items:
                if name in EFFECT_MAP:
                    fx_type, params = EFFECT_MAP[name]
                    self.root.after(0, lambda n=name: self.log_msg(f"  Applying: {n}..."))
                    ok = self._run_effect(fx_type, params)
                    status = "OK" if ok else "FAILED"
                    self.root.after(0, lambda n=name, s=status: self.log_msg(f"  {n}: {s}"))
            self.root.after(0, lambda: self.log_msg("--- Chain complete ---\n"))

        threading.Thread(target=go, daemon=True).start()


def main():
    root = tk.Tk()
    app = VoiceCleanApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
