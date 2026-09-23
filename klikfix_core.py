# KlikFix is free software: you may redistribute and/or modify it under
# the GNU General Public License, version 3 or later, as published by the
# Free Software Foundation. There is NO WARRANTY. See the LICENSE file.
"""Read and change the startup window options of old Clickteam games.

Supports Multimedia Fusion 1.0 / 1.5 standalone EXEs and the 1996 line
(The Games Factory, Click & Create, MMF Express), whose game data sits in a
.gam / .cca file beside the EXE.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass

# Bits of the application flags word. The 1996 format stores the low 16 bits
# of the same word, with the same numbering.
BIT_NO_TITLE_BAR = 1
BIT_STRETCH = 4
BIT_MENU_HIDDEN_AT_START = 7
BIT_MENU_BAR = 8
BIT_MAXIMIZED = 9
BIT_FULL_SCREEN = 11          # the editor calls it "change resolution mode"
BIT_ALLOW_SWITCH = 12

MMF_HEADER_CHUNK = 0x2223
MMF_PRODUCTS = {0: "Multimedia Fusion 1.0", 1: "Multimedia Fusion 1.5"}

KLIK96_OPTIONS = 0x100        # u16 at this offset of the .gam / .cca
KLIK96_VERSION = 0x0207
KLIK96_PRODUCTS = {b"GAME": "Click & Create / MMF Express",
                   b"PAME": "Click & Create / MMF Express",
                   b"GAPP": "The Games Factory", b"PAPP": "The Games Factory"}
KLIK96_EXTENSIONS = (".gam", ".cca")

MAX_HEADER = 0x10000          # the real header is under 100 bytes


class NotAGame(ValueError):
    """The file is not a game this tool can read."""


# -- Clickteam decompression ------------------------------------------------
# DEFLATE with renumbered block types (5 fixed, 6 dynamic, 7 stored), a 4-bit
# block header, and the code-length alphabet in the order 18, 17, 16, 0-15.

_ORDER = (18, 17, 16, *range(16))
_LEN_BASE = (3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43,
             51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258)
_LEN_EXTRA = (0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3,
              4, 4, 4, 4, 5, 5, 5, 5, 0)
_DIST_BASE = (1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257,
              385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289,
              16385, 24577)
_DIST_EXTRA = (0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8,
               9, 9, 10, 10, 11, 11, 12, 12, 13, 13)


class _Bits:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def read(self, count: int) -> int:
        value = 0
        for index in range(count):
            byte = self.pos >> 3
            if byte >= len(self.data):
                raise NotAGame("The game's header is cut short.")
            value |= (self.data[byte] >> (self.pos & 7) & 1) << index
            self.pos += 1
        return value


def _huffman(lengths) -> dict:
    table, code = {}, 0
    for length in range(1, 16):
        for symbol, symbol_length in enumerate(lengths):
            if symbol_length == length:
                table[(length, code)] = symbol
                code += 1
        code <<= 1
    return table


def _symbol(bits: _Bits, table: dict) -> int:
    code = 0
    for length in range(1, 16):
        code = code << 1 | bits.read(1)
        symbol = table.get((length, code))
        if symbol is not None:
            return symbol
    raise NotAGame("The game's header is damaged.")


_FIXED_LIT = _huffman((8,) * 144 + (9,) * 112 + (7,) * 24 + (8,) * 8)
_FIXED_DIST = _huffman((5,) * 30)


def inflate(stream: bytes, limit: int = MAX_HEADER) -> bytes:
    bits = _Bits(stream)
    out = bytearray()
    while True:
        block_type, final = bits.read(3), bits.read(1)
        if block_type == 7:
            bits.pos = (bits.pos + 7) & ~7
            length = bits.read(16)
            start = bits.pos >> 3
            out += stream[start:start + length]
            bits.pos += length * 8
        elif block_type in (5, 6):
            if block_type == 5:
                lit, dist = _FIXED_LIT, _FIXED_DIST
            else:
                lit_count = bits.read(5) + 257
                dist_count = bits.read(5) + 1
                cl_lengths = [0] * 19
                for index in range(bits.read(4) + 4):
                    cl_lengths[_ORDER[index]] = bits.read(3)
                cl_table = _huffman(cl_lengths)
                lengths: list[int] = []
                while len(lengths) < lit_count + dist_count:
                    symbol = _symbol(bits, cl_table)
                    if symbol < 16:
                        lengths.append(symbol)
                    elif symbol == 16 and lengths:
                        lengths += [lengths[-1]] * (bits.read(2) + 3)
                    elif symbol == 17:
                        lengths += [0] * (bits.read(3) + 3)
                    elif symbol == 18:
                        lengths += [0] * (bits.read(7) + 11)
                    else:
                        raise NotAGame("The game's header is damaged.")
                lit = _huffman(lengths[:lit_count])
                dist = _huffman(lengths[lit_count:lit_count + dist_count])
            while True:
                symbol = _symbol(bits, lit)
                if symbol < 256:
                    out.append(symbol)
                elif symbol == 256:
                    break
                else:
                    index = symbol - 257
                    code = None
                    if index < len(_LEN_BASE):
                        length = _LEN_BASE[index] + bits.read(_LEN_EXTRA[index])
                        code = _symbol(bits, dist)
                    if code is None or code >= len(_DIST_BASE):
                        raise NotAGame("The game's header is damaged.")
                    distance = _DIST_BASE[code] + bits.read(_DIST_EXTRA[code])
                    if distance > len(out):
                        raise NotAGame("The game's header is damaged.")
                    for _ in range(length):
                        out.append(out[-distance])
        else:
            raise NotAGame("The game's header uses an unknown packing.")
        if len(out) > limit:
            raise NotAGame("The game's header is too large.")
        if final:
            return bytes(out)


def stored(data: bytes) -> bytes:
    """``data`` as one final stored block: no compressor needed to write."""
    return bytes([7 | 1 << 3]) + struct.pack("<H", len(data)) + data


# -- Game files -----------------------------------------------------------

@dataclass
class Game:
    kind: str                 # "mmf" or "klik96"
    path: str                 # the file holding the options (gets patched)
    exe: str | None           # what to run
    data: bytes
    product_name: str
    chunk: int = 0            # MMF: offset of the header chunk
    chunk_flags: int = 0
    chunk_size: int = 0
    header: bytes = b""       # MMF: unpacked header

    @property
    def flags(self) -> int:
        if self.kind == "klik96":
            return struct.unpack_from("<H", self.data, KLIK96_OPTIONS)[0]
        return struct.unpack_from("<I", self.header, 0)[0]


def _find_package(data: bytes) -> int:
    """Offset of the MMF package: a PAME/PAMU tag followed by the header."""
    for tag in (b"PAME", b"PAMU"):
        at = data.find(tag)
        while at != -1:
            if data[at + 16:at + 18] == b"\x23\x22":
                return at
            at = data.find(tag, at + 1)
    return -1


def _sibling(path: str, extensions) -> str | None:
    stem = os.path.splitext(path)[0]
    for extension in extensions:
        if os.path.isfile(stem + extension):
            return stem + extension
    return None


def load(path: str) -> Game:
    """Open a game EXE, or a 1996 .gam / .cca data file."""
    with open(path, "rb") as handle:
        data = handle.read()
    if data[:4] in KLIK96_PRODUCTS:
        return parse_klik96(data, path, _sibling(path, (".exe",)))
    if _find_package(data) >= 0:
        exe = path if path.lower().endswith(".exe") else None
        return parse(data, path, exe)
    if path.lower().endswith(".exe"):
        # A 1996 runtime: its game is the data file with the same name.
        companion = _sibling(path, KLIK96_EXTENSIONS)
        if companion:
            with open(companion, "rb") as handle:
                companion_data = handle.read()
            if companion_data[:4] in KLIK96_PRODUCTS:
                return parse_klik96(companion_data, companion, path)
    raise NotAGame("This doesn't look like a Multimedia Fusion, Click & "
                   "Create or Games Factory game.\n(It may be an installer, "
                   "or packed with another tool.)")


def parse_klik96(data: bytes, path: str, exe: str | None) -> Game:
    if len(data) < KLIK96_OPTIONS + 2:
        raise NotAGame("This game file is too short.")
    version = struct.unpack_from("<H", data, 4)[0]
    if version == 0x0126:
        raise NotAGame("Klik & Play games aren't supported yet.")
    if version != KLIK96_VERSION:
        raise NotAGame("This game file is a version KlikFix doesn't know.")
    return Game("klik96", path, exe, data, KLIK96_PRODUCTS[data[:4]])


def parse(data: bytes, path: str = "", exe: str | None = None) -> Game:
    package = _find_package(data)
    if package < 0:
        raise NotAGame("This doesn't look like a Multimedia Fusion game.")
    product, major = data[package + 4], data[package + 5]
    if major == 3 and product == 2:
        raise NotAGame("Multimedia Fusion 2 games aren't supported yet.")
    if major != 3 or product not in MMF_PRODUCTS:
        raise NotAGame("This Clickteam format isn't supported yet.")
    chunk = package + 16
    if len(data) < chunk + 8:
        raise NotAGame("This game file is cut short.")
    _, chunk_flags, chunk_size = struct.unpack_from("<HHI", data, chunk)
    payload = data[chunk + 8:chunk + 8 + chunk_size]
    if chunk_flags == 0:
        header = payload
    elif chunk_flags == 1 and len(payload) >= 4:
        size = struct.unpack_from("<I", payload, 0)[0]
        header = inflate(payload[4:])
        if len(header) != size:
            raise NotAGame("The game's header did not unpack cleanly.")
    else:
        raise NotAGame("The game's header uses an unknown packing.")
    if not 4 <= len(header) <= MAX_HEADER:
        raise NotAGame("The game's header is the wrong size.")
    return Game("mmf", path, exe, data, MMF_PRODUCTS[product], chunk,
                chunk_flags, chunk_size, header)


def with_flags(game: Game, flags: int) -> bytes:
    """The options file's bytes with new flags."""
    if game.kind == "klik96":
        at = KLIK96_OPTIONS
        return (game.data[:at] + struct.pack("<H", flags & 0xFFFF)
                + game.data[at + 2:])
    # MMF: rewrite the header chunk as a stored block. Later chunks shift by
    # a few bytes, which the runtime accepts.
    header = struct.pack("<I", flags) + game.header[4:]
    if game.chunk_flags == 0:
        payload = header
    else:
        payload = struct.pack("<I", len(header)) + stored(header)
    chunk = struct.pack("<HHI", MMF_HEADER_CHUNK, game.chunk_flags,
                        len(payload))
    end = game.chunk + 8 + game.chunk_size
    patched = game.data[:game.chunk] + chunk + payload + game.data[end:]
    if parse(patched, game.path).header != header:
        raise RuntimeError("The change did not read back correctly.")
    return patched


