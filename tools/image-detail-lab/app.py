#!/usr/bin/env python3
"""Image Detail Lab — Local image enhancement and analysis tool.

Usage:
    python app.py
"""

import json
import os
import shutil
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from analyzer import analyze_image, generate_suggestions, rank_variants
from enhancer import generate_variants
from reporter import export_html_report

THUMB_SIZE = (120, 120)
CANVAS_BG = "#2b2b2b"


class ImageDetailLab:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Image Detail Lab")
        self.root.geometry("1280x820")
        self.root.minsize(960, 640)

        # State
        self.case_dir: str | None = None
        self.original: Image.Image | None = None
        self.variants: dict[str, Image.Image] = {}
        self.analyses: dict[str, dict] = {}
        self.rankings: list[tuple[str, float, str]] = []
        self.suggestions: list[str] = []
        self.selected: set[str] = set()
        self.check_vars: dict[str, tk.BooleanVar] = {}
        self.current_name: str | None = None
        self.current_image: Image.Image | None = None

        # Zoom / pan
        self.zoom_level = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self._drag_start: tuple[int, int] | None = None

        # Crop
        self.crop_mode = False
        self._crop_rect_id = None
        self._crop_start: tuple[int, int] | None = None

        # Compare
        self.compare_active = False

        # PhotoImage refs (prevent garbage collection)
        self._photo_refs: list[ImageTk.PhotoImage] = []
        self._thumb_refs: list[ImageTk.PhotoImage] = []

        self._build_gui()
        self._set_status("Ready — load an image to begin.")

    # ── GUI Construction ───────────────────────────────────────

    def _build_gui(self):
        self._build_menu()
        self._build_toolbar()
        self._build_main_area()
        self._build_status_bar()

    def _build_menu(self):
        bar = tk.Menu(self.root)
        fm = tk.Menu(bar, tearoff=0)
        fm.add_command(label="Open Image…", command=self.load_image, accelerator="Ctrl+O")
        fm.add_command(label="Save Selected", command=self.save_selected, accelerator="Ctrl+S")
        fm.add_command(label="Export Report", command=self.export_report, accelerator="Ctrl+E")
        fm.add_separator()
        fm.add_command(label="Quit", command=self.root.quit, accelerator="Ctrl+Q")
        bar.add_cascade(label="File", menu=fm)
        self.root.config(menu=bar)

        self.root.bind("<Control-o>", lambda _: self.load_image())
        self.root.bind("<Control-s>", lambda _: self.save_selected())
        self.root.bind("<Control-e>", lambda _: self.export_report())
        self.root.bind("<Control-q>", lambda _: self.root.quit())

    def _build_toolbar(self):
        tb = ttk.Frame(self.root)
        tb.pack(side=tk.TOP, fill=tk.X, padx=5, pady=3)

        ttk.Button(tb, text="Open Image", command=self.load_image).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text="Save Selected", command=self.save_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text="Export Report", command=self.export_report).pack(side=tk.LEFT, padx=2)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        self.crop_btn = ttk.Button(tb, text="Crop Mode", command=self.toggle_crop)
        self.crop_btn.pack(side=tk.LEFT, padx=2)
        self.compare_btn = ttk.Button(tb, text="Compare", command=self.toggle_compare)
        self.compare_btn.pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text="Reset Zoom", command=self.reset_zoom).pack(side=tk.LEFT, padx=2)

        # Compare variant selector (hidden until compare mode)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        self._cmp_label = ttk.Label(tb, text="Compare with:")
        self._cmp_var = tk.StringVar()
        self._cmp_combo = ttk.Combobox(tb, textvariable=self._cmp_var, state="readonly", width=18)
        self._cmp_combo.bind("<<ComboboxSelected>>", lambda _: self._render_compare())

    def _build_main_area(self):
        pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=3)

        # Left — thumbnails
        left = ttk.Frame(pane, width=170)
        pane.add(left, weight=0)
        ttk.Label(left, text="Variants", font=("", 10, "bold")).pack(anchor="w", padx=5)
        container = ttk.Frame(left)
        container.pack(fill=tk.BOTH, expand=True)
        self._thumb_canvas = tk.Canvas(container, width=158, bg="#f0f0f0", highlightthickness=0)
        scroll = ttk.Scrollbar(container, orient=tk.VERTICAL, command=self._thumb_canvas.yview)
        self._thumb_canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._thumb_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._thumb_inner = ttk.Frame(self._thumb_canvas)
        self._thumb_canvas.create_window((0, 0), window=self._thumb_inner, anchor="nw")
        self._thumb_inner.bind(
            "<Configure>",
            lambda _: self._thumb_canvas.configure(scrollregion=self._thumb_canvas.bbox("all")),
        )
        # Mousewheel scrolling on the thumbnail panel
        self._thumb_canvas.bind("<Button-4>", lambda e: self._thumb_canvas.yview_scroll(-3, "units"))
        self._thumb_canvas.bind("<Button-5>", lambda e: self._thumb_canvas.yview_scroll(3, "units"))

        # Center — main canvas + compare canvas
        center = ttk.Frame(pane)
        pane.add(center, weight=3)
        self._canvas_frame = ttk.Frame(center)
        self._canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.main_canvas = tk.Canvas(self._canvas_frame, bg=CANVAS_BG, cursor="hand2", highlightthickness=0)
        self.main_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.main_canvas.bind("<ButtonPress-1>", self._on_press)
        self.main_canvas.bind("<B1-Motion>", self._on_drag)
        self.main_canvas.bind("<ButtonRelease-1>", self._on_release)
        self.main_canvas.bind("<Button-4>", self._on_scroll)
        self.main_canvas.bind("<Button-5>", self._on_scroll)
        self.main_canvas.bind("<MouseWheel>", self._on_scroll)

        self._cmp_canvas = tk.Canvas(self._canvas_frame, bg=CANVAS_BG, highlightthickness=0)

        # Right — analysis + AI guidance + notes
        right = ttk.Frame(pane, width=270)
        pane.add(right, weight=1)

        ttk.Label(right, text="Analysis", font=("", 10, "bold")).pack(anchor="w", padx=5, pady=(5, 0))
        self._analysis_text = tk.Text(right, height=12, wrap=tk.WORD, state=tk.DISABLED, font=("Consolas", 9))
        self._analysis_text.pack(fill=tk.X, padx=5, pady=3)

        ttk.Label(right, text="AI Guidance", font=("", 10, "bold")).pack(anchor="w", padx=5, pady=(5, 0))
        self._suggest_text = tk.Text(right, height=8, wrap=tk.WORD, state=tk.DISABLED, font=("", 9))
        self._suggest_text.pack(fill=tk.X, padx=5, pady=3)

        ttk.Label(right, text="Notes", font=("", 10, "bold")).pack(anchor="w", padx=5, pady=(5, 0))
        self._notes_text = tk.Text(right, height=10, wrap=tk.WORD, font=("", 9))
        self._notes_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=3)

    def _build_status_bar(self):
        self._status_var = tk.StringVar()
        ttk.Label(self.root, textvariable=self._status_var, relief=tk.SUNKEN, anchor="w").pack(
            side=tk.BOTTOM, fill=tk.X
        )

    def _set_status(self, text: str):
        self._status_var.set(text)
        self.root.update_idletasks()

    # ── Image Loading ──────────────────────────────────────────

    def load_image(self):
        path = filedialog.askopenfilename(
            title="Open Image",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.tiff *.tif *.bmp *.webp"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        self._set_status(f"Loading {os.path.basename(path)}…")
        try:
            img = Image.open(path)
            img.load()
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            self.original = img
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to load image:\n{exc}")
            return

        # Case folder
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        case_name = f"{ts}_{Path(path).stem}"
        self.case_dir = os.path.join(os.getcwd(), "cases", case_name)
        for sub in ("original", "variants", "exports"):
            os.makedirs(os.path.join(self.case_dir, sub), exist_ok=True)
        shutil.copy2(path, os.path.join(self.case_dir, "original", os.path.basename(path)))

        # Generate variants
        self._set_status("Generating enhancement variants…")
        self.root.update()
        self.variants = {"Original": self.original}
        self.variants.update(generate_variants(self.original))

        # Analyze
        self._set_status("Analyzing variants…")
        self.root.update()
        self.analyses = {n: analyze_image(v) for n, v in self.variants.items()}
        self.rankings = rank_variants(self.analyses)
        self.suggestions = generate_suggestions(self.analyses, self.rankings)

        # Save metadata
        self._save_case_meta(path)

        # Reset view state
        self.selected.clear()
        self.zoom_level = 1.0
        self.pan_x = self.pan_y = 0
        if self.compare_active:
            self.toggle_compare()
        if self.crop_mode:
            self.toggle_crop()

        # Refresh GUI
        self._populate_thumbs()
        self._show_variant("Original")
        self._refresh_suggestions()
        self._set_status(f"Loaded — {len(self.variants)} variants. Case: {case_name}")

    def _save_case_meta(self, source_path: str):
        meta = {
            "source": source_path,
            "created": datetime.now().isoformat(),
            "image_size": list(self.original.size),
            "mode": self.original.mode,
            "variants": list(self.variants.keys()),
            "analyses": self.analyses,
            "rankings": [(n, s, r) for n, s, r in self.rankings],
        }
        with open(os.path.join(self.case_dir, "case.json"), "w") as f:
            json.dump(meta, f, indent=2)

    # ── Thumbnail Panel ────────────────────────────────────────

    def _populate_thumbs(self):
        for w in self._thumb_inner.winfo_children():
            w.destroy()
        self._thumb_refs.clear()
        self.check_vars.clear()

        for name in self.variants:
            frame = ttk.Frame(self._thumb_inner)
            frame.pack(fill=tk.X, padx=3, pady=3)

            thumb = self.variants[name].copy()
            thumb.thumbnail(THUMB_SIZE, Image.LANCZOS)
            if thumb.mode != "RGB":
                thumb = thumb.convert("RGB")
            photo = ImageTk.PhotoImage(thumb)
            self._thumb_refs.append(photo)

            lbl = tk.Label(frame, image=photo, cursor="hand2", bg="#f0f0f0")
            lbl.pack()
            lbl.bind("<Button-1>", lambda _, n=name: self._show_variant(n))

            row = ttk.Frame(frame)
            row.pack(fill=tk.X)
            var = tk.BooleanVar()
            self.check_vars[name] = var
            ttk.Checkbutton(row, variable=var).pack(side=tk.LEFT)
            ttk.Label(row, text=name, font=("", 8)).pack(side=tk.LEFT)

    # ── Main Canvas ────────────────────────────────────────────

    def _show_variant(self, name: str):
        if name not in self.variants:
            return
        self.current_name = name
        self.current_image = self.variants[name]
        self._render_main()
        self._refresh_analysis(name)

    def _render_main(self):
        if self.current_image is None:
            return
        self.main_canvas.delete("all")
        self._photo_refs.clear()

        cw = self.main_canvas.winfo_width()
        ch = self.main_canvas.winfo_height()
        if cw < 2 or ch < 2:
            self.root.after(50, self._render_main)
            return

        img = self.current_image
        fit = min(cw / img.width, ch / img.height, 1.0)
        ratio = fit * self.zoom_level
        nw, nh = max(1, int(img.width * ratio)), max(1, int(img.height * ratio))

        display = img.resize((nw, nh), Image.LANCZOS)
        if display.mode != "RGB":
            display = display.convert("RGB")
        photo = ImageTk.PhotoImage(display)
        self._photo_refs.append(photo)

        cx = cw // 2 + self.pan_x
        cy = ch // 2 + self.pan_y
        self.main_canvas.create_image(cx, cy, image=photo, anchor="center")
        self.main_canvas.create_text(10, 10, text=self.current_name, fill="white", anchor="nw", font=("", 11, "bold"))
        self.main_canvas.create_text(10, 30, text=f"Zoom: {self.zoom_level:.1f}x", fill="#aaa", anchor="nw", font=("", 9))

        # Also update compare pane if active
        if self.compare_active:
            self._render_compare()

    # ── Canvas Interaction ─────────────────────────────────────

    def _on_press(self, event):
        if self.crop_mode:
            self._crop_start = (event.x, event.y)
            if self._crop_rect_id:
                self.main_canvas.delete(self._crop_rect_id)
        else:
            self._drag_start = (event.x, event.y)

    def _on_drag(self, event):
        if self.crop_mode and self._crop_start:
            if self._crop_rect_id:
                self.main_canvas.delete(self._crop_rect_id)
            self._crop_rect_id = self.main_canvas.create_rectangle(
                *self._crop_start, event.x, event.y,
                outline="#00ff00", width=2, dash=(4, 4),
            )
        elif self._drag_start:
            self.pan_x += event.x - self._drag_start[0]
            self.pan_y += event.y - self._drag_start[1]
            self._drag_start = (event.x, event.y)
            self._render_main()

    def _on_release(self, event):
        if self.crop_mode and self._crop_start:
            self._apply_crop(*self._crop_start, event.x, event.y)
            self._crop_start = None
        self._drag_start = None

    def _on_scroll(self, event):
        if event.num == 5 or (hasattr(event, "delta") and event.delta < 0):
            self.zoom_level = max(0.1, self.zoom_level * 0.9)
        else:
            self.zoom_level = min(10.0, self.zoom_level * 1.1)
        self._render_main()

    def reset_zoom(self):
        self.zoom_level = 1.0
        self.pan_x = self.pan_y = 0
        self._render_main()

    # ── Crop ───────────────────────────────────────────────────

    def toggle_crop(self):
        self.crop_mode = not self.crop_mode
        if self.crop_mode:
            self.main_canvas.config(cursor="crosshair")
            self.crop_btn.config(text="Cancel Crop")
            self._set_status("Crop mode — draw a rectangle on the image.")
        else:
            self.main_canvas.config(cursor="hand2")
            self.crop_btn.config(text="Crop Mode")
            if self._crop_rect_id:
                self.main_canvas.delete(self._crop_rect_id)
                self._crop_rect_id = None
            self._set_status("Crop mode cancelled.")

    def _apply_crop(self, x1, y1, x2, y2):
        if self.current_image is None:
            return

        cw = self.main_canvas.winfo_width()
        ch = self.main_canvas.winfo_height()
        img = self.current_image
        fit = min(cw / img.width, ch / img.height, 1.0)
        ratio = fit * self.zoom_level

        disp_w = int(img.width * ratio)
        disp_h = int(img.height * ratio)
        img_left = cw // 2 + self.pan_x - disp_w // 2
        img_top = ch // 2 + self.pan_y - disp_h // 2

        # Canvas coords → image coords
        ix1 = max(0, min(int((min(x1, x2) - img_left) / ratio), img.width))
        iy1 = max(0, min(int((min(y1, y2) - img_top) / ratio), img.height))
        ix2 = max(0, min(int((max(x1, x2) - img_left) / ratio), img.width))
        iy2 = max(0, min(int((max(y1, y2) - img_top) / ratio), img.height))

        if ix2 - ix1 < 10 or iy2 - iy1 < 10:
            self._set_status("Crop region too small — try again.")
            return

        if not messagebox.askyesno("Crop", f"Crop all variants to region ({ix1},{iy1})–({ix2},{iy2})?"):
            self.toggle_crop()
            return

        for name in list(self.variants):
            try:
                self.variants[name] = self.variants[name].crop((ix1, iy1, ix2, iy2))
            except Exception:
                pass
        self.original = self.original.crop((ix1, iy1, ix2, iy2))

        # Re-analyze
        self.analyses = {n: analyze_image(v) for n, v in self.variants.items()}
        self.rankings = rank_variants(self.analyses)
        self.suggestions = generate_suggestions(self.analyses, self.rankings)

        self._populate_thumbs()
        self._show_variant(self.current_name or "Original")
        self._refresh_suggestions()
        self.toggle_crop()
        self._set_status(f"Cropped to {ix2 - ix1}×{iy2 - iy1} px. All variants updated.")

    # ── Compare Mode ───────────────────────────────────────────

    def toggle_compare(self):
        self.compare_active = not self.compare_active
        if self.compare_active:
            self.compare_btn.config(text="Exit Compare")
            names = [n for n in self.variants if n != self.current_name]
            self._cmp_combo["values"] = names
            if names:
                self._cmp_var.set(names[0])
            self._cmp_label.pack(side=tk.LEFT, padx=(0, 4))
            self._cmp_combo.pack(side=tk.LEFT, padx=2)
            self._cmp_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            self._render_compare()
            self._set_status("Compare mode — select a second variant from the toolbar dropdown.")
        else:
            self.compare_btn.config(text="Compare")
            self._cmp_label.pack_forget()
            self._cmp_combo.pack_forget()
            self._cmp_canvas.pack_forget()
            self._set_status("Compare mode off.")

    def _render_compare(self):
        name = self._cmp_var.get()
        if name not in self.variants:
            return
        self._cmp_canvas.delete("all")
        cw = self._cmp_canvas.winfo_width()
        ch = self._cmp_canvas.winfo_height()
        if cw < 2 or ch < 2:
            self.root.after(50, self._render_compare)
            return

        img = self.variants[name]
        ratio = min(cw / img.width, ch / img.height, 1.0)
        nw, nh = max(1, int(img.width * ratio)), max(1, int(img.height * ratio))
        display = img.resize((nw, nh), Image.LANCZOS)
        if display.mode != "RGB":
            display = display.convert("RGB")
        photo = ImageTk.PhotoImage(display)
        self._photo_refs.append(photo)
        self._cmp_canvas.create_image(cw // 2, ch // 2, image=photo, anchor="center")
        self._cmp_canvas.create_text(10, 10, text=name, fill="white", anchor="nw", font=("", 11, "bold"))

    # ── Analysis Panel ─────────────────────────────────────────

    def _refresh_analysis(self, name: str):
        a = self.analyses.get(name, {})
        self._analysis_text.config(state=tk.NORMAL)
        self._analysis_text.delete("1.0", tk.END)
        if not a:
            self._analysis_text.config(state=tk.DISABLED)
            return

        lines = [
            f"Variant: {name}",
            "",
            f"Sharpness:  {a['sharpness']:>10.2f}",
            f"Contrast:   {a['contrast']:>10.2f}",
            f"Detail:     {a['detail']:>10.2f}",
            f"Noise:      {a['noise']:>10.2f}",
            f"Brightness: {a['brightness']:>10.2f}",
            "",
        ]
        for i, (rn, sc, reason) in enumerate(self.rankings):
            if rn == name:
                lines.append(f"Rank: #{i + 1}  (score {sc})")
                lines.append(reason)
                break
        if a.get("posterization_risk"):
            lines.append("\n⚠ Posterization risk")
        if a.get("clipping_risk"):
            lines.append(f"⚠ Clipping: {a['clip_dark_pct']}% dark, {a['clip_bright_pct']}% bright")

        self._analysis_text.insert("1.0", "\n".join(lines))
        self._analysis_text.config(state=tk.DISABLED)

    def _refresh_suggestions(self):
        self._suggest_text.config(state=tk.NORMAL)
        self._suggest_text.delete("1.0", tk.END)
        for s in self.suggestions:
            self._suggest_text.insert(tk.END, f"• {s}\n\n")
        self._suggest_text.config(state=tk.DISABLED)

    # ── Save / Export ──────────────────────────────────────────

    def save_selected(self):
        if not self.case_dir:
            messagebox.showinfo("Info", "No case loaded.")
            return
        self.selected = {n for n, v in self.check_vars.items() if v.get()}
        if not self.selected:
            messagebox.showinfo("Info", "No variants selected.\nTick the checkboxes next to thumbnails first.")
            return

        export_dir = os.path.join(self.case_dir, "exports")
        count = 0
        for name in self.selected:
            safe = name.lower().replace(" ", "_")
            self.variants[name].save(os.path.join(export_dir, f"{safe}.png"), "PNG")
            count += 1

        self._set_status(f"Saved {count} variant(s) to exports/.")
        messagebox.showinfo("Saved", f"Saved {count} variant(s) to:\n{export_dir}")

    def export_report(self):
        if not self.case_dir:
            messagebox.showinfo("Info", "No case loaded.")
            return
        self.selected = {n for n, v in self.check_vars.items() if v.get()}
        notes = self._notes_text.get("1.0", tk.END).strip()

        self._set_status("Generating report…")
        try:
            path = export_html_report(
                case_dir=self.case_dir,
                original=self.original,
                variants=self.variants,
                analyses=self.analyses,
                rankings=self.rankings,
                suggestions=self.suggestions,
                notes=notes,
                selected=self.selected,
            )
            self._set_status(f"Report saved: {path}")
            messagebox.showinfo("Report", f"Report saved to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Error", f"Report generation failed:\n{exc}")


def main():
    root = tk.Tk()
    ImageDetailLab(root)
    root.mainloop()


if __name__ == "__main__":
    main()
