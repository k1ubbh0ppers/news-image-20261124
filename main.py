#!/usr/bin/env python3
"""Draw a one-page world-news broadsheet for Tuesday 24 November 2026.

Everything is drawn with the Python standard library alone: a tiny
5-by-7 bitmap face for the type, a hand-rolled PNG reader for the lead
illustration, and a hand-rolled PNG writer for the finished page.
"""

import os
import struct
import zlib

PAGE = 1024                      # the sheet is square, 1024 pixels a side

# Palette. Cream paper, near-black ink, and a brick red / brass gold accent.
CREAM = (247, 243, 231)
SOOT = (24, 34, 43)
ASH = (83, 93, 97)
BRICK = (169, 47, 37)
BRASS = (204, 153, 58)
NAVY = (20, 39, 72)
PALE = (226, 185, 98)
FAINT = (193, 188, 175)


# ---------------------------------------------------------------------------
# Bitmap face
# ---------------------------------------------------------------------------
# One glyph per entry: the seven 5-pixel rows joined into a single string,
# top row first. The page is set entirely in capitals.
GLYPHS = {
    "A": "01110100011000111111100011000110001",
    "B": "11110100011000111110100011000111110",
    "C": "01111100001000010000100001000001111",
    "D": "11110100011000110001100011000111110",
    "E": "11111100001000011110100001000011111",
    "F": "11111100001000011110100001000010000",
    "G": "01111100001000010111100011000101111",
    "H": "10001100011000111111100011000110001",
    "I": "11111001000010000100001000010011111",
    "J": "00111000100001000010100101001001100",
    "K": "10001100101010011000101001001010001",
    "L": "10000100001000010000100001000011111",
    "M": "10001110111010110101100011000110001",
    "N": "10001110011010110011100011000110001",
    "O": "01110100011000110001100011000101110",
    "P": "11110100011000111110100001000010000",
    "Q": "01110100011000110001101011001001101",
    "R": "11110100011000111110101001001010001",
    "S": "01111100001000001110000010000111110",
    "T": "11111001000010000100001000010000100",
    "U": "10001100011000110001100011000101110",
    "V": "10001100011000110001100010101000100",
    "W": "10001100011000110101101011010101010",
    "X": "10001100010101000100010101000110001",
    "Y": "10001100010101000100001000010000100",
    "Z": "11111000010001000100010001000011111",
    "0": "01110100011001110101110011000101110",
    "1": "00100011000010000100001000010001110",
    "2": "01110100010000100010001000100011111",
    "3": "11110000010000101110000010000111110",
    "4": "00010001100101010010111110001000010",
    "5": "11111100001000011110000010000111110",
    "6": "01110100001000011110100011000101110",
    "7": "11111000010001000100010000100001000",
    "8": "01110100011000101110100011000101110",
    "9": "01110100011000101111000010000101110",
    " ": "00000000000000000000000000000000000",
    ".": "00000000000000000000000000011000110",
    ",": "00000000000000000000001100011000100",
    ":": "00000001100011000000001100011000000",
    ";": "00000001100011000000001100011000100",
    "-": "00000000000000011111000000000000000",
    '"': "01010010100101000000000000000000000",
    "'": "00100001000000000000000000000000000",
    "/": "00001000100001000100010000100010000",
    "?": "01110100010000100010001000000000100",
    "+": "00000001000010011111001000010000000",
}


def glyph_rows(ch):
    """Split a glyph's packed string back into its seven rows."""
    packed = GLYPHS.get(ch, GLYPHS[" "])
    return [packed[i * 5:(i + 1) * 5] for i in range(7)]


