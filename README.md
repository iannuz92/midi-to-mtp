# midi-to-mtp

A tool to convert MIDI files into Polyend Tracker pattern files (.mtp).

The .mtp binary format has been reverse-engineered by analyzing pattern files
generated and loaded by the Polyend Tracker hardware.

---

## Features

- Convert one or more MIDI files to .mtp pattern files
- Chord spreading: overlapping notes on the same step are distributed across
  multiple tracker tracks, matching the Tracker's own behaviour
- Two conversion modes:
  - **Separate** (default): each MIDI file produces its own pattern file
  - **Merge**: multiple MIDI files are combined into a single pattern, each
    assigned to a distinct tracker track (0-7). If more than 8 files are
    loaded they overflow into consecutive pattern slots automatically
- Pattern length is derived from the actual duration of the MIDI file, not
  only from the position of the last note
- GUI and command-line interface

---

## Requirements

- Python 3.9 or later
- [mido](https://mido.readthedocs.io/) >= 1.3.0
- tkinter (included with most Python distributions; on macOS install via
  `brew install python-tk`)

Install dependencies:

```
pip install -r requirements.txt
```

---

## GUI

```
python midi_to_mtp_gui.py
```

### Separate mode

Each MIDI file in the list is converted to an independent pattern file.
The output files are named `pattern_00.mtp`, `pattern_01.mtp`, etc., starting
from the pattern index specified in the options.

### Merge mode

All MIDI files in the list are combined into one or more pattern files.
Up to 8 files fit in a single pattern (one file per tracker track).  
If more than 8 files are loaded, the tool writes multiple pattern files
automatically: `pattern_00.mtp` contains files 1-8, `pattern_01.mtp`
contains files 9-16, and so on.

The listbox label shows `[Pn Tm]` for each file, indicating the destination
pattern index and track.

---

## Command-line interface

```
python midi_to_mtp.py input.mid
python midi_to_mtp.py input.mid output.mtp
python midi_to_mtp.py input.mid -r 16 -v
python midi_to_mtp.py input.mid -i 1
```

Options:

| Flag | Description |
|------|-------------|
| `-r, --resolution` | Step resolution: 16 = 1/16 (default), 8 = 1/8, 4 = 1/4 |
| `-i, --instrument` | Instrument index to assign to all notes (0-47, default 0) |
| `-v, --verbose` | Print conversion details |

---

## Pattern format overview

The .mtp file is 8492 bytes, little-endian, with natural ARM alignment:

- 2-byte magic: `K`, `S`
- File type, version, and size fields
- 11 tracks x 769 bytes each:
  - 1 byte: pattern length (steps - 1)
  - 128 steps x 6 bytes: note, instrument, fx1 type/value, fx2 type/value
- 4-byte CRC32 of the preceding 8488 bytes

---

## Notes on MIDI compatibility

- MIDI type 0 (single track): each channel is treated as a separate source
  for chord spreading
- MIDI type 1 (multi-track): each MIDI track is treated as a separate source
- In merge mode, each file is monophonic per tracker track; if multiple notes
  fall on the same step, the first one wins

---

## License

MIT