# -- Friendly options -----------------------------------------------------

# (option, bit, inverted): inverted means the bit is set when the option is off.
SIMPLE_OPTIONS = (
    ("switch", BIT_ALLOW_SWITCH, False),
    ("titlebar", BIT_NO_TITLE_BAR, True),
    ("menubar", BIT_MENU_BAR, False),
    ("stretch", BIT_STRETCH, False),
)
_FULL_SCREEN_BITS = 1 << BIT_MAXIMIZED | 1 << BIT_FULL_SCREEN


def read_options(flags: int) -> dict:
    # Either bit starts the game full screen, so either counts.
    result = {"fullscreen": bool(flags & _FULL_SCREEN_BITS),
              "resolution": bool(flags >> BIT_FULL_SCREEN & 1)}
    for key, bit, inverted in SIMPLE_OPTIONS:
        result[key] = bool(flags >> bit & 1) != inverted
    return result


def apply_options(flags: int, options: dict) -> int:
    """Apply only the options given; every other bit is left alone."""
    for key, bit, inverted in SIMPLE_OPTIONS:
        if key in options:
            if bool(options[key]) != inverted:
                flags |= 1 << bit
            else:
                flags &= ~(1 << bit)
    if "menubar" in options:
        # Show a menu bar at start when there is one.
        if options["menubar"]:
            flags &= ~(1 << BIT_MENU_HIDDEN_AT_START)
        else:
            flags |= 1 << BIT_MENU_HIDDEN_AT_START
    if "fullscreen" in options or "resolution" in options:
        current = read_options(flags)
        fullscreen = options.get("fullscreen", current["fullscreen"])
        resolution = options.get("resolution", current["resolution"])
        flags &= ~_FULL_SCREEN_BITS
        if fullscreen:
            flags |= 1 << BIT_MAXIMIZED
            if resolution:
                flags |= 1 << BIT_FULL_SCREEN
    return flags


if __name__ == "__main__":
    import sys
    for name in sys.argv[1:]:
        try:
            game = load(name)
        except (OSError, NotAGame) as error:
            print(f"{name}: {error}")
            continue
        print(f"{os.path.basename(name)} ({game.product_name}): "
              f"{read_options(game.flags)}")
