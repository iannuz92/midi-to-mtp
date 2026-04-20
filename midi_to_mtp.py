#!/usr/bin/env python3
"""
MIDI to MTP converter for Polyend Tracker
==========================================
Converts MIDI files (.mid) into Polyend Tracker pattern files (.mtp).

The .mtp binary format has been reverse-engineered by analyzing pattern files
generated and read by the Polyend Tracker hardware. 

.mtp binary layout (8492 bytes, little-endian, ARM Cortex-M7 natural alignment):

  offset  0 : magic[2]               char[2]   = 'K', 'S'
  offset  2 : type                    uint16 LE = 2 (pattern file)
  offset  4 : fwVersion[4]            byte[4]
  offset  8 : fileStructureVersion[4] byte[4]
  offset 12 : size                    uint16 LE = 8492
  offset 14 : (2 padding bytes)
  offset 16 : tempo                   float32 LE = 100.0
  offset 20 : swing                   float32 LE = 50.0
  offset 24 : reserved[4]             byte[4]   = {0,0,0,0}
  offset 28 : track[11] x 769 bytes
    offset +0 : length                uint8     = steps - 1
    offset +1 : step[128] x 6 bytes
      offset +0 : note                int8      = -1 (empty) / MIDI note 0-120
      offset +1 : instrument          uint8     = 0..47
      offset +2 : fx[0].type          uint8
      offset +3 : fx[0].value         uint8
      offset +4 : fx[1].type          uint8
      offset +5 : fx[1].value         uint8
  offset 8487 : (1 padding byte)
  offset 8488 : crc                   uint32 LE (CRC32 of first 8488 bytes)

Usage:
  python midi_to_mtp.py input.mid
  python midi_to_mtp.py input.mid output.mtp
  python midi_to_mtp.py input.mid -r 16 -v
  python midi_to_mtp.py input.mid -i 1        # set instrument=1 on all notes
"""

import argparse
import struct
import sys
from pathlib import Path
import binascii

try:
    import mido
except ImportError:
    print("Errore: libreria 'mido' non trovata.")
    print("Installa con:  pip install mido")
    sys.exit(1)

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────
PATTERN_FILE_VERSION = 1
FV_VER_1 = 1
FV_VER_2 = 1
FV_VER_3 = 1

TRACK_COUNT = 11          # 11 tracks per pattern
STEP_COUNT  = 128         # max 128 steps per track

DEFAULT_PATTERN_LENGTH = 32
DEFAULT_SWING          = 50.0

FILE_TYPE_PATTERN = 2

STEP_NOTE_EMPTY = -1      # empty slot
STEP_NOTE_OFF   = -4      # explicit note-off

SIZEOF_PATTERN  = 8492    # total size of a .mtp file in bytes

# ─────────────────────────────────────────────
# Packing helpers
# ─────────────────────────────────────────────

def _pack_header() -> bytes:
    """Serializza strFileHeader (14 bytes)."""
    return struct.pack(
        '<2sH4s4sH',
        b'KS',                                     # id_file[2]
        FILE_TYPE_PATTERN,                          # type uint16
        bytes([FV_VER_1, FV_VER_2, FV_VER_3, 1]), # fwVersion[4]
        bytes([PATTERN_FILE_VERSION] * 4),          # fileStructureVersion[4]
        SIZEOF_PATTERN,                             # size uint16
    )  # = 14 bytes


def _pack_step(note: int, instrument: int,
               fx0_type: int = 0, fx0_val: int = 0,
               fx1_type: int = 0, fx1_val: int = 0) -> bytes:
    """Serializza un singolo step (6 bytes)."""
    return struct.pack('<bBBBBB', note, instrument,
                       fx0_type, fx0_val, fx1_type, fx1_val)


