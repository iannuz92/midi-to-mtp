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
    print("Error: 'mido' library not found.")
    print("Install with:  pip install mido")
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
    """Serializes the file header (14 bytes)."""
    return struct.pack(
        '<2sH4s4sH',
        b'KS',
        FILE_TYPE_PATTERN,
        bytes([FV_VER_1, FV_VER_2, FV_VER_3, 1]),
        bytes([PATTERN_FILE_VERSION] * 4),
        SIZEOF_PATTERN,
    )  # = 14 bytes


def _pack_step(note: int, instrument: int,
               fx0_type: int = 0, fx0_val: int = 0,
               fx1_type: int = 0, fx1_val: int = 0) -> bytes:
    """Serializes a single step (6 bytes)."""
    return struct.pack('<bBBBBB', note, instrument,
                       fx0_type, fx0_val, fx1_type, fx1_val)


def _pack_track(length: int, steps: list) -> bytes:
    """
    Serializes a track (769 bytes).
    length: number of active steps (1-128).
    steps: list of dicts {'note', 'instrument', 'fx'} indexed 0..127.
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
    Builds the complete .mtp file as bytes.

    tracks_data: list of dicts (max 11):
        'length' : int  - pattern length for this track (steps)
        'steps'  : list - list of step dicts (indexed by step number)
    """
    header   = _pack_header()           # 14 bytes
    pad1     = b'\x00\x00'              #  2 bytes (alignment for float)
    f_tempo  = struct.pack('<f', 100.0) #  4 bytes
    f_swing  = struct.pack('<f', DEFAULT_SWING)  #  4 bytes
    rezerwa  = b'\x00' * 4             #  4 bytes reserved

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

    pad2 = b'\x00'  # 1 byte (alignment for uint32 crc)

    payload = header + pad1 + f_tempo + f_swing + rezerwa + tracks_bytes + pad2
    assert len(payload) == SIZEOF_PATTERN - 4, \
        f"Layout bug: payload={len(payload)} expected={SIZEOF_PATTERN - 4}"

    crc = binascii.crc32(payload) & 0xFFFFFFFF
    return payload + struct.pack('<I', crc)


# ─────────────────────────────────────────────
# Conversione MIDI → tracks_data
# ─────────────────────────────────────────────

def _round_pattern_length(max_step: int) -> int:
    """Rounds up to the nearest multiple of 16 >= max_step (16, 32, 64, 128)."""
    for length in [16, 32, 64, 128]:
        if max_step <= length:
            return length
    return STEP_COUNT


