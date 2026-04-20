#!/usr/bin/env python3
"""
MIDI → MTP  |  Polyend Tracker Pattern Converter
GUI built with tkinter – no extra dependencies beyond mido.
"""

import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
import threading
import sys

sys.path.insert(0, str(Path(__file__).parent))

try:
    import mido
except ImportError:
    mido = None

from midi_to_mtp import (build_mtp, midi_to_tracks, merge_midi_files_to_tracks,
                          SIZEOF_PATTERN, STEP_NOTE_EMPTY, MERGE_TRACK_MAX)

# ─────────────────────────────────────────────────────────────
# Palette  – dark hardware / tracker aesthetic
# ─────────────────────────────────────────────────────────────
BG       = "#111111"
SURFACE  = "#1A1A1A"
SURFACE2 = "#222222"
BORDER   = "#2E2E2E"
LINE     = "#303030"
ACCENT   = "#FF7A00"
ACCENT_H = "#FF9A30"
ACCENT_D = "#7A3B00"
FG       = "#DDDDDD"
FG2      = "#888888"
FG3      = "#555555"
OK       = "#55CC88"
ERR      = "#FF4455"
SEL_BG   = "#2A2000"

FONT_TITLE = ("Courier", 18, "bold")
FONT_SUB   = ("Courier", 9)
FONT_LABEL = ("Courier", 10)
FONT_MONO  = ("Courier", 10)
FONT_LOG   = ("Courier", 9)
FONT_BTN   = ("Courier", 11, "bold")
FONT_CONV  = ("Courier", 14, "bold")
FONT_HINT  = ("Courier", 8)
FONT_HELP  = ("Courier", 10)


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _sep(parent, **kw):
    tk.Frame(parent, bg=LINE, height=1, **kw).pack(fill="x", padx=16, pady=8)


def _label(parent, text, color=FG2, font=FONT_LABEL, **kw):
    return tk.Label(parent, text=text, bg=BG, fg=color, font=font, **kw)


def _hint(parent, text):
    """Small dark-grey hint line for contextual instructions."""
    tk.Label(parent, text=text, bg=BG, fg=FG3, font=FONT_HINT,
             anchor="w", justify="left").pack(fill="x", padx=20, pady=(0, 4))


def _section_title(parent, text):
    row = tk.Frame(parent, bg=BG)
    row.pack(fill="x", padx=16, pady=(12, 4))
    tk.Label(row, text="▸ " + text, bg=BG, fg=ACCENT,
             font=("Courier", 10, "bold")).pack(side="left")


# ─────────────────────────────────────────────────────────────
# Main App
# ─────────────────────────────────────────────────────────────