def _pack_track(length: int, steps: list) -> bytes:
    """
    Serializza un track (769 bytes).
    length: numero di step attivi (1–128).
    steps: lista di dict {'note', 'instrument', 'fx'} indicizzata 0..127.
    """
    data = struct.pack('<B', min(length, STEP_COUNT) - 1)
    for i in range(STEP_COUNT):
        if i < len(steps):
            s = steps[i]
            fxs = s.get('fx', [(0, 0), (0, 0)])
            data += _pack_step(
                s.get('note', STEP_NOTE_EMPTY),
                s.get('instrument', 0),
                fxs[0][0] if len(fxs) > 0 else 0,
                fxs[0][1] if len(fxs) > 0 else 0,
                fxs[1][0] if len(fxs) > 1 else 0,
                fxs[1][1] if len(fxs) > 1 else 0,
            )
        else:
            data += _pack_step(STEP_NOTE_EMPTY, 0)
    return data  # 1 + 128*6 = 769 bytes


def build_mtp(tracks_data: list, pattern_length: int = DEFAULT_PATTERN_LENGTH) -> bytes:
    """
    Costruisce il file .mtp completo come bytes.

    tracks_data: lista di dict (max 11):
        'length'     : int   – lunghezza del pattern per questo track (steps)
        'steps'      : list  – lista di step dict (indicizzata per step)
    """
    header   = _pack_header()           # 14 bytes
    pad1     = b'\x00\x00'              #  2 bytes (allineamento float)
    f_tempo  = struct.pack('<f', 100.0) #  4 bytes
    f_swing  = struct.pack('<f', DEFAULT_SWING)  #  4 bytes
    rezerwa  = b'\x00' * 4             #  4 bytes

    tracks_bytes = b''
    for i in range(TRACK_COUNT):
        if i < len(tracks_data):
            td = tracks_data[i]
            tracks_bytes += _pack_track(
                td.get('length', pattern_length),
                td.get('steps', []),
            )
        else:
            tracks_bytes += _pack_track(pattern_length, [])

    pad2 = b'\x00'  # 1 byte (allineamento uint32 crc)

    payload = header + pad1 + f_tempo + f_swing + rezerwa + tracks_bytes + pad2
    assert len(payload) == SIZEOF_PATTERN - 4, \
        f"Bug layout: payload={len(payload)} atteso={SIZEOF_PATTERN - 4}"

    crc = binascii.crc32(payload) & 0xFFFFFFFF
    return payload + struct.pack('<I', crc)


# ─────────────────────────────────────────────
# Conversione MIDI → tracks_data
# ─────────────────────────────────────────────

def _round_pattern_length(max_step: int) -> int:
    """Arrotonda al primo multiplo di 16 >= max_step (16, 32, 64, 128)."""
    for length in [16, 32, 64, 128]:
        if max_step <= length:
            return length
    return STEP_COUNT