# ---------------------------------------------------------------------------
# Canvas
# ---------------------------------------------------------------------------
class Sheet:
    """A flat RGB canvas with the drawing helpers the page needs."""

    def __init__(self):
        self.buf = bytearray(CREAM * (PAGE * PAGE))

    def fill(self, x, y, w, h, colour):
        """Paint a solid rectangle, clipped to the sheet."""
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(PAGE, x + w), min(PAGE, y + h)
        if x0 >= x1 or y0 >= y1:
            return
        row = bytes(colour) * (x1 - x0)
        for yy in range(y0, y1):
            at = (yy * PAGE + x0) * 3
            self.buf[at:at + len(row)] = row

    def put_text(self, s, x, y, scale, colour, width=None):
        """Set one string in the bitmap face; returns the y below the last line."""
        s = s.upper()
        step = 6 * scale
        lines = [s]
        if width is not None:
            per_line = max(1, width // step)
            wrapped, current = [], ""
            for word in s.split():
                trial = (current + " " + word).strip()
                if len(trial) > per_line and current:
                    wrapped.append(current)
                    current = word
                else:
                    current = trial
            if current:
                wrapped.append(current)
            lines = wrapped
        yy = y
        for line in lines:
            xx = x
            for ch in line:
                for gy, bits in enumerate(glyph_rows(ch)):
                    for gx, bit in enumerate(bits):
                        if bit == "1":
                            self.fill(xx + gx * scale, yy + gy * scale, scale, scale, colour)
                xx += step
            yy += 9 * scale
        return yy

    def place_photo(self, path, x, y, w, h):
        """Centre-crop a PNG to the target box and scale it in (nearest neighbour)."""
        sw, sh, src = decode_png(path)
        if sw * h > sh * w:
            cw = sh * w // h
            ox, oy, ch = (sw - cw) // 2, 0, sh
        else:
            ch = sw * h // w
            ox, oy, cw = 0, (sh - ch) // 2, sw
        for dy in range(h):
            sy = oy + dy * ch // h
            for dx in range(w):
                sx = ox + dx * cw // w
                si = (sy * sw + sx) * 3
                di = ((y + dy) * PAGE + x + dx) * 3
                self.buf[di:di + 3] = src[si:si + 3]

    def to_png(self):
        """Serialise the canvas as a PNG: one unfiltered scanline per row."""
        raw = b"".join(b"\0" + bytes(self.buf[y * PAGE * 3:(y + 1) * PAGE * 3])
                       for y in range(PAGE))

        def chunk(tag, payload):
            return (struct.pack(">I", len(payload)) + tag + payload
                    + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

        return (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", PAGE, PAGE, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9))
                + chunk(b"IEND", b""))


# ---------------------------------------------------------------------------
# PNG reading (for the lead illustration)
# ---------------------------------------------------------------------------
def decode_png(path):
    """Decode a non-interlaced 8-bit RGB/RGBA PNG into raw RGB bytes."""
    data = open(path, "rb").read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("lead illustration is not a PNG")
    pos = 8
    packed = bytearray()
    width = height = depth = ctype = interlace = None
    while pos < len(data):
        size = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + size]
        pos += size + 12
        if kind == b"IHDR":
            width, height, depth, ctype, _comp, _filt, interlace = struct.unpack(">IIBBBBB", chunk)
        elif kind == b"IDAT":
            packed.extend(chunk)
        elif kind == b"IEND":
            break
    if (depth, interlace) != (8, 0) or ctype not in (2, 6):
        raise ValueError("expected a non-interlaced RGB or RGBA PNG")
    channels = 3 if ctype == 2 else 4
    raw = zlib.decompress(packed)
    stride = width * channels
    out = bytearray(height * width * 3)
    p = 0
    prev = bytearray(stride)
    for y in range(height):
        f = raw[p]
        p += 1
        row = bytearray(raw[p:p + stride])
        p += stride
        for i in range(stride):
            a = row[i - channels] if i >= channels else 0
            b = prev[i]
            c = prev[i - channels] if i >= channels else 0
            if f == 1:
                row[i] = (row[i] + a) & 255
            elif f == 2:
                row[i] = (row[i] + b) & 255
            elif f == 3:
                row[i] = (row[i] + ((a + b) // 2)) & 255
            elif f == 4:
                q = a + b - c
                pa, pb, pc = abs(q - a), abs(q - b), abs(q - c)
                row[i] = (row[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
            elif f != 0:
                raise ValueError("unknown PNG filter")
        prev = row
        for x in range(width):
            si = x * channels
            di = (y * width + x) * 3
            out[di:di + 3] = row[si:si + 3]
    return width, height, out


# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------
def masthead(sheet):
    """The nameplate, the date line, and the rules that frame them."""
    sheet.fill(32, 26, 960, 4, SOOT)
    sheet.put_text("THE WORLD / TUESDAY EDITION", 42, 40, 3, SOOT)
    sheet.put_text("TUESDAY 24 NOVEMBER 2026", 536, 43, 2, BRICK)
    sheet.fill(32, 75, 960, 2, SOOT)


def hero_band(sheet):
    """The lead illustration on the left, the In Focus panel on the right."""
    sheet.fill(32, 91, 960, 296, NAVY)
    sheet.place_photo(os.path.join(os.path.dirname(__file__), "assets", "hero.png"),
                      32, 91, 444, 296)
    sheet.fill(476, 91, 516, 296, NAVY)
    sheet.fill(516, 145, 54, 4, BRASS)
    sheet.put_text("TUESDAY", 516, 174, 4, CREAM)
    sheet.put_text("IN FOCUS", 516, 224, 4, CREAM)
    sheet.put_text("SIX STORIES. ONE DAY.", 516, 294, 2, PALE)
    sheet.fill(32, 387, 960, 3, SOOT)


def lead_story(sheet):
    """The Hormuz story, set large across the full width."""
    sheet.put_text("HORMUZ / IRAN SAYS FOUR TANKERS HIT MINES; IRGC CLAIMS SHIP ATTACK",
                   42, 405, 3, BRICK, 940)
    sheet.put_text("IRAN SAID FOUR TANKERS HIT NAVAL MINES IN THE STRAIT OF HORMUZ AND CAUGHT "
                   "FIRE. ITS GUARD SAID ITS NAVY ALSO HIT A CONTAINER SHIP.",
                   42, 465, 2, SOOT, 940)
    sheet.fill(32, 515, 960, 3, SOOT)


# The five shorter dispatches, each a tag, a headline and one deck line.
DISPATCHES = [
    {"tag": "HUAWEI",
     "head": "US JURY CONVICTS HUAWEI OF TRADE-SECRET THEFT",
     "body": "GUILTY OF TRADE SECRETS AND BANK FRAUD; RACKETEERING CHARGE DROPPED."},
    {"tag": "UKRAINE",
     "head": "UKRAINE HITS RUSSIAN SHIPS IN FINLAND GULF AND OFF LIBYA",
     "body": "KYIV CONFIRMED DRONE STRIKES ON SPARTA II AND A WARSHIP."},
    {"tag": "YEMEN",
     "head": "HOUTHIS 60 KM FROM ADEN; RIYADH TOWER HIT",
     "body": "11 WOUNDED IN SUSPECTED DRONE ATTACK ON RIYADH TOWER."},
    {"tag": "SPACE",
     "head": "CHINA LAUNCHES SHENZHOU 24 WITH PAKISTANI ASTRONAUT",
     "body": "FIRST FOREIGN ASTRONAUT TO FLY TO TIANGONG STATION."},
    {"tag": "TURKIYE",
     "head": "AIR FORCE HELICOPTER CRASH KILLS FIVE",
     "body": "AS-532 WENT DOWN AFTER TAKEOFF FROM ESKISEHIR."},
]


def dispatch_columns(sheet):
    """Set the five dispatches in two columns, three rows on the left."""
    columns = [42, 526]
    width = 456
    top = 534
    pitch = 156
    for i, item in enumerate(DISPATCHES):
        col, row = i // 3, i % 3
        x = columns[col]
        y = top + row * pitch
        sheet.fill(x, y, 34, 3, BRASS)
        sheet.put_text(item["tag"], x, y + 10, 2, BRICK)
        below_head = sheet.put_text(item["head"], x, y + 32, 2, SOOT, width)
        sheet.put_text(item["body"], x, below_head + 5, 2, ASH, width)
        if row < 2:
            sheet.fill(x, y + pitch - 9, width, 1, FAINT)


def main():
    """Compose the page and write it out as entry.png."""
    sheet = Sheet()
    masthead(sheet)
    hero_band(sheet)
    lead_story(sheet)
    dispatch_columns(sheet)
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "entry.png"), "wb") as fh:
        fh.write(sheet.to_png())


if __name__ == "__main__":
    main()
