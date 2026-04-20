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
    """Riga di testo grigio-scuro per istruzioni contestuali."""
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
        self.track_assignments = []            # parallelo a midi_files – track per file (merge mode)
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
        _section_title(self, "FILE MIDI")

        # ── Modalità toggle ────────────────────────────────────
        mode_row = tk.Frame(self, bg=BG)
        mode_row.pack(fill="x", padx=16, pady=(0, 6))
        tk.Label(mode_row, text="Modalità:", bg=BG, fg=FG2,
                 font=FONT_LABEL, width=10, anchor="w").pack(side="left")
        for label, val in [("UN FILE = UN PATTERN", "split"),
                            ("PIÙ FILE = UN PATTERN", "merge")]:
            rb = tk.Radiobutton(
                mode_row, text=label, variable=self.mode_var, value=val,
                bg=BG, fg=FG, selectcolor=BG,
                activebackground=BG, activeforeground=ACCENT,
                font=FONT_HINT, indicatoron=0, relief="flat", borderwidth=0,
                padx=8, pady=4,
                command=self._on_mode_change,
            )
            rb.pack(side="left", padx=(0, 6))

        # ── File list + buttons ─────────────────────────────────
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
        self._mk_btn(btn_col, "+ AGGIUNGI", self._add_files).pack(fill="x", pady=(0, 4))
        self._mk_btn(btn_col, "− RIMUOVI",  self._remove_file).pack(fill="x", pady=(0, 4))
        self._mk_btn(btn_col, "✕ SVUOTA",   self._clear_files).pack(fill="x")

        # ── Counter ─────────────────────────────────────────────
        self.files_lbl = tk.Label(self, text="0 file selezionati",
                                  bg=BG, fg=FG3, font=FONT_LOG, anchor="w")
        self.files_lbl.pack(fill="x", padx=20, pady=(2, 0))

        # ── Contenuto dipendente dalla modalità ─────────────────
        self.mode_content = tk.Frame(self, bg=BG)
        self.mode_content.pack(fill="x")

        # ── Merge frame (nascosto inizialmente) ─────────────────
        self.merge_frame = tk.Frame(self.mode_content, bg=BG)
        track_row = tk.Frame(self.merge_frame, bg=BG)
        track_row.pack(fill="x", padx=16, pady=(4, 0))
        tk.Label(track_row, text="Track file selezionato:", bg=BG, fg=FG2,
                 font=FONT_LABEL, width=22, anchor="w").pack(side="left")
        sp_frame = tk.Frame(track_row, bg=BORDER, padx=1, pady=1)
        sp_frame.pack(side="left")
        tk.Spinbox(sp_frame, from_=0, to=MERGE_TRACK_MAX - 1,
                   textvariable=self.track_sel_var, width=2,
                   bg=SURFACE, fg=ACCENT, insertbackground=ACCENT,
                   buttonbackground=SURFACE2, font=FONT_MONO,
                   borderwidth=0, highlightthickness=0,
                   ).pack(padx=4, pady=3)
        self._mk_btn(track_row, "ASSEGNA", self._assign_track_to_selected).pack(
            side="left", padx=(6, 0))
        tk.Label(self.merge_frame,
                 text="  Seleziona un file nella lista, poi cambia la track (0–7) e premi ASSEGNA",
                 bg=BG, fg=FG3, font=FONT_HINT, anchor="w").pack(fill="x", padx=20, pady=(2, 0))
        tk.Label(self.merge_frame,
                 text="  Tutti i file → un solo .mtp  |  max 8 file  |  monophonic per track",
                 bg=BG, fg=FG3, font=FONT_HINT, anchor="w").pack(fill="x", padx=20, pady=(0, 4))

        # ── Split frame (visibile di default) ───────────────────
        self.split_frame = tk.Frame(self.mode_content, bg=BG)
        tk.Label(self.split_frame,
                 text="  Ogni file MIDI diventa un pattern .mtp separato (pattern_01, _02 …)",
                 bg=BG, fg=FG3, font=FONT_HINT, anchor="w").pack(fill="x", padx=4, pady=(0, 2))
        tk.Label(self.split_frame,
                 text="  Accordi: note simultanee vengono distribuite automaticamente su track diverse",
                 bg=BG, fg=FG3, font=FONT_HINT, anchor="w").pack(fill="x", padx=4, pady=(0, 4))
        self.split_frame.pack(fill="x")

        self._style_radio_buttons(self)

    def _build_output_section(self):
        _section_title(self, "OUTPUT")

        # folder
        row1 = tk.Frame(self, bg=BG)
        row1.pack(fill="x", padx=16, pady=(0, 6))
        tk.Label(row1, text="Cartella:", bg=BG, fg=FG2,
                 font=FONT_LABEL, width=10, anchor="w").pack(side="left")

        dir_frame = tk.Frame(row1, bg=BORDER, padx=1, pady=1)
        dir_frame.pack(side="left", fill="x", expand=True)
        tk.Entry(dir_frame, textvariable=self.out_dir_var,
                 bg=SURFACE, fg=FG, insertbackground=ACCENT,
                 font=FONT_MONO, borderwidth=0, highlightthickness=0
                 ).pack(fill="both", padx=4, pady=3)

        self._mk_btn(row1, "SFOGLIA", self._browse_output).pack(side="left", padx=(8, 0))

        # filename pattern + index
        row2 = tk.Frame(self, bg=BG)
        row2.pack(fill="x", padx=16, pady=(0, 4))
        tk.Label(row2, text="Nome file:", bg=BG, fg=FG2,
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

        tk.Label(row2, text=".mtp  (incrementato per ogni file)",
                 bg=BG, fg=FG3, font=FONT_SUB).pack(side="left", padx=(4, 0))
        _hint(self, "Percorso SD card:  /projects/<nome_progetto>/patterns/pattern_NN.mtp")

    def _build_options_section(self):
        _section_title(self, "OPZIONI")

        # Resolution
        row1 = tk.Frame(self, bg=BG)
        row1.pack(fill="x", padx=16, pady=(0, 8))
        tk.Label(row1, text="Risoluzione:", bg=BG, fg=FG2,
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
        _hint(self, "1/16 = passo minimo 1/16  |  1/8 = 1/8  |  1/4 = una nota per beat")

        # Instrument
        row2 = tk.Frame(self, bg=BG)
        row2.pack(fill="x", padx=16, pady=(6, 0))
        tk.Label(row2, text="Strumento:", bg=BG, fg=FG2,
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
        _hint(self, "Slot strumento che verrà assegnato a tutte le note del pattern")

    def _build_convert_btn(self):
        frame = tk.Frame(self, bg=BG)
        frame.pack(fill="x", padx=16, pady=(4, 8))

        self.conv_btn = tk.Button(
            frame,
            text="▶  CONVERTI",
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
            ("MIDI → MTP  |  Guida rapida", "head"),
            ("─" * 52, "dim"),
            ("", None),
            ("1. Aggiungi uno o più file .mid con + AGGIUNGI", "info"),
            ("2. Scegli la cartella di output con SFOGLIA", "info"),
            ("   → Ideale: /projects/<nome>/patterns/ sulla SD card", "dim"),
            ("3. Imposta l'indice di partenza (es. 01 → pattern_01.mtp)", "info"),
            ("4. Scegli la risoluzione e lo strumento", "info"),
            ("5. Premi CONVERTI", "info"),
            ("", None),
            ("─" * 52, "dim"),
            ("ACCORDI – come funziona il chord spreading:", "acc"),
            ("  Note suonate insieme nello stesso step vengono", "info"),
            ("  distribuite su track consecutive del tracker,", "info"),
            ("  esattamente come fa il firmware Polyend via MIDI IN.", "info"),
            ("", None),
            ("  Es: C4 + E4 + G4 allo step 0:", "dim"),
            ("    track 0 → G4  (voce più alta)", "ok"),
            ("    track 1 → E4", "ok"),
            ("    track 2 → C4  (voce più bassa)", "ok"),
            ("", None),
            ("  Polifonia massima: 11 voci (11 track disponibili)", "dim"),
            ("─" * 52, "dim"),
        ]
        for text, tag in lines:
            self._log(text, tag=tag)

    def _open_help(self):
        win = tk.Toplevel(self)
        win.title("Guida")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.grab_set()

        # Centra rispetto alla finestra principale
        self.update_idletasks()
        px, py = self.winfo_x(), self.winfo_y()
        pw, ph = self.winfo_width(), self.winfo_height()
        w, h = 560, 540
        win.geometry(f"{w}x{h}+{px + (pw - w)//2}+{py + (ph - h)//2}")

        # Titolo
        tk.Label(win, text="MIDI → MTP  |  Guida", bg=BG, fg=ACCENT,
                 font=("Courier", 14, "bold")).pack(padx=20, pady=(16, 4), anchor="w")
        tk.Frame(win, bg=LINE, height=1).pack(fill="x", padx=16, pady=(0, 10))

        # Testo scrollabile
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
            ("FLUSSO DI LAVORO\n", "h"),
            ("1. Aggiungi i file .mid con + AGGIUNGI (anche multipli).\n", "body"),
            ("2. Scegli la cartella di output con SFOGLIA.\n", "body"),
            ("   Percorso SD card consigliato:\n", "dim"),
            ("   /projects/<nome_progetto>/patterns/\n", "ok"),
            ("3. Imposta l'Indice di partenza (es. 01).\n", "body"),
            ("   Ogni file viene salvato come pattern_NN.mtp\n", "dim"),
            ("   con NN che si incrementa automaticamente.\n", "dim"),
            ("4. Scegli Risoluzione e Strumento.\n", "body"),
            ("5. Premi CONVERTI.\n", "body"),
            ("\n", None),
            ("RISOLUZIONE\n", "h"),
            ("Definisce il passo minimo di quantizzazione delle note:\n", "body"),
            ("  1/16  →  passo minimo = una semicroma  (default)\n", "ok"),
            ("  1/8   →  passo minimo = una croma\n", "body"),
            ("  1/4   →  passo minimo = un quarto (quarter note)\n", "body"),
            ("Usa 1/16 per la maggior parte dei file MIDI.\n", "dim"),
            ("\n", None),
            ("STRUMENTO\n", "h"),
            ("Slot strumento (0–47) assegnato a tutte le note.\n", "body"),
            ("Corrisponde agli strumenti caricati nel progetto\n", "body"),
            ("sul Polyend Tracker (slot 0 = primo strumento).\n", "dim"),
            ("\n", None),
            ("ACCORDI – CHORD SPREADING\n", "h"),
            ("Quando più note vanno allo stesso step,\n", "body"),
            ("vengono distribuite su track consecutive,\n", "body"),
            ("esattamente come fa il firmware Polyend\n", "body"),
            ("quando riceve un accordo via MIDI IN.\n", "body"),
            ("\n", None),
            ("Esempio – Do maggiore (C4+E4+G4) allo step 0:\n", "dim"),
            ("  Track 0, step 0  →  G4  (voce più alta)\n", "ok"),
            ("  Track 1, step 0  →  E4\n", "ok"),
            ("  Track 2, step 0  →  C4  (voce più bassa)\n", "ok"),
            ("\n", None),
            ("Polifonia massima: 11 voci simultanee.\n", "body"),
            ("Note in eccesso vengono scartate (segnalate nel log).\n", "warn"),
            ("\n", None),
            ("TIPI DI FILE MIDI\n", "h"),
            ("Type 0 (single track):\n", "body"),
            ("  Ogni canale MIDI = sorgente separata per il\n", "dim"),
            ("  chord spreading (ch 0, ch 1, … trattati distinti).\n", "dim"),
            ("Type 1 (multi track):\n", "body"),
            ("  Ogni MIDI track = sorgente separata.\n", "dim"),
            ("\n", None),
            ("LUNGHEZZA PATTERN\n", "h"),
            ("Calcolata automaticamente, arrotondata al multiplo\n", "body"),
            ("di 16 step successivo: 16, 32, 64, 128 (max).\n", "dim"),
        ]

        txt.config(state="normal")
        for text, tag in HELP_TEXT:
            txt.insert("end", text, tag or "body")
        txt.config(state="disabled")

        # Pulsante chiudi
        tk.Button(
            win, text="CHIUDI",
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
            title="Scegli file MIDI",
            filetypes=[("MIDI files", "*.mid *.midi"), ("All files", "*")],
        )
        merge  = self.mode_var.get() == "merge"
        added  = 0
        for p in paths:
            if p not in self.midi_files:
                # in merge mode: track 0-7, poi si ricomincia da 0 nel pattern successivo
                auto_track = len(self.midi_files) % MERGE_TRACK_MAX
                self.midi_files.append(p)
                self.track_assignments.append(auto_track)
                added += 1
        if added:
            self._log(f"Aggiunti {added} file.", tag="acc")
            if merge:
                n_patterns = (len(self.midi_files) + MERGE_TRACK_MAX - 1) // MERGE_TRACK_MAX
                self._log(f"  → {len(self.midi_files)} file su {n_patterns} pattern", tag="info")
        self._refresh_listbox()
        self._update_files_label()

    def _remove_file(self):
        sel = self.file_list.curselection()
        for i in reversed(sel):
            removed = self.midi_files.pop(i)
            if i < len(self.track_assignments):
                self.track_assignments.pop(i)
            self._log(f"Rimosso: {Path(removed).name}", tag="dim")
        self._refresh_listbox()
        self._update_files_label()

    def _clear_files(self):
        self.midi_files.clear()
        self.track_assignments.clear()
        self.file_list.delete(0, "end")
        self._update_files_label()
        self._log("Lista svuotata.", tag="dim")

    # ── Mode helpers ────────────────────────────────────────────

    def _on_mode_change(self):
        mode = self.mode_var.get()
        if mode == "merge":
            self.split_frame.pack_forget()
            self.merge_frame.pack(fill="x")
            self._log("Modalità UNIFICA: tutti i file → un solo pattern .mtp", tag="acc")
            self._log("  Assegna ogni file a una track (0–7) con il selettore.", tag="info")
        else:
            self.merge_frame.pack_forget()
            self.split_frame.pack(fill="x")
            self._log("Modalità SEPARATA: ogni file MIDI → pattern .mtp distinto", tag="acc")
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
                p_idx = i // MERGE_TRACK_MAX  # pattern di destinazione
                t_idx = i % MERGE_TRACK_MAX   # track dentro quel pattern
                self.file_list.insert("end", f" [P{p_idx} T{t_idx}]  {Path(p).name}")
            else:
                self.file_list.insert("end", f" {Path(p).name}")

    def _assign_track_to_selected(self):
        sel = self.file_list.curselection()
        if not sel:
            self._log("  Seleziona prima un file dalla lista.", tag="dim")
            return
        new_track = self.track_sel_var.get()
        idx = sel[0]
        self.track_assignments[idx] = new_track
        self._refresh_listbox()
        self.file_list.selection_set(idx)
        fname = Path(self.midi_files[idx]).name
        self._log(f"  {fname}  →  Track {new_track}", tag="acc")

    def _browse_output(self):
        d = filedialog.askdirectory(title="Scegli cartella di output")
        if d:
            self.out_dir_var.set(d)
            self._log(f"Output → {d}", tag="acc")

    def _on_res(self, val):
        self.res_var.set(val)
        self._update_radio_styles()

    def _update_radio_styles(self):
        frame = self.winfo_children()
        # scan all radio buttons in the options section and re-color
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
            text=f"{n} file selezionat{'o' if n == 1 else 'i'}",
            fg=ACCENT if n > 0 else FG3,
        )

    # ── Conversion ─────────────────────────────────────────────

    def _start_convert(self):
        if self.converting:
            return

        if mido is None:
            messagebox.showerror("Errore", "Libreria 'mido' non installata.\n\npip install mido")
            return

        if not self.midi_files:
            messagebox.showwarning("Nessun file", "Aggiungi almeno un file MIDI.")
            return

        out_dir = self.out_dir_var.get().strip()
        if not out_dir:
            messagebox.showwarning("Cartella mancante", "Seleziona la cartella di output.")
            return

        out_path = Path(out_dir)
        if not out_path.exists():
            messagebox.showerror("Errore", f"La cartella non esiste:\n{out_dir}")
            return

        self.converting = True
        self.conv_btn.config(state="disabled", bg=ACCENT_D, text="◌  Conversione in corso…")
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
        self._log(f"\n── Conversione {len(self.midi_files)} file ──────────────────", tag="acc")

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
                    f"  ✓  {fname}  →  {output_name}  ({pattern_length} step, {used} track)",
                    tag="ok",
                )
                ok_count += 1
            except Exception as e:
                self._log(f"  ✗  {fname}  →  {e}", tag="err")
                err_count += 1

        self._log(
            f"\n── Fine: {ok_count} OK  |  {err_count} errori ──────────────",
            tag="acc" if err_count == 0 else "err",
        )
        self._finish_convert(ok_count, err_count)

    def _convert_thread_merge(self, out_path, start_idx, steps_per_beat, instrument):
        n_files     = len(self.midi_files)
        n_patterns  = (n_files + MERGE_TRACK_MAX - 1) // MERGE_TRACK_MAX

        self._log(
            f"\n── UNIFICA {n_files} file → {n_patterns} pattern ──────────────",
            tag="acc",
        )

        # Fase 1: carica tutti i MIDI
        loaded = []  # list of (mido.MidiFile | None, fname)
        load_err = 0
        for i, midi_path in enumerate(self.midi_files):
            fname = Path(midi_path).name
            self._set_progress(f"Carico {i+1}/{n_files}  {fname}")
            try:
                mid = mido.MidiFile(str(midi_path))
                loaded.append((mid, fname))
            except Exception as e:
                self._log(f"  ✗  {fname}  →  {e}", tag="err")
                loaded.append((None, fname))
                load_err += 1

        if load_err:
            self._log(f"  {load_err} file non caricati — continua con gli altri.", tag="err")

        # Fase 2: scrivi un pattern per ogni chunk da MERGE_TRACK_MAX file
        ok_patterns  = 0
        err_patterns = 0

        for chunk_idx in range(n_patterns):
            chunk_start = chunk_idx * MERGE_TRACK_MAX
            chunk       = loaded[chunk_start : chunk_start + MERGE_TRACK_MAX]
            pat_idx     = start_idx + chunk_idx
            output_name = f"pattern_{pat_idx:02d}.mtp"
            output_file = out_path / output_name

            self._log(f"\n  Pattern {pat_idx:02d} ({len(chunk)} tracce):", tag="acc")

            # rimappa le track 0..len(chunk)-1, salta i None
            assignments = []
            for local_track, (mid, fname) in enumerate(chunk):
                if mid is not None:
                    assignments.append((mid, local_track, instrument))
                    self._log(f"    ● {fname}  →  Track {local_track}", tag="info")
                else:
                    self._log(f"    ✗  {fname}  (skipped)", tag="err")

            if not assignments:
                self._log(f"    Nessun file valido in questo chunk, pattern saltato.", tag="err")
                err_patterns += 1
                continue

            try:
                self._set_progress(f"Pattern {pat_idx:02d} – merging {len(assignments)} file…")
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
                    f"    ✓  Salvato: {output_name}  ({pattern_length} step, {used} track usate)",
                    tag="ok",
                )
                ok_patterns += 1
            except Exception as e:
                self._log(f"    ✗  Errore: {e}", tag="err")
                err_patterns += 1

        self._log(
            f"\n── Fine: {ok_patterns} pattern OK  |  {err_patterns} errori ──",
            tag="acc" if err_patterns == 0 else "err",
        )
        self._finish_convert(ok_patterns, err_patterns)

    def _finish_convert(self, ok, err):
        def _ui():
            self.converting = False
            self.conv_btn.config(state="normal", bg=ACCENT, text="▶  CONVERTI")
            if err == 0:
                self.progress_lbl.config(
                    text=f"Completato: {ok} file convertiti con successo.",
                    fg=OK,
                )
            else:
                self.progress_lbl.config(
                    text=f"Completato con errori: {ok} OK  /  {err} falliti.",
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
    # Centro la finestra
    app.update_idletasks()
    w, h = 580, 740
    sx = (app.winfo_screenwidth()  - w) // 2
    sy = (app.winfo_screenheight() - h) // 2
    app.geometry(f"{w}x{h}+{sx}+{sy}")
    app.mainloop()


if __name__ == "__main__":
    main()