def _midi_length_in_steps(mid, ticks_per_step: int) -> int:
    """
    Calcola la lunghezza reale del file MIDI in step.
    Usa la somma totale dei tick di ogni track (end_of_track incluso),
    cosi' il pattern rispecchia la durata del file, non solo l'ultima nota.
    Per file Type 0: somma tutti i msg della singola track.
    Per file Type 1/2: prende la track piu' lunga (in tick).
    """
    if not mid.tracks:
        return DEFAULT_PATTERN_LENGTH
    if mid.type == 0:
        total_ticks = sum(msg.time for msg in mid.tracks[0])
    else:
        total_ticks = max(
            sum(msg.time for msg in track)
            for track in mid.tracks
        )
    return max(1, total_ticks // ticks_per_step)


def midi_to_tracks(mid: "mido.MidiFile",
                   steps_per_beat: int = 4,
                   default_instrument: int = 0,
                   verbose: bool = False) -> tuple:
    """
    Converte un MidiFile in (tracks_data, pattern_length).

    Gestione accordi (chord spreading):
      Quando più note MIDI coincidono allo stesso step (stessa sorgente),
      vengono distribuite su tracker track consecutive – esattamente come
      fa il firmware Polyend quando il MIDI IN riceve un accordo.

      Esempio: C4+E4+G4 allo step 0 →
        tracker track 0 step 0 = C4
        tracker track 1 step 0 = E4
        tracker track 2 step 0 = G4

    steps_per_beat:
        4  = risoluzione 1/16  (default)
        2  = risoluzione 1/8
        1  = risoluzione 1/4

    Per MIDI type 0 (singolo track): ogni canale MIDI = sorgente distinta.
    Per MIDI type 1 (multi-track)  : ogni MIDI track = sorgente distinta.
    """
    ppqn           = mid.ticks_per_beat
    ticks_per_step = ppqn // steps_per_beat

    if ticks_per_step == 0:
        ticks_per_step = 1
        print("Warning: PPQN molto basso, possibile perdita di risoluzione")

    if verbose:
        print(f"MIDI type: {mid.type}  PPQN: {ppqn}  ticks/step: {ticks_per_step}")

    # ── Fase 1: raccolta note come (step, note, source_idx) ──────────
    # Ogni nota allo stesso step nella stessa sorgente = accordo.
    # step_source_notes[(step, source_idx)] = lista ordinata di note MIDI (pitch desc)
    step_source_notes: dict = {}

    def _add_note(source_idx: int, step: int, note: int):
        if step >= STEP_COUNT:
            return
        key = (step, source_idx)
        if key not in step_source_notes:
            step_source_notes[key] = []
        step_source_notes[key].append(note)

    if mid.type == 0:
        abs_tick = 0
        for msg in mid.tracks[0]:
            abs_tick += msg.time
            if msg.type == 'note_on' and msg.velocity > 0:
                _add_note(getattr(msg, 'channel', 0),
                          abs_tick // ticks_per_step, msg.note)
    else:
        for src_idx, midi_track in enumerate(mid.tracks):
            abs_tick = 0
            for msg in midi_track:
                abs_tick += msg.time
                if msg.type == 'note_on' and msg.velocity > 0:
                    _add_note(src_idx, abs_tick // ticks_per_step, msg.note)

    if not step_source_notes:
        print("Warning: nessuna nota trovata nel file MIDI")
        return [{'length': DEFAULT_PATTERN_LENGTH, 'steps': []} for _ in range(TRACK_COUNT)], DEFAULT_PATTERN_LENGTH

    # Ordina ogni accordo: nota più alta prima (voce superiore = traccia bassa,
    # coerente con come il tracker visualizza le voci di un accordo).
    for key in step_source_notes:
        step_source_notes[key].sort(reverse=True)

    # ── Fase 2: chord spreading ───────────────────────────────────────
    # step_occupied[step] = set di tracker track già assegnate in quello step.
    # Per ogni nota dell'accordo, prendiamo la prima tracker track libera.
    step_occupied: dict = {}   # step -> set(tracker_track_idx)
    tracker_raw:   dict = {}   # tracker_track_idx -> {step: note}

    skipped_chords = 0

    for (step, _src) in sorted(step_source_notes.keys()):
        notes = step_source_notes[(step, _src)]
        if step not in step_occupied:
            step_occupied[step] = set()

        for note_midi in notes:
            # Prima tracker track libera in questo step
            assigned = False
            for t in range(TRACK_COUNT):
                if t not in step_occupied[step]:
                    step_occupied[step].add(t)
                    if t not in tracker_raw:
                        tracker_raw[t] = {}
                    tracker_raw[t][step] = max(0, min(120, note_midi))
                    assigned = True
                    break
            if not assigned:
                skipped_chords += 1

    if verbose:
        max_poly = max(len(v) for v in step_source_notes.values())
        used_tracks = len(tracker_raw)
        total_notes = sum(len(v) for v in step_source_notes.values())
        print(f"  Note totali: {total_notes}  |  Polifonia max: {max_poly} voci")
        print(f"  Tracker track usate: {used_tracks}")
        if skipped_chords:
            print(f"  Warning: {skipped_chords} note scartate (tutte le {TRACK_COUNT} track piene)")

    # ── Fase 3: lunghezza pattern ─────────────────────────────────────
    all_steps  = [s for steps_dict in tracker_raw.values() for s in steps_dict.keys()]
    last_note  = max(all_steps) + 1 if all_steps else DEFAULT_PATTERN_LENGTH
    # Usa anche la durata reale del file MIDI: il pattern non si accorcia mai
    # rispetto all'intento del loop anche se l'ultima nota cade prima del bordo.
    ppqn           = mid.ticks_per_beat
    ticks_per_step = max(1, ppqn // steps_per_beat)
    file_steps     = _midi_length_in_steps(mid, ticks_per_step)
    pattern_length = _round_pattern_length(max(last_note, file_steps))

    if verbose:
        print(f"  Durata file MIDI: {file_steps} step  |  Ultima nota: {last_note - 1}  |  Pattern: {pattern_length}")

    # ── Fase 4: costruisci tracks_data ───────────────────────────────
    tracks_data = []
    for i in range(TRACK_COUNT):
        steps_list = []
        steps_dict = tracker_raw.get(i, {})
        for s in range(STEP_COUNT):
            if s in steps_dict:
                steps_list.append({
                    'note':       steps_dict[s],
                    'instrument': default_instrument,
                    'fx':         [(0, 0), (0, 0)],
                })
            else:
                steps_list.append({
                    'note':       STEP_NOTE_EMPTY,
                    'instrument': 0,
                    'fx':         [(0, 0), (0, 0)],
                })
        tracks_data.append({'length': pattern_length, 'steps': steps_list})

    return tracks_data, pattern_length


# ─────────────────────────────────────────────
# Merge: più MIDI → un solo pattern
# ─────────────────────────────────────────────

MERGE_TRACK_MAX = 8  # tracce audio disponibili in modalità unificata

def merge_midi_files_to_tracks(
    assignments: list,
    steps_per_beat: int = 4,
    verbose: bool = False,
) -> tuple:
    """
    Unisce più file MIDI in un singolo pattern (tracks_data).

    assignments: lista di (mido.MidiFile, base_track_idx, instrument_idx)
        - Ogni file viene posizionato sulla tracker track specificata (0–7).
        - Monophonic per track: se più note cadono sullo stesso step la prima vince.
        - Massimo 8 tracker track (MERGE_TRACK_MAX).

    Returns (tracks_data, pattern_length).
    """
    tracker_raw: dict = {}  # {track_idx: {step: (note, instrument)}}

    if verbose:
        print(f"Merge di {len(assignments)} file MIDI")

    for mid, base_track, instrument in assignments:
        if base_track >= MERGE_TRACK_MAX or base_track >= TRACK_COUNT:
            if verbose:
                print(f"  Warning: track {base_track} fuori range, ignorato")
            continue

        ppqn           = mid.ticks_per_beat
        ticks_per_step = max(1, ppqn // steps_per_beat)

        if base_track not in tracker_raw:
            tracker_raw[base_track] = {}

        # Raccoglie tutte le note_on (tutti i canali/track MIDI del file)
        # Monophonic: il primo step vince
        step_notes: dict = {}

        if mid.type == 0:
            abs_tick = 0
            for msg in mid.tracks[0]:
                abs_tick += msg.time
                if msg.type == 'note_on' and msg.velocity > 0:
                    step = abs_tick // ticks_per_step
                    if step < STEP_COUNT and step not in step_notes:
                        step_notes[step] = msg.note
        else:
            for midi_track in mid.tracks:
                abs_tick = 0
                for msg in midi_track:
                    abs_tick += msg.time
                    if msg.type == 'note_on' and msg.velocity > 0:
                        step = abs_tick // ticks_per_step
                        if step < STEP_COUNT and step not in step_notes:
                            step_notes[step] = msg.note

        for step, note_midi in step_notes.items():
            if step not in tracker_raw[base_track]:
                tracker_raw[base_track][step] = (max(0, min(120, note_midi)), instrument)

        if verbose:
            fname = getattr(mid, 'filename', '') or ''
            print(f"  Track {base_track}: {len(step_notes)} step  ← '{Path(fname).name if fname else '?'}'")

    if not tracker_raw:
        if verbose:
            print("  Warning: nessuna nota trovata")
        return [{'length': DEFAULT_PATTERN_LENGTH, 'steps': []} for _ in range(TRACK_COUNT)], DEFAULT_PATTERN_LENGTH

    # La lunghezza del pattern e' il massimo tra:
    # - ultima nota trovata in qualsiasi file
    # - durata reale del file MIDI piu' lungo (end_of_track ticks)
    # In questo modo se un file dichiara un loop da 32 step ma l'ultima nota
    # e' a step 30, il pattern sara' comunque 32 e non 16.
    all_steps    = [s for sd in tracker_raw.values() for s in sd.keys()]
    last_note    = max(all_steps) + 1 if all_steps else DEFAULT_PATTERN_LENGTH
    max_file_steps = 0
    for mid, base_track, instrument in assignments:
        ppqn           = mid.ticks_per_beat
        ticks_per_step = max(1, ppqn // steps_per_beat)
        fs = _midi_length_in_steps(mid, ticks_per_step)
        if fs > max_file_steps:
            max_file_steps = fs
    pattern_length = _round_pattern_length(max(last_note, max_file_steps))

    if verbose:
        print(f"  Lunghezza pattern: {pattern_length} step")

    tracks_data = []
    for i in range(TRACK_COUNT):
        steps_list  = []
        steps_dict  = tracker_raw.get(i, {})
        for s in range(STEP_COUNT):
            if s in steps_dict:
                note_val, instr = steps_dict[s]
                steps_list.append({'note': note_val, 'instrument': instr, 'fx': [(0, 0), (0, 0)]})
            else:
                steps_list.append({'note': STEP_NOTE_EMPTY, 'instrument': 0, 'fx': [(0, 0), (0, 0)]})
        tracks_data.append({'length': pattern_length, 'steps': steps_list})

    return tracks_data, pattern_length


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Converte file MIDI in pattern Polyend Tracker (.mtp)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi:
  python midi_to_mtp.py beat.mid
  python midi_to_mtp.py beat.mid pattern_01.mtp
  python midi_to_mtp.py beat.mid -r 16 -v
  python midi_to_mtp.py beat.mid -r 8 -i 2
  python midi_to_mtp.py beat.mid --resolution 16 --instrument 0

Risoluzione (-r):
  16  = note da 1/16  (default) – 4 step per beat
   8  = note da 1/8             – 2 step per beat
   4  = note da 1/4             – 1 step per beat

Posizionamento file output sul tracker:
  Copia il file .mtp nella cartella del progetto:
    <SD>/projects/<nome_progetto>/patterns/pattern_NN.mtp
  dove NN è il numero del pattern (01–255).
        """,
    )
    parser.add_argument('input',
                        help='File MIDI di input (.mid)')
    parser.add_argument('output', nargs='?',
                        help='File MTP di output (default: stesso nome con estensione .mtp)')
    parser.add_argument('-r', '--resolution',
                        type=int, default=16, choices=[4, 8, 16],
                        metavar='{4,8,16}',
                        help='Risoluzione: note da 1/N (default: 16)')
    parser.add_argument('-i', '--instrument',
                        type=int, default=0,
                        help='Indice strumento di default (0–47, default: 0)')
    parser.add_argument('-v', '--verbose',
                        action='store_true',
                        help='Output dettagliato')

    args = parser.parse_args()

    input_path  = Path(args.input)
    output_path = Path(args.output) if args.output else input_path.with_suffix('.mtp')

    if not input_path.exists():
        print(f"Errore: file '{args.input}' non trovato")
        sys.exit(1)

    if not 0 <= args.instrument <= 47:
        print("Errore: --instrument deve essere tra 0 e 47")
        sys.exit(1)

    steps_per_beat = args.resolution // 4  # 16→4, 8→2, 4→1

    if args.verbose:
        print(f"Input : {input_path}")
        print(f"Output: {output_path}")
        print(f"Risoluzione: 1/{args.resolution}  ({steps_per_beat} step/beat)")
        print(f"Strumento default: {args.instrument}")

    try:
        mid = mido.MidiFile(str(input_path))
    except Exception as e:
        print(f"Errore nel caricare il file MIDI: {e}")
        sys.exit(1)

    tracks_data, pattern_length = midi_to_tracks(
        mid,
        steps_per_beat=steps_per_beat,
        default_instrument=args.instrument,
        verbose=args.verbose,
    )

    mtp_data = build_mtp(tracks_data, pattern_length)

    output_path.write_bytes(mtp_data)

    used_tracks = sum(1 for td in tracks_data if any(
        s.get('note', STEP_NOTE_EMPTY) != STEP_NOTE_EMPTY for s in td.get('steps', [])
    ))
    print(f"Salvato: {output_path}  ({len(mtp_data)} bytes, {pattern_length} step, {used_tracks} track)")


if __name__ == '__main__':
    main()