class App(tk.Tk):

    def __init__(self):
        super().__init__()

        self.title("MIDI→MTP  |  Polyend Tracker")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(560, 680)

        # ── state ──────────────────────────────
        self.midi_files        = []
        self.track_assignments = []            # parallel to midi_files - track per file (merge mode)
        self.mode_var          = tk.StringVar(value="split")
        self.track_sel_var     = tk.IntVar(value=0)
        self.out_dir_var       = tk.StringVar(value="")
        self.index_var         = tk.IntVar(value=1)
        self.res_var           = tk.IntVar(value=16)
        self.instr_var         = tk.IntVar(value=0)
        self.converting        = False

        self._build_ui()

    # ── UI construction ────────────────────────────────────────

    def _build_ui(self):
        self._build_header()
        _sep(self)
        self._build_files_section()
        _sep(self)
        self._build_output_section()
        _sep(self)
        self._build_options_section()
        _sep(self)
        self._build_convert_btn()
        self._build_log_section()
        self._show_welcome()

    def _build_header(self):
        frame = tk.Frame(self, bg=BG)
        frame.pack(fill="x", padx=20, pady=(18, 6))

        tk.Label(frame, text="MIDI → MTP", bg=BG, fg=ACCENT,
                 font=FONT_TITLE).pack(side="left")
        tk.Label(frame, text="  Polyend Tracker Pattern Converter",
                 bg=BG, fg=FG3, font=FONT_SUB, anchor="s").pack(side="left", pady=(8, 0))

        help_btn = tk.Button(
            frame, text="?",
            bg=SURFACE2, fg=FG2,
            activebackground=SURFACE, activeforeground=ACCENT,
            relief="flat", borderwidth=0, padx=8, pady=4,
            font=("Courier", 11, "bold"), cursor="hand2",
            command=self._open_help,
        )
        help_btn.pack(side="right")

    def _build_files_section(self):
        _section_title(self, "MIDI FILES")

        # -- Mode toggle ───────────────────────────────────
        mode_row = tk.Frame(self, bg=BG)
        mode_row.pack(fill="x", padx=16, pady=(0, 6))
        tk.Label(mode_row, text="Mode:", bg=BG, fg=FG2,
                 font=FONT_LABEL, width=10, anchor="w").pack(side="left")
        for label, val in [("ONE FILE = ONE PATTERN", "split"),
                            ("MULTI FILE = ONE PATTERN", "merge")]:
            rb = tk.Radiobutton(
                mode_row, text=label, variable=self.mode_var, value=val,
                bg=BG, fg=FG, selectcolor=BG,
                activebackground=BG, activeforeground=ACCENT,
                font=FONT_HINT, indicatoron=0, relief="flat", borderwidth=0,
                padx=8, pady=4,
                command=self._on_mode_change,
            )
            rb.pack(side="left", padx=(0, 6))

        # -- File list + buttons ───────────────────────────────
        container = tk.Frame(self, bg=BG)
        container.pack(fill="both", padx=16, pady=(0, 4))

        list_frame = tk.Frame(container, bg=BORDER, padx=1, pady=1)
        list_frame.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(list_frame, bg=SURFACE)
        inner.pack(fill="both", expand=True)

        self.file_list = tk.Listbox(
            inner,
            bg=SURFACE, fg=FG, selectbackground=SEL_BG,
            selectforeground=ACCENT, font=FONT_MONO,
            borderwidth=0, highlightthickness=0,
            activestyle="none", height=5,
        )
        sb = tk.Scrollbar(inner, orient="vertical",
                          command=self.file_list.yview,
                          bg=SURFACE2, troughcolor=SURFACE,
                          activebackground=ACCENT_D, relief="flat", width=10)
        self.file_list.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.file_list.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        self.file_list.bind("<<ListboxSelect>>", self._on_file_select)

        btn_col = tk.Frame(container, bg=BG)
        btn_col.pack(side="left", padx=(8, 0), anchor="n")
        self._mk_btn(btn_col, "+ ADD",    self._add_files).pack(fill="x", pady=(0, 4))
        self._mk_btn(btn_col, "- REMOVE",  self._remove_file).pack(fill="x", pady=(0, 4))
        self._mk_btn(btn_col, "x CLEAR",   self._clear_files).pack(fill="x")

        # ── Counter ─────────────────────────────────────────────
        self.files_lbl = tk.Label(self, text="0 files selected",
                                  bg=BG, fg=FG3, font=FONT_LOG, anchor="w")
        self.files_lbl.pack(fill="x", padx=20, pady=(2, 0))

        # ── Mode-dependent content ─────────────────────────────
        self.mode_content = tk.Frame(self, bg=BG)
        self.mode_content.pack(fill="x")

        # ── Merge frame (hidden by default) ─────────────────────
        self.merge_frame = tk.Frame(self.mode_content, bg=BG)
        track_row = tk.Frame(self.merge_frame, bg=BG)
        track_row.pack(fill="x", padx=16, pady=(4, 0))
        tk.Label(track_row, text="Track for selected file:", bg=BG, fg=FG2,
                 font=FONT_LABEL, width=22, anchor="w").pack(side="left")
        sp_frame = tk.Frame(track_row, bg=BORDER, padx=1, pady=1)
        sp_frame.pack(side="left")
        tk.Spinbox(sp_frame, from_=0, to=MERGE_TRACK_MAX - 1,
                   textvariable=self.track_sel_var, width=2,
                   bg=SURFACE, fg=ACCENT, insertbackground=ACCENT,
                   buttonbackground=SURFACE2, font=FONT_MONO,
                   borderwidth=0, highlightthickness=0,
                   ).pack(padx=4, pady=3)
        self._mk_btn(track_row, "ASSIGN", self._assign_track_to_selected).pack(
            side="left", padx=(6, 0))
        tk.Label(self.merge_frame,
                 text="  Select a file in the list, change the track (0-7) and press ASSIGN",
                 bg=BG, fg=FG3, font=FONT_HINT, anchor="w").pack(fill="x", padx=20, pady=(2, 0))
        tk.Label(self.merge_frame,
                 text="  All files → one .mtp  |  max 8 files per pattern  |  monophonic per track",
                 bg=BG, fg=FG3, font=FONT_HINT, anchor="w").pack(fill="x", padx=20, pady=(0, 4))

        # ── Split frame (visible by default) ────────────────────
        self.split_frame = tk.Frame(self.mode_content, bg=BG)
        tk.Label(self.split_frame,
                 text="  Each MIDI file becomes a separate .mtp pattern (pattern_01, _02 ...)",
                 bg=BG, fg=FG3, font=FONT_HINT, anchor="w").pack(fill="x", padx=4, pady=(0, 2))
        tk.Label(self.split_frame,
                 text="  Chords: simultaneous notes are automatically spread across separate tracks",
                 bg=BG, fg=FG3, font=FONT_HINT, anchor="w").pack(fill="x", padx=4, pady=(0, 4))
        self.split_frame.pack(fill="x")

        self._style_radio_buttons(self)

    def _build_output_section(self):
        _section_title(self, "OUTPUT")

        # folder
        row1 = tk.Frame(self, bg=BG)
        row1.pack(fill="x", padx=16, pady=(0, 6))
        tk.Label(row1, text="Folder:", bg=BG, fg=FG2,
                 font=FONT_LABEL, width=10, anchor="w").pack(side="left")

        dir_frame = tk.Frame(row1, bg=BORDER, padx=1, pady=1)
        dir_frame.pack(side="left", fill="x", expand=True)
        tk.Entry(dir_frame, textvariable=self.out_dir_var,
                 bg=SURFACE, fg=FG, insertbackground=ACCENT,
                 font=FONT_MONO, borderwidth=0, highlightthickness=0
                 ).pack(fill="both", padx=4, pady=3)

        self._mk_btn(row1, "BROWSE", self._browse_output).pack(side="left", padx=(8, 0))

        # filename pattern + index
        row2 = tk.Frame(self, bg=BG)
        row2.pack(fill="x", padx=16, pady=(0, 4))
        tk.Label(row2, text="Filename:", bg=BG, fg=FG2,
                 font=FONT_LABEL, width=10, anchor="w").pack(side="left")
        tk.Label(row2, text="pattern_", bg=BG, fg=FG, font=FONT_MONO).pack(side="left")

        idx_frame = tk.Frame(row2, bg=BORDER, padx=1, pady=1)
        idx_frame.pack(side="left")
        tk.Spinbox(idx_frame, from_=1, to=255, textvariable=self.index_var, width=3,
                   bg=SURFACE, fg=ACCENT, insertbackground=ACCENT,
                   buttonbackground=SURFACE2, disabledbackground=SURFACE,
                   font=FONT_MONO, borderwidth=0, highlightthickness=0,
                   format="%02.0f",
                   ).pack(padx=4, pady=3)

        tk.Label(row2, text=".mtp  (auto-incremented per file)",
                 bg=BG, fg=FG3, font=FONT_SUB).pack(side="left", padx=(4, 0))
        _hint(self, "SD card path:  /projects/<project_name>/patterns/pattern_NN.mtp")

    def _build_options_section(self):
        _section_title(self, "OPTIONS")

        # Resolution
        row1 = tk.Frame(self, bg=BG)
        row1.pack(fill="x", padx=16, pady=(0, 8))
        tk.Label(row1, text="Resolution:", bg=BG, fg=FG2,
                 font=FONT_LABEL, width=13, anchor="w").pack(side="left")

        for label, val in [("1/16", 16), ("1/8", 8), ("1/4", 4)]:
            rb = tk.Radiobutton(
                row1, text=label, variable=self.res_var, value=val,
                bg=BG, fg=FG, selectcolor=BG,
                activebackground=BG, activeforeground=ACCENT,
                font=FONT_MONO,
                indicatoron=0,
                relief="flat", borderwidth=0,
                padx=10, pady=4,
                command=lambda v=val: self._on_res(v),
            )
            rb.pack(side="left", padx=(0, 6))
        self._radio_btns_res = row1.winfo_children()[1:]
        self._update_radio_styles()
        _hint(self, "1/16 = finest step  |  1/8 = eighth note steps  |  1/4 = one note per beat")

        # Instrument
        row2 = tk.Frame(self, bg=BG)
        row2.pack(fill="x", padx=16, pady=(6, 0))
        tk.Label(row2, text="Instrument:", bg=BG, fg=FG2,
                 font=FONT_LABEL, width=13, anchor="w").pack(side="left")

        sp_frame = tk.Frame(row2, bg=BORDER, padx=1, pady=1)
        sp_frame.pack(side="left")
        tk.Spinbox(sp_frame, from_=0, to=47, textvariable=self.instr_var, width=3,
                   bg=SURFACE, fg=ACCENT, insertbackground=ACCENT,
                   buttonbackground=SURFACE2,
                   font=FONT_MONO, borderwidth=0, highlightthickness=0,
                   format="%02.0f",
                   ).pack(padx=4, pady=3)
        tk.Label(row2, text="(0 – 47)", bg=BG, fg=FG3, font=FONT_SUB).pack(side="left", padx=6)
        _hint(self, "Instrument slot assigned to all notes in the pattern (0 = first instrument)")

    def _build_convert_btn(self):
        frame = tk.Frame(self, bg=BG)
        frame.pack(fill="x", padx=16, pady=(4, 8))

        self.conv_btn = tk.Button(
            frame,
            text="▶  CONVERT",
            font=FONT_CONV,
            bg=ACCENT, fg=BG,
            activebackground=ACCENT_H, activeforeground=BG,
            relief="flat", borderwidth=0,
            padx=20, pady=12,
            cursor="hand2",
            command=self._start_convert,
        )
        self.conv_btn.pack(fill="x")

        self.progress_lbl = tk.Label(self, text="", bg=BG, fg=FG2, font=FONT_LOG)
        self.progress_lbl.pack()

    def _build_log_section(self):
        _section_title(self, "LOG")

        log_frame = tk.Frame(self, bg=BORDER, padx=1, pady=1)
        log_frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        inner = tk.Frame(log_frame, bg=SURFACE)
        inner.pack(fill="both", expand=True)

        self.log_txt = tk.Text(
            inner,
            bg=SURFACE, fg=FG2, insertbackground=ACCENT,
            font=FONT_LOG, borderwidth=0, highlightthickness=0,
            state="disabled", height=8, wrap="word",
        )
        sb = tk.Scrollbar(inner, orient="vertical", command=self.log_txt.yview,
                          bg=SURFACE2, troughcolor=SURFACE, activebackground=ACCENT_D,
                          relief="flat", width=10)
        self.log_txt.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_txt.pack(side="left", fill="both", expand=True, padx=6, pady=4)

        # Tag colors
        self.log_txt.tag_config("ok",   foreground=OK)
        self.log_txt.tag_config("err",  foreground=ERR)
        self.log_txt.tag_config("acc",  foreground=ACCENT)
        self.log_txt.tag_config("dim",  foreground=FG3)
        self.log_txt.tag_config("info", foreground=FG2)
        self.log_txt.tag_config("head", foreground=ACCENT)

    # ── Help & Welcome ──────────────────────────────────────────

    def _show_welcome(self):
        lines = [
            ("MIDI → MTP  |  Quick start", "head"),
            ("─" * 52, "dim"),
            ("", None),
            ("1. Add one or more .mid files with + ADD", "info"),
            ("2. Choose the output folder with BROWSE", "info"),
            ("   → Recommended: /projects/<name>/patterns/ on the SD card", "dim"),
            ("3. Set the starting index (e.g. 01 → pattern_01.mtp)", "info"),
            ("4. Choose resolution and instrument slot", "info"),
            ("5. Press CONVERT", "info"),
            ("", None),
            ("─" * 52, "dim"),
            ("CHORDS – how chord spreading works:", "acc"),
            ("  Notes played simultaneously on the same step are", "info"),
            ("  distributed across consecutive tracker tracks,", "info"),
            ("  matching the Polyend Tracker firmware behaviour.", "info"),
            ("", None),
            ("  Example: C4 + E4 + G4 on step 0:", "dim"),
            ("    track 0 → G4  (highest voice)", "ok"),
            ("    track 1 → E4", "ok"),
            ("    track 2 → C4  (lowest voice)", "ok"),
            ("", None),
            ("  Max polyphony: 11 voices (11 tracks available)", "dim"),
            ("─" * 52, "dim"),
        ]
        for text, tag in lines:
            self._log(text, tag=tag)

    def _open_help(self):
        win = tk.Toplevel(self)
        win.title("Help")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.grab_set()

        # Center relative to main window
        self.update_idletasks()
        px, py = self.winfo_x(), self.winfo_y()
        pw, ph = self.winfo_width(), self.winfo_height()
        w, h = 560, 540
        win.geometry(f"{w}x{h}+{px + (pw - w)//2}+{py + (ph - h)//2}")

        # Title
        tk.Label(win, text="MIDI \u2192 MTP  |  Help", bg=BG, fg=ACCENT,
                 font=("Courier", 14, "bold")).pack(padx=20, pady=(16, 4), anchor="w")
        tk.Frame(win, bg=LINE, height=1).pack(fill="x", padx=16, pady=(0, 10))

        # Scrollable text
        frame = tk.Frame(win, bg=BORDER, padx=1, pady=1)
        frame.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        inner = tk.Frame(frame, bg=SURFACE)
        inner.pack(fill="both", expand=True)

        txt = tk.Text(inner, bg=SURFACE, fg=FG, font=FONT_HELP,
                      borderwidth=0, highlightthickness=0,
                      state="disabled", wrap="word", padx=10, pady=8)
        sb = tk.Scrollbar(inner, orient="vertical", command=txt.yview,
                          bg=SURFACE2, troughcolor=SURFACE,
                          activebackground=ACCENT_D, relief="flat", width=10)
        txt.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)

        txt.tag_config("h",    foreground=ACCENT,  font=("Courier", 11, "bold"))
        txt.tag_config("ok",   foreground=OK)
        txt.tag_config("dim",  foreground=FG3)
        txt.tag_config("warn", foreground="#FFCC44")
        txt.tag_config("body", foreground=FG)

        HELP_TEXT = [
            ("WORKFLOW\n", "h"),
            ("1. Add .mid files with + ADD (multiple selection supported).\n", "body"),
            ("2. Choose the output folder with BROWSE.\n", "body"),
            ("   Recommended SD card path:\n", "dim"),
            ("   /projects/<project_name>/patterns/\n", "ok"),
            ("3. Set the starting index (e.g. 01).\n", "body"),
            ("   Each file is saved as pattern_NN.mtp\n", "dim"),
            ("   with NN auto-incremented for each file.\n", "dim"),
            ("4. Choose Resolution and Instrument.\n", "body"),
            ("5. Press CONVERT.\n", "body"),
            ("\n", None),
            ("RESOLUTION\n", "h"),
            ("Sets the minimum quantization step for notes:\n", "body"),
            ("  1/16  →  minimum step = sixteenth note  (default)\n", "ok"),
            ("  1/8   →  minimum step = eighth note\n", "body"),
            ("  1/4   →  minimum step = quarter note\n", "body"),
            ("Use 1/16 for most MIDI files.\n", "dim"),
            ("\n", None),
            ("INSTRUMENT\n", "h"),
            ("Instrument slot (0-47) assigned to all notes.\n", "body"),
            ("Corresponds to instruments loaded in the project\n", "body"),
            ("on the Polyend Tracker (slot 0 = first instrument).\n", "dim"),
            ("\n", None),
            ("CHORDS – CHORD SPREADING\n", "h"),
            ("When multiple notes land on the same step,\n", "body"),
            ("they are spread across consecutive tracks,\n", "body"),
            ("matching the Polyend Tracker firmware behaviour\n", "body"),
            ("when receiving chords via MIDI IN.\n", "body"),
            ("\n", None),
            ("Example – C major chord (C4+E4+G4) on step 0:\n", "dim"),
            ("  Track 0, step 0  →  G4  (highest voice)\n", "ok"),
            ("  Track 1, step 0  →  E4\n", "ok"),
            ("  Track 2, step 0  →  C4  (lowest voice)\n", "ok"),
            ("\n", None),
            ("Maximum polyphony: 11 simultaneous voices.\n", "body"),
            ("Excess notes are discarded (reported in the log).\n", "warn"),
            ("\n", None),
            ("MIDI FILE TYPES\n", "h"),
            ("Type 0 (single track):\n", "body"),
            ("  Each MIDI channel = separate source for\n", "dim"),
            ("  chord spreading (ch 0, ch 1, ... treated independently).\n", "dim"),
            ("Type 1 (multi track):\n", "body"),
            ("  Each MIDI track = separate source.\n", "dim"),
            ("\n", None),
            ("PATTERN LENGTH\n", "h"),
            ("Calculated automatically and rounded up to the\n", "body"),
            ("nearest multiple of 16: 16, 32, 64, 128 (max).\n", "dim"),
        ]

        txt.config(state="normal")
        for text, tag in HELP_TEXT:
            txt.insert("end", text, tag or "body")
        txt.config(state="disabled")

        # Close button
        tk.Button(
            win, text="CLOSE",
            bg=SURFACE2, fg=FG2,
            activebackground=SURFACE, activeforeground=ACCENT,
            relief="flat", borderwidth=0, padx=20, pady=8,
            font=FONT_LOG, cursor="hand2",
            command=win.destroy,
        ).pack(pady=(0, 16))

    # ── Button factory ─────────────────────────────────────────

    def _mk_btn(self, parent, text, cmd):
        return tk.Button(
            parent, text=text, command=cmd,
            bg=SURFACE2, fg=FG2,
            activebackground=SURFACE, activeforeground=ACCENT,
            relief="flat", borderwidth=0, padx=10, pady=5,
            font=FONT_LOG, cursor="hand2",
        )

    # ── Events ─────────────────────────────────────────────────

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            title="Choose MIDI files",
            filetypes=[("MIDI files", "*.mid *.midi"), ("All files", "*")],
        )
        merge  = self.mode_var.get() == "merge"
        added  = 0
        for p in paths:
            if p not in self.midi_files:
                # in merge mode: track 0-7, then wraps to next pattern
                auto_track = len(self.midi_files) % MERGE_TRACK_MAX
                self.midi_files.append(p)
                self.track_assignments.append(auto_track)
                added += 1
        if added:
            self._log(f"Added {added} file(s).", tag="acc")
            if merge:
                n_patterns = (len(self.midi_files) + MERGE_TRACK_MAX - 1) // MERGE_TRACK_MAX
                self._log(f"  \u2192 {len(self.midi_files)} files across {n_patterns} pattern(s)", tag="info")
        self._refresh_listbox()
        self._update_files_label()

    def _remove_file(self):
        sel = self.file_list.curselection()
        for i in reversed(sel):
            removed = self.midi_files.pop(i)
            if i < len(self.track_assignments):
                self.track_assignments.pop(i)
            self._log(f"Removed: {Path(removed).name}", tag="dim")
        self._refresh_listbox()
        self._update_files_label()

    def _clear_files(self):
        self.midi_files.clear()
        self.track_assignments.clear()
        self.file_list.delete(0, "end")
        self._update_files_label()
        self._log("File list cleared.", tag="dim")

    # -- Mode helpers ────────────────────────────────────────────

    def _on_mode_change(self):
        mode = self.mode_var.get()
        if mode == "merge":
            self.split_frame.pack_forget()
            self.merge_frame.pack(fill="x")
            self._log("Mode MERGE: all files \u2192 one .mtp pattern", tag="acc")
            self._log("  Assign each file to a track (0-7) using the selector.", tag="info")
        else:
            self.merge_frame.pack_forget()
            self.split_frame.pack(fill="x")
            self._log("Mode SEPARATE: each MIDI file \u2192 individual .mtp pattern", tag="acc")
        self._refresh_listbox()
        self._style_radio_buttons(self)

    def _on_file_select(self, event=None):
        if self.mode_var.get() != "merge":
            return
        sel = self.file_list.curselection()
        if sel:
            idx = sel[0]
            if idx < len(self.track_assignments):
                self.track_sel_var.set(self.track_assignments[idx])

    def _refresh_listbox(self):
        merge = self.mode_var.get() == "merge"
        self.file_list.delete(0, "end")
        for i, p in enumerate(self.midi_files):
            if merge:
                p_idx = i // MERGE_TRACK_MAX  # destination pattern
                t_idx = i % MERGE_TRACK_MAX   # track within that pattern
                self.file_list.insert("end", f" [P{p_idx} T{t_idx}]  {Path(p).name}")
            else:
                self.file_list.insert("end", f" {Path(p).name}")

    def _assign_track_to_selected(self):
        sel = self.file_list.curselection()
        if not sel:
            self._log("  Select a file from the list first.", tag="dim")
            return
        new_track = self.track_sel_var.get()
        idx = sel[0]
        self.track_assignments[idx] = new_track
        self._refresh_listbox()
        self.file_list.selection_set(idx)
        fname = Path(self.midi_files[idx]).name
        self._log(f"  {fname}  \u2192  Track {new_track}", tag="acc")

    def _browse_output(self):
        d = filedialog.askdirectory(title="Choose output folder")
        if d:
            self.out_dir_var.set(d)
            self._log(f"Output → {d}", tag="acc")

    def _on_res(self, val):
        self.res_var.set(val)
        self._update_radio_styles()

    def _update_radio_styles(self):
        frame = self.winfo_children()
        # scan all radio buttons and re-color based on current selection
        self._style_radio_buttons(self)

    def _style_radio_buttons(self, parent):
        for child in parent.winfo_children():
            if isinstance(child, tk.Radiobutton):
                val = child.cget("value")
                selected = (val == str(self.res_var.get())) or (val == self.mode_var.get())
                if selected:
                    child.config(bg=ACCENT_D, fg=ACCENT, relief="flat")
                else:
                    child.config(bg=SURFACE2, fg=FG2, relief="flat")
            else:
                self._style_radio_buttons(child)

    def _update_files_label(self):
        n = len(self.midi_files)
        self.files_lbl.config(
            text=f"{n} file{'s' if n != 1 else ''} selected",
            fg=ACCENT if n > 0 else FG3,
        )

    # ── Conversion ─────────────────────────────────────────────

    def _start_convert(self):
        if self.converting:
            return

        if mido is None:
            messagebox.showerror("Error", "Library 'mido' is not installed.\n\npip install mido")
            return

        if not self.midi_files:
            messagebox.showwarning("No files", "Add at least one MIDI file.")
            return

        out_dir = self.out_dir_var.get().strip()
        if not out_dir:
            messagebox.showwarning("Missing folder", "Select the output folder.")
            return

        out_path = Path(out_dir)
        if not out_path.exists():
            messagebox.showerror("Error", f"Folder does not exist:\n{out_dir}")
            return

        self.converting = True
        self.conv_btn.config(state="disabled", bg=ACCENT_D, text="\u25cc  Converting\u2026")
        self.progress_lbl.config(text="")

        threading.Thread(target=self._convert_thread, daemon=True).start()

    def _convert_thread(self):
        out_path       = Path(self.out_dir_var.get())
        start_idx      = self.index_var.get()
        resolution     = self.res_var.get()
        instrument     = self.instr_var.get()
        mode           = self.mode_var.get()
        steps_per_beat = resolution // 4  # 16→4, 8→2, 4→1

        if mode == "merge":
            self._convert_thread_merge(out_path, start_idx, steps_per_beat, instrument)
            return

        ok_count  = 0
        err_count = 0
        self._log(f"\n── Converting {len(self.midi_files)} file(s) ──────────────────", tag="acc")

        for i, midi_path in enumerate(self.midi_files):
            pattern_idx  = start_idx + i
            output_name  = f"pattern_{pattern_idx:02d}.mtp"
            output_file  = out_path / output_name
            fname        = Path(midi_path).name
            self._set_progress(f"{i+1}/{len(self.midi_files)}  {fname}")
            try:
                mid = mido.MidiFile(str(midi_path))
                tracks_data, pattern_length = midi_to_tracks(
                    mid,
                    steps_per_beat=steps_per_beat,
                    default_instrument=instrument,
                    verbose=False,
                )
                mtp_data = build_mtp(tracks_data, pattern_length)
                output_file.write_bytes(mtp_data)
                used = sum(1 for td in tracks_data if any(
                    s.get("note", STEP_NOTE_EMPTY) != STEP_NOTE_EMPTY
                    for s in td.get("steps", [])
                ))
                self._log(
                    f"  \u2713  {fname}  \u2192  {output_name}  ({pattern_length} steps, {used} tracks)",
                    tag="ok",
                )
                ok_count += 1
            except Exception as e:
                self._log(f"  ✗  {fname}  →  {e}", tag="err")
                err_count += 1

        self._log(
            f"\n── Done: {ok_count} OK  |  {err_count} error(s) ──────────────",
            tag="acc" if err_count == 0 else "err",
        )
        self._finish_convert(ok_count, err_count)

    def _convert_thread_merge(self, out_path, start_idx, steps_per_beat, instrument):
        n_files     = len(self.midi_files)
        n_patterns  = (n_files + MERGE_TRACK_MAX - 1) // MERGE_TRACK_MAX

        self._log(
            f"\n── MERGE {n_files} file(s) → {n_patterns} pattern(s) ──────────────",
            tag="acc",
        )

        # Phase 1: load all MIDI files
        loaded = []  # list of (mido.MidiFile | None, fname)
        load_err = 0
        for i, midi_path in enumerate(self.midi_files):
            fname = Path(midi_path).name
            self._set_progress(f"Loading {i+1}/{n_files}  {fname}")
            try:
                mid = mido.MidiFile(str(midi_path))
                loaded.append((mid, fname))
            except Exception as e:
                self._log(f"  ✗  {fname}  →  {e}", tag="err")
                loaded.append((None, fname))
                load_err += 1

        if load_err:
            self._log(f"  {load_err} file(s) could not be loaded \u2014 continuing with the rest.", tag="err")

        # Phase 2: write one pattern per chunk of MERGE_TRACK_MAX files
        ok_patterns  = 0
        err_patterns = 0

        for chunk_idx in range(n_patterns):
            chunk_start = chunk_idx * MERGE_TRACK_MAX
            chunk       = loaded[chunk_start : chunk_start + MERGE_TRACK_MAX]
            pat_idx     = start_idx + chunk_idx
            output_name = f"pattern_{pat_idx:02d}.mtp"
            output_file = out_path / output_name

            self._log(f"\n  Pattern {pat_idx:02d} ({len(chunk)} track(s)):", tag="acc")

            # remap to local tracks 0..len(chunk)-1, skip None entries
            assignments = []
            for local_track, (mid, fname) in enumerate(chunk):
                if mid is not None:
                    assignments.append((mid, local_track, instrument))
                    self._log(f"    ● {fname}  →  Track {local_track}", tag="info")
                else:
                    self._log(f"    ✗  {fname}  (skipped)", tag="err")

            if not assignments:
                self._log(f"    No valid files in this chunk, pattern skipped.", tag="err")
                err_patterns += 1
                continue

            try:
                self._set_progress(f"Pattern {pat_idx:02d} \u2013 merging {len(assignments)} file(s)\u2026")
                tracks_data, pattern_length = merge_midi_files_to_tracks(
                    assignments,
                    steps_per_beat=steps_per_beat,
                    verbose=False,
                )
                mtp_data = build_mtp(tracks_data, pattern_length)
                output_file.write_bytes(mtp_data)
                used = sum(1 for td in tracks_data if any(
                    s.get("note", STEP_NOTE_EMPTY) != STEP_NOTE_EMPTY
                    for s in td.get("steps", [])
                ))
                self._log(
                    f"    \u2713  Saved: {output_name}  ({pattern_length} steps, {used} track(s) used)",
                    tag="ok",
                )
                ok_patterns += 1
            except Exception as e:
                self._log(f"    \u2717  Error: {e}", tag="err")
                err_patterns += 1

        self._log(
            f"\n\u2500\u2500 Done: {ok_patterns} pattern(s) OK  |  {err_patterns} error(s) \u2500\u2500",
            tag="acc" if err_patterns == 0 else "err",
        )
        self._finish_convert(ok_patterns, err_patterns)

    def _finish_convert(self, ok, err):
        def _ui():
            self.converting = False
            self.conv_btn.config(state="normal", bg=ACCENT, text="\u25b6  CONVERT")
            if err == 0:
                self.progress_lbl.config(
                    text=f"Done: {ok} file(s) converted successfully.",
                    fg=OK,
                )
            else:
                self.progress_lbl.config(
                    text=f"Completed with errors: {ok} OK  /  {err} failed.",
                    fg=ERR,
                )
        self.after(0, _ui)

    def _set_progress(self, text):
        self.after(0, lambda: self.progress_lbl.config(text=text, fg=FG2))

    # ── Logging ────────────────────────────────────────────────

    def _log(self, msg, tag=None):
        def _write():
            self.log_txt.config(state="normal")
            self.log_txt.insert("end", msg + "\n", tag or "")
            self.log_txt.config(state="disabled")
            self.log_txt.see("end")
        self.after(0, _write)


# ─────────────────────────────────────────────────────────────

def main():
    app = App()
    # Center the window on screen
    app.update_idletasks()
    w, h = 580, 740
    sx = (app.winfo_screenwidth()  - w) // 2
    sy = (app.winfo_screenheight() - h) // 2
    app.geometry(f"{w}x{h}+{sx}+{sy}")
    app.mainloop()


if __name__ == "__main__":
    main()