def _midi_length_in_steps(mid, ticks_per_step: int) -> int:
    """
    Calculates the real length of a MIDI file in steps.
    Sums all delta-times in each track (including end_of_track) so the
    pattern reflects the intended loop length, not just the last note position.
    Type 0: sums all messages in the single track.
    Type 1/2: takes the longest track (in ticks).
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
    Converts a MidiFile into (tracks_data, pattern_length).

    Chord spreading:
      When multiple MIDI notes land on the same step from the same source,
      they are distributed across consecutive tracker tracks, matching the
      behaviour of the Polyend Tracker firmware when receiving chords via MIDI IN.

      Example: C4+E4+G4 on step 0:
        tracker track 0 step 0 = G4  (highest voice)
        tracker track 1 step 0 = E4
        tracker track 2 step 0 = C4  (lowest voice)

    steps_per_beat:
        4  = 1/16 resolution (default)
        2  = 1/8  resolution
        1  = 1/4  resolution

    MIDI type 0 (single track): each MIDI channel = separate source.
    MIDI type 1 (multi-track) : each MIDI track = separate source.
    """
    ppqn           = mid.ticks_per_beat
    ticks_per_step = ppqn // steps_per_beat

    if ticks_per_step == 0:
        ticks_per_step = 1
        print("Warning: very low PPQN, possible loss of resolution")

    if verbose:
        print(f"MIDI type: {mid.type}  PPQN: {ppqn}  ticks/step: {ticks_per_step}")

    # -- Phase 1: collect notes as (step, note, source_idx) ─────────────
    # Notes on the same step from the same source form a chord.
    # step_source_notes[(step, source_idx)] = sorted list of MIDI notes (descending pitch)
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
        print("Warning: no notes found in MIDI file")
        return [{'length': DEFAULT_PATTERN_LENGTH, 'steps': []} for _ in range(TRACK_COUNT)], DEFAULT_PATTERN_LENGTH

    # Sort each chord highest-to-lowest (highest voice = lowest track index,
    # consistent with how the Tracker displays chord voices).
    for key in step_source_notes:
        step_source_notes[key].sort(reverse=True)

    # -- Phase 2: chord spreading ─────────────────────────────────────
    # step_occupied[step] = set of tracker tracks already assigned at that step.
    # For each note in a chord, pick the first free tracker track.
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
        print(f"  Total notes: {total_notes}  |  Max polyphony: {max_poly} voices")
        print(f"  Tracker tracks used: {used_tracks}")
        if skipped_chords:
            print(f"  Warning: {skipped_chords} notes discarded (all {TRACK_COUNT} tracks full)")

    # -- Phase 3: pattern length ──────────────────────────────────────
    all_steps  = [s for steps_dict in tracker_raw.values() for s in steps_dict.keys()]
    last_note  = max(all_steps) + 1 if all_steps else DEFAULT_PATTERN_LENGTH
    # Also use the real MIDI file duration so the pattern never shrinks below
    # the intended loop length even if the last note falls before the loop boundary.
    ppqn           = mid.ticks_per_beat
    ticks_per_step = max(1, ppqn // steps_per_beat)
    file_steps     = _midi_length_in_steps(mid, ticks_per_step)
    pattern_length = _round_pattern_length(max(last_note, file_steps))

    if verbose:
        print(f"  MIDI file duration: {file_steps} steps  |  Last note: {last_note - 1}  |  Pattern: {pattern_length}")

    # -- Phase 4: build tracks_data ──────────────────────────────────
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
# Merge: multiple MIDI files → single pattern
# ─────────────────────────────────────────────

MERGE_TRACK_MAX = 8  # max tracker tracks in merge mode

def merge_midi_files_to_tracks(
    assignments: list,
    steps_per_beat: int = 4,
    verbose: bool = False,
) -> tuple:
    """
    Merges multiple MIDI files into a single pattern (tracks_data).

    assignments: list of (mido.MidiFile, base_track_idx, instrument_idx)
        - Each file is placed on the specified tracker track (0-7).
        - Monophonic per track: if multiple notes fall on the same step, the first wins.
        - Maximum 8 tracker tracks (MERGE_TRACK_MAX).

    Returns (tracks_data, pattern_length).
    """
    tracker_raw: dict = {}  # {track_idx: {step: (note, instrument)}}

    if verbose:
        print(f"Merging {len(assignments)} MIDI files")

    for mid, base_track, instrument in assignments:
        if base_track >= MERGE_TRACK_MAX or base_track >= TRACK_COUNT:
            if verbose:
                print(f"  Warning: track {base_track} out of range, skipped")
            continue

        ppqn           = mid.ticks_per_beat
        ticks_per_step = max(1, ppqn // steps_per_beat)

        if base_track not in tracker_raw:
            tracker_raw[base_track] = {}

        # Collect all note_on events (all MIDI channels/tracks in the file).
        # Monophonic: first note at each step wins.
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
            print("  Warning: no notes found")
        return [{'length': DEFAULT_PATTERN_LENGTH, 'steps': []} for _ in range(TRACK_COUNT)], DEFAULT_PATTERN_LENGTH

    # Pattern length = max of:
    # - position of last note found across all files
    # - real duration of the longest MIDI file (end_of_track ticks)
    # This ensures that a file declaring a 32-step loop with its last note at
    # step 30 still produces a 32-step pattern rather than a 16-step one.
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
        print(f"  Pattern length: {pattern_length} steps")

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
        description='Convert MIDI files to Polyend Tracker pattern files (.mtp)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python midi_to_mtp.py beat.mid
  python midi_to_mtp.py beat.mid pattern_01.mtp
  python midi_to_mtp.py beat.mid -r 16 -v
  python midi_to_mtp.py beat.mid -r 8 -i 2
  python midi_to_mtp.py beat.mid --resolution 16 --instrument 0

Resolution (-r):
  16  = 1/16 notes (default) – 4 steps per beat
   8  = 1/8  notes           – 2 steps per beat
   4  = 1/4  notes           – 1 step  per beat

Output file placement on the Tracker:
  Copy the .mtp file into the project folder on the SD card:
    <SD>/projects/<project_name>/patterns/pattern_NN.mtp
  where NN is the pattern number (01-255).
        """,
    )
    parser.add_argument('input',
                        help='Input MIDI file (.mid)')
    parser.add_argument('output', nargs='?',
                        help='Output MTP file (default: same name with .mtp extension)')
    parser.add_argument('-r', '--resolution',
                        type=int, default=16, choices=[4, 8, 16],
                        metavar='{4,8,16}',
                        help='Resolution: 1/N notes (default: 16)')
    parser.add_argument('-i', '--instrument',
                        type=int, default=0,
                        help='Default instrument slot (0-47, default: 0)')
    parser.add_argument('-v', '--verbose',
                        action='store_true',
                        help='Print detailed output')

    args = parser.parse_args()

    input_path  = Path(args.input)
    output_path = Path(args.output) if args.output else input_path.with_suffix('.mtp')

    if not input_path.exists():
        print(f"Error: file '{args.input}' not found")
        sys.exit(1)

    if not 0 <= args.instrument <= 47:
        print("Error: --instrument must be between 0 and 47")
        sys.exit(1)

    steps_per_beat = args.resolution // 4  # 16→4, 8→2, 4→1

    if args.verbose:
        print(f"Input : {input_path}")
        print(f"Output: {output_path}")
        print(f"Resolution: 1/{args.resolution}  ({steps_per_beat} steps/beat)")
        print(f"Default instrument: {args.instrument}")

    try:
        mid = mido.MidiFile(str(input_path))
    except Exception as e:
        print(f"Error loading MIDI file: {e}")
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
    print(f"Saved: {output_path}  ({len(mtp_data)} bytes, {pattern_length} steps, {used_tracks} tracks used)")


if __name__ == '__main__':
    main()
