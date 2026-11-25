#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=10.0.0"]
# ///
from __future__ import annotations

import argparse
import json
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Full printable ASCII (32..126) 5x7 bitmap font; each int is a 5-bit row.
FONT_5X7: dict[int, tuple[int, int, int, int, int, int, int]] = {
    32: (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00),  # ' '
    33: (0x04, 0x04, 0x04, 0x04, 0x04, 0x00, 0x04),  # '!'
    34: (0x0A, 0x0A, 0x0A, 0x00, 0x00, 0x00, 0x00),  # '"'
    35: (0x0A, 0x0A, 0x1F, 0x0A, 0x1F, 0x0A, 0x0A),  # '#'
    36: (0x04, 0x0F, 0x14, 0x0E, 0x05, 0x1E, 0x04),  # '$'
    37: (0x18, 0x19, 0x02, 0x04, 0x08, 0x13, 0x03),  # '%'
    38: (0x0C, 0x12, 0x14, 0x08, 0x15, 0x12, 0x0D),  # '&'
    39: (0x04, 0x04, 0x08, 0x00, 0x00, 0x00, 0x00),  # "'"
    40: (0x02, 0x04, 0x08, 0x08, 0x08, 0x04, 0x02),  # '('
    41: (0x08, 0x04, 0x02, 0x02, 0x02, 0x04, 0x08),  # ')'
    42: (0x00, 0x04, 0x15, 0x0E, 0x15, 0x04, 0x00),  # '*'
    43: (0x00, 0x04, 0x04, 0x1F, 0x04, 0x04, 0x00),  # '+'
    44: (0x00, 0x00, 0x00, 0x00, 0x04, 0x04, 0x08),  # ','
    45: (0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00),  # '-'
    46: (0x00, 0x00, 0x00, 0x00, 0x00, 0x0C, 0x0C),  # '.'
    47: (0x01, 0x01, 0x02, 0x04, 0x08, 0x10, 0x10),  # '/'
    48: (0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E),  # '0'
    49: (0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E),  # '1'
    50: (0x0E, 0x11, 0x01, 0x06, 0x08, 0x10, 0x1F),  # '2'
    51: (0x1F, 0x02, 0x04, 0x06, 0x01, 0x11, 0x0E),  # '3'
    52: (0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02),  # '4'
    53: (0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E),  # '5'
    54: (0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E),  # '6'
    55: (0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08),  # '7'
    56: (0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E),  # '8'
    57: (0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C),  # '9'
    58: (0x00, 0x0C, 0x0C, 0x00, 0x0C, 0x0C, 0x00),  # ':'
    59: (0x00, 0x0C, 0x0C, 0x00, 0x0C, 0x04, 0x08),  # ';'
    60: (0x02, 0x04, 0x08, 0x10, 0x08, 0x04, 0x02),  # '<'
    61: (0x00, 0x00, 0x1F, 0x00, 0x1F, 0x00, 0x00),  # '='
    62: (0x08, 0x04, 0x02, 0x01, 0x02, 0x04, 0x08),  # '>'
    63: (0x0E, 0x11, 0x01, 0x02, 0x04, 0x00, 0x04),  # '?'
    64: (0x0E, 0x11, 0x17, 0x15, 0x17, 0x10, 0x0E),  # '@'
    65: (0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),  # 'A'
    66: (0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E),  # 'B'
    67: (0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E),  # 'C'
    68: (0x1E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1E),  # 'D'
    69: (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F),  # 'E'
    70: (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10),  # 'F'
    71: (0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0F),  # 'G'
    72: (0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),  # 'H'
    73: (0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E),  # 'I'
    74: (0x07, 0x02, 0x02, 0x02, 0x02, 0x12, 0x0C),  # 'J'
    75: (0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11),  # 'K'
    76: (0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F),  # 'L'
    77: (0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11),  # 'M'
    78: (0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11),  # 'N'
    79: (0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),  # 'O'
    80: (0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10),  # 'P'
    81: (0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D),  # 'Q'
    82: (0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11),  # 'R'
    83: (0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E),  # 'S'
    84: (0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04),  # 'T'
    85: (0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),  # 'U'
    86: (0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04),  # 'V'
    87: (0x11, 0x11, 0x11, 0x15, 0x15, 0x1B, 0x11),  # 'W'
    88: (0x11, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x11),  # 'X'
    89: (0x11, 0x11, 0x0A, 0x04, 0x04, 0x04, 0x04),  # 'Y'
    90: (0x1F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1F),  # 'Z'
    91: (0x0E, 0x08, 0x08, 0x08, 0x08, 0x08, 0x0E),  # '['
    92: (0x10, 0x10, 0x08, 0x04, 0x02, 0x01, 0x01),  # '\'
    93: (0x0E, 0x02, 0x02, 0x02, 0x02, 0x02, 0x0E),  # ']'
    94: (0x04, 0x0A, 0x11, 0x00, 0x00, 0x00, 0x00),  # '^'
    95: (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x1F),  # '_'
    96: (0x08, 0x04, 0x02, 0x00, 0x00, 0x00, 0x00),  # '`'
    97: (0x00, 0x00, 0x0E, 0x01, 0x0F, 0x11, 0x0F),  # 'a'
    98: (0x10, 0x10, 0x1E, 0x11, 0x11, 0x11, 0x1E),  # 'b'
    99: (0x00, 0x00, 0x0E, 0x10, 0x10, 0x11, 0x0E),  # 'c'
    100: (0x01, 0x01, 0x0F, 0x11, 0x11, 0x11, 0x0F),  # 'd'
    101: (0x00, 0x00, 0x0E, 0x11, 0x1F, 0x10, 0x0E),  # 'e'
    102: (0x06, 0x08, 0x08, 0x1E, 0x08, 0x08, 0x08),  # 'f'
    103: (0x00, 0x0F, 0x11, 0x11, 0x0F, 0x01, 0x0E),  # 'g'
    104: (0x10, 0x10, 0x1E, 0x11, 0x11, 0x11, 0x11),  # 'h'
    105: (0x04, 0x00, 0x0C, 0x04, 0x04, 0x04, 0x0E),  # 'i'
    106: (0x02, 0x00, 0x06, 0x02, 0x02, 0x12, 0x0C),  # 'j'
    107: (0x10, 0x10, 0x12, 0x14, 0x18, 0x14, 0x12),  # 'k'
    108: (0x0C, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E),  # 'l'
    109: (0x00, 0x00, 0x1A, 0x15, 0x15, 0x15, 0x11),  # 'm'
    110: (0x00, 0x00, 0x1E, 0x11, 0x11, 0x11, 0x11),  # 'n'
    111: (0x00, 0x00, 0x0E, 0x11, 0x11, 0x11, 0x0E),  # 'o'
    112: (0x00, 0x00, 0x1E, 0x11, 0x1E, 0x10, 0x10),  # 'p'
    113: (0x00, 0x00, 0x0F, 0x11, 0x0F, 0x01, 0x01),  # 'q'
    114: (0x00, 0x00, 0x16, 0x19, 0x10, 0x10, 0x10),  # 'r'
    115: (0x00, 0x00, 0x0F, 0x10, 0x0E, 0x01, 0x1E),  # 's'
    116: (0x08, 0x08, 0x1E, 0x08, 0x08, 0x09, 0x06),  # 't'
    117: (0x00, 0x00, 0x11, 0x11, 0x11, 0x13, 0x0D),  # 'u'
    118: (0x00, 0x00, 0x11, 0x11, 0x11, 0x0A, 0x04),  # 'v'
    119: (0x00, 0x00, 0x11, 0x11, 0x15, 0x15, 0x0A),  # 'w'
    120: (0x00, 0x00, 0x11, 0x0A, 0x04, 0x0A, 0x11),  # 'x'
    121: (0x00, 0x00, 0x11, 0x11, 0x0F, 0x01, 0x0E),  # 'y'
    122: (0x00, 0x00, 0x1F, 0x02, 0x04, 0x08, 0x1F),  # 'z'
    123: (0x02, 0x04, 0x04, 0x08, 0x04, 0x04, 0x02),  # '{'
    124: (0x04, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04),  # '|'
    125: (0x08, 0x04, 0x04, 0x02, 0x04, 0x04, 0x08),  # '}'
    126: (0x00, 0x00, 0x08, 0x15, 0x02, 0x00, 0x00),  # '~'
}

_UNICODE_ASCII_MAP = str.maketrans({
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2013": "-",
    "\u2014": "-",
    "\u2026": "...",
    "\u2192": "->",
    "\u2190": "<-",
    "\u00a0": " ",
})

BG_SLIDE = (15, 23, 42)
BG_STRIP = (9, 13, 22)
STRIP_DIVIDER = (51, 65, 85)
TEXT_PRIMARY = (248, 250, 252)
TEXT_SUBTITLE = (241, 245, 249)
TEXT_MUTED = (148, 163, 184)
EDGE_COLOR = (148, 163, 184)
EDGE_PILL_BG = (30, 41, 59)
EDGE_PILL_BORDER = (71, 85, 105)
FRAME_BORDER = (71, 85, 105)
LABEL_BG = (30, 41, 59)
LABEL_BORDER = (56, 189, 248)

STATUS_PALETTE: dict[str, tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]] = {
    "done": ((20, 83, 45), (34, 197, 94), (220, 252, 231)),
    "pass": ((20, 83, 45), (34, 197, 94), (220, 252, 231)),
    "passed": ((20, 83, 45), (34, 197, 94), (220, 252, 231)),
    "ok": ((20, 83, 45), (34, 197, 94), (220, 252, 231)),
    "merged": ((20, 83, 45), (34, 197, 94), (220, 252, 231)),
    "ready": ((20, 83, 45), (34, 197, 94), (220, 252, 231)),
    "green": ((20, 83, 45), (34, 197, 94), (220, 252, 231)),
    "running": ((69, 26, 3), (245, 158, 11), (254, 243, 199)),
    "active": ((69, 26, 3), (245, 158, 11), (254, 243, 199)),
    "pending": ((69, 26, 3), (245, 158, 11), (254, 243, 199)),
    "in_progress": ((69, 26, 3), (245, 158, 11), (254, 243, 199)),
    "warn": ((69, 26, 3), (245, 158, 11), (254, 243, 199)),
    "amber": ((69, 26, 3), (245, 158, 11), (254, 243, 199)),
    "failed": ((69, 10, 10), (239, 68, 68), (254, 226, 226)),
    "fail": ((69, 10, 10), (239, 68, 68), (254, 226, 226)),
    "error": ((69, 10, 10), (239, 68, 68), (254, 226, 226)),
    "blocked": ((69, 10, 10), (239, 68, 68), (254, 226, 226)),
    "red": ((69, 10, 10), (239, 68, 68), (254, 226, 226)),
}
DEFAULT_NODE_COLORS = ((30, 41, 59), (56, 189, 248), (226, 232, 240))


def _build_glyph_runs() -> dict[int, tuple[tuple[tuple[int, int], ...], ...]]:
    runs: dict[int, tuple[tuple[tuple[int, int], ...], ...]] = {}
    for code, rows in FONT_5X7.items():
        row_runs: list[tuple[tuple[int, int], ...]] = []
        for mask in rows:
            spans: list[tuple[int, int]] = []
            x = 0
            while x < 5:
                if (mask >> (4 - x)) & 1:
                    start = x
                    while x < 5 and ((mask >> (4 - x)) & 1):
                        x += 1
                    spans.append((start, x - start))
                else:
                    x += 1
            row_runs.append(tuple(spans))
        runs[code] = tuple(row_runs)
    return runs


GLYPH_RUNS = _build_glyph_runs()

SYSTEM_FONT_CANDIDATES: tuple[str, ...] = (
    "/System/Library/Fonts/SFNS.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)

TRUETYPE_PIXEL_SIZES: dict[int, int] = {
    2: 18,
    3: 26,
}


class TextBackend:
    def __init__(
        self,
        name: str,
        font_path: str | None,
        pil_image: Any = None,
        pil_draw: Any = None,
        pil_font: Any = None,
    ) -> None:
        self.name = name
        self.font_path = font_path
        self._pil_image = pil_image
        self._pil_draw = pil_draw
        self._pil_font = pil_font
        self._fonts: dict[int, tuple[Any, int, int]] = {}

    @property
    def is_truetype(self) -> bool:
        return self.name == "pillow-truetype" and self.font_path is not None

    def _get_font(self, scale: int) -> tuple[Any, int, int]:
        cached = self._fonts.get(scale)
        if cached is not None:
            return cached
        px_size = TRUETYPE_PIXEL_SIZES.get(scale, max(12, scale * 9))
        font = self._pil_font.truetype(self.font_path, px_size)
        sample_bb = font.getbbox("AgypQ|[]")
        ink_top = int(sample_bb[1])
        ink_h = max(1, int(sample_bb[3] - sample_bb[1]))
        entry = (font, ink_top, ink_h)
        self._fonts[scale] = entry
        return entry

    def glyph_height(self, scale: int) -> int:
        if self.is_truetype:
            return self._get_font(scale)[2]
        return 7 * scale

    def line_gap(self, scale: int) -> int:
        if self.is_truetype:
            return 6 if scale == 3 else 5
        return 7 if scale == 3 else 6

    def line_step(self, scale: int) -> int:
        return self.glyph_height(scale) + self.line_gap(scale)

    def measure_width(self, text: str, scale: int) -> int:
        if not text:
            return 0
        norm = _normalize_text(text)
        if self.is_truetype:
            font, _, _ = self._get_font(scale)
            return int(math.ceil(font.getlength(norm)))
        return len(norm) * 6 * scale - scale

    def draw_on_canvas(
        self,
        canvas: Canvas,
        x: int,
        y: int,
        text: str,
        rgb: tuple[int, int, int],
        scale: int = 2,
    ) -> None:
        norm = _normalize_text(text)
        if not norm:
            return

        if not self.is_truetype:
            cursor_x = x
            step_x = 6 * scale
            raw = canvas.raw
            row_bytes = canvas.row_bytes
            cx0, cy0, cx1, cy1 = canvas.clip_x0, canvas.clip_y0, canvas.clip_x1, canvas.clip_y1
            rgb_bytes = bytes(rgb)

            for ch in norm:
                code = ord(ch)
                runs = GLYPH_RUNS.get(code) or GLYPH_RUNS[63]
                if cursor_x + 5 * scale > cx0 and cursor_x < cx1:
                    for gy, row_spans in enumerate(runs):
                        if not row_spans:
                            continue
                        py0 = y + gy * scale
                        py1 = py0 + scale
                        ry0 = max(cy0, py0)
                        ry1 = min(cy1, py1)
                        if ry0 >= ry1:
                            continue
                        for sx, slen in row_spans:
                            px0 = max(cx0, cursor_x + sx * scale)
                            px1 = min(cx1, cursor_x + (sx + slen) * scale)
                            if px0 >= px1:
                                continue
                            span = rgb_bytes * (px1 - px0)
                            span_len = len(span)
                            base_x = 1 + px0 * 3
                            for py in range(ry0, ry1):
                                off = py * row_bytes + base_x
                                raw[off : off + span_len] = span
                cursor_x += step_x
            return

        font, ink_top, _ = self._get_font(scale)
        left, top, right, bottom = font.getbbox(norm)
        if right <= left or bottom <= top:
            return
        pad = 2
        mw = int(right - left) + 2 * pad
        mh = int(bottom - top) + 2 * pad
        mask = self._pil_image.new("L", (mw, mh), 0)
        self._pil_draw.Draw(mask).text((pad - left, pad - top), norm, fill=255, font=font)

        dst_x = x + int(left) - pad
        dst_y = y + int(top) - ink_top - pad
        cx0 = max(canvas.clip_x0, dst_x)
        cy0 = max(canvas.clip_y0, dst_y)
        cx1 = min(canvas.clip_x1, dst_x + mw)
        cy1 = min(canvas.clip_y1, dst_y + mh)
        if cx0 >= cx1 or cy0 >= cy1:
            return

        mask_bytes = mask.tobytes()
        r_fg, g_fg, b_fg = rgb
        raw = canvas.raw
        row_bytes = canvas.row_bytes
        src_x_off = cx0 - dst_x
        span_w = cx1 - cx0

        for py in range(cy0, cy1):
            m_row = (py - dst_y) * mw + src_x_off
            dst_off = py * row_bytes + 1 + cx0 * 3
            for i in range(span_w):
                alpha = mask_bytes[m_row + i]
                if alpha == 255:
                    raw[dst_off] = r_fg
                    raw[dst_off + 1] = g_fg
                    raw[dst_off + 2] = b_fg
                elif alpha > 0:
                    inv = 255 - alpha
                    raw[dst_off] = (r_fg * alpha + raw[dst_off] * inv) // 255
                    raw[dst_off + 1] = (g_fg * alpha + raw[dst_off + 1] * inv) // 255
                    raw[dst_off + 2] = (b_fg * alpha + raw[dst_off + 2] * inv) // 255
                dst_off += 3


def resolve_text_backend(font_candidates: tuple[str, ...] = SYSTEM_FONT_CANDIDATES) -> TextBackend:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except (ImportError, OSError):
        return TextBackend(name="bitmap-5x7", font_path=None)

    for candidate in font_candidates:
        if not Path(candidate).is_file():
            continue
        try:
            ImageFont.truetype(candidate, TRUETYPE_PIXEL_SIZES[2])
        except OSError:
            continue
        return TextBackend(
            name="pillow-truetype",
            font_path=candidate,
            pil_image=Image,
            pil_draw=ImageDraw,
            pil_font=ImageFont,
        )

    return TextBackend(name="bitmap-5x7", font_path=None)


class KetchupRenderError(Exception):
    pass


@dataclass(frozen=True)
class EnvStatus:
    ok: bool
    ffmpeg: str | None
    ffprobe: str | None
    encoders: dict[str, bool]
    renderer: str
    text_backend: str
    font_path: str | None
    fallback: str | None
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "ffmpeg": self.ffmpeg,
            "ffprobe": self.ffprobe,
            "encoders": self.encoders,
            "renderer": self.renderer,
            "text_backend": self.text_backend,
            "font_path": self.font_path,
            "fallback": self.fallback,
            "error": self.error,
        }


@dataclass(frozen=True)
class NodeSpec:
    id: str | None
    label: str
    x: float | None
    y: float | None
    status: str


@dataclass(frozen=True)
class EdgeSpec:
    source: str
    target: str
    label: str


@dataclass(frozen=True)
class ScreenshotSpec:
    path: Path
    caption: str


@dataclass(frozen=True)
class SlideSpec:
    title: str
    subtitle: str
    labels: tuple[str, ...]
    nodes: tuple[NodeSpec, ...]
    edges: tuple[EdgeSpec, ...]
    screenshots: tuple[ScreenshotSpec, ...]


@dataclass(frozen=True)
class RenderSpec:
    width: int
    height: int
    strip_height: int
    fps: int
    transition_seconds: float
    slides: tuple[SlideSpec, ...]


@dataclass(frozen=True)
class SlideTiming:
    index: int
    added_words: int
    hold_seconds: float
    steady_start: float
    steady_end: float
    input_duration: float
    subtitle_lines: tuple[str, ...] = field(default_factory=tuple)


def check_environment() -> EnvStatus:
    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")
    encoders = {"libx264": False, "png": False}
    text_backend = resolve_text_backend()

    if not ffmpeg_path:
        return EnvStatus(
            ok=False,
            ffmpeg=None,
            ffprobe=ffprobe_path,
            encoders=encoders,
            renderer="pure-python-png+ffmpeg",
            text_backend=text_backend.name,
            font_path=text_backend.font_path,
            fallback="generative_ui",
            error="ffmpeg not found on PATH",
        )

    if not ffprobe_path:
        return EnvStatus(
            ok=False,
            ffmpeg=ffmpeg_path,
            ffprobe=None,
            encoders=encoders,
            renderer="pure-python-png+ffmpeg",
            text_backend=text_backend.name,
            font_path=text_backend.font_path,
            fallback="generative_ui",
            error="ffprobe not found on PATH",
        )

    try:
        proc = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return EnvStatus(
            ok=False,
            ffmpeg=ffmpeg_path,
            ffprobe=ffprobe_path,
            encoders=encoders,
            renderer="pure-python-png+ffmpeg",
            text_backend=text_backend.name,
            font_path=text_backend.font_path,
            fallback="generative_ui",
            error=f"failed to probe ffmpeg encoders: {exc}",
        )

    if proc.returncode != 0:
        return EnvStatus(
            ok=False,
            ffmpeg=ffmpeg_path,
            ffprobe=ffprobe_path,
            encoders=encoders,
            renderer="pure-python-png+ffmpeg",
            text_backend=text_backend.name,
            font_path=text_backend.font_path,
            fallback="generative_ui",
            error=f"ffmpeg -encoders exited with {proc.returncode}",
        )

    encoder_names: set[str] = set()
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("V"):
            encoder_names.add(parts[1])

    encoders["libx264"] = "libx264" in encoder_names
    encoders["png"] = "png" in encoder_names
    missing = [name for name, present in encoders.items() if not present]
    if missing:
        return EnvStatus(
            ok=False,
            ffmpeg=ffmpeg_path,
            ffprobe=ffprobe_path,
            encoders=encoders,
            renderer="pure-python-png+ffmpeg",
            text_backend=text_backend.name,
            font_path=text_backend.font_path,
            fallback="generative_ui",
            error=f"missing required ffmpeg encoders: {', '.join(missing)}",
        )

    return EnvStatus(
        ok=True,
        ffmpeg=ffmpeg_path,
        ffprobe=ffprobe_path,
        encoders=encoders,
        renderer="pure-python-png+ffmpeg",
        text_backend=text_backend.name,
        font_path=text_backend.font_path,
        fallback=None,
        error=None,
    )


def _as_str(value: Any, field_name: str, default: str = "") -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise KetchupRenderError(f"{field_name} must be a string")
    return value


def _as_int(value: Any, field_name: str, default: int, minimum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise KetchupRenderError(f"{field_name} must be an integer")
    if value < minimum:
        raise KetchupRenderError(f"{field_name} must be >= {minimum}")
    return value


def _as_float(value: Any, field_name: str, default: float, minimum: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KetchupRenderError(f"{field_name} must be a number")
    val = float(value)
    if not math.isfinite(val) or val < minimum:
        raise KetchupRenderError(f"{field_name} must be >= {minimum}")
    return val


def _resolve_asset_path(raw_path: str, base_dir: Path) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    rel = base_dir / candidate
    if rel.exists():
        return rel
    return candidate


def parse_spec(raw: dict[str, Any], base_dir: Path) -> RenderSpec:
    if not isinstance(raw, dict):
        raise KetchupRenderError("spec root must be a JSON object")

    width = _as_int(raw.get("width"), "width", 1280, 320)
    height = _as_int(raw.get("height"), "height", 720, 240)
    if width % 2 != 0 or height % 2 != 0:
        raise KetchupRenderError("width and height must be even integers for yuv420p")

    strip_height = _as_int(raw.get("strip_height"), "strip_height", 96, 32)
    if strip_height >= height - 64:
        raise KetchupRenderError("strip_height must leave at least 64px for slide area")

    fps = _as_int(raw.get("fps"), "fps", 30, 1)
    transition_seconds = _as_float(raw.get("transition_seconds"), "transition_seconds", 0.3, 0.0)

    slides_raw = raw.get("slides")
    if not isinstance(slides_raw, list) or not slides_raw:
        raise KetchupRenderError("spec must contain a non-empty 'slides' list")

    slides: list[SlideSpec] = []
    for idx, item in enumerate(slides_raw):
        if not isinstance(item, dict):
            raise KetchupRenderError(f"slides[{idx}] must be an object")

        title = _as_str(item.get("title"), f"slides[{idx}].title")
        subtitle = _as_str(item.get("subtitle"), f"slides[{idx}].subtitle")

        labels_raw = item.get("labels") or []
        if not isinstance(labels_raw, list):
            raise KetchupRenderError(f"slides[{idx}].labels must be a list")
        labels = tuple(_as_str(lbl, f"slides[{idx}].labels[{j}]") for j, lbl in enumerate(labels_raw))

        nodes_raw = item.get("nodes") or []
        if not isinstance(nodes_raw, list):
            raise KetchupRenderError(f"slides[{idx}].nodes must be a list")
        nodes: list[NodeSpec] = []
        for j, node_item in enumerate(nodes_raw):
            if not isinstance(node_item, dict):
                raise KetchupRenderError(f"slides[{idx}].nodes[{j}] must be an object")
            node_id = node_item.get("id")
            if node_id is not None and not isinstance(node_id, str):
                raise KetchupRenderError(f"slides[{idx}].nodes[{j}].id must be a string")
            label = _as_str(node_item.get("label"), f"slides[{idx}].nodes[{j}].label")
            nx = node_item.get("x")
            ny = node_item.get("y")
            if nx is not None and (isinstance(nx, bool) or not isinstance(nx, (int, float))):
                raise KetchupRenderError(f"slides[{idx}].nodes[{j}].x must be numeric")
            if ny is not None and (isinstance(ny, bool) or not isinstance(ny, (int, float))):
                raise KetchupRenderError(f"slides[{idx}].nodes[{j}].y must be numeric")
            status = _as_str(node_item.get("status"), f"slides[{idx}].nodes[{j}].status", "default").lower()
            nodes.append(
                NodeSpec(
                    id=node_id,
                    label=label,
                    x=float(nx) if nx is not None else None,
                    y=float(ny) if ny is not None else None,
                    status=status,
                )
            )

        edges_raw = item.get("edges") or []
        if not isinstance(edges_raw, list):
            raise KetchupRenderError(f"slides[{idx}].edges must be a list")
        edges: list[EdgeSpec] = []
        for j, edge_item in enumerate(edges_raw):
            if not isinstance(edge_item, dict):
                raise KetchupRenderError(f"slides[{idx}].edges[{j}] must be an object")
            source = _as_str(edge_item.get("from"), f"slides[{idx}].edges[{j}].from")
            target = _as_str(edge_item.get("to"), f"slides[{idx}].edges[{j}].to")
            elabel = _as_str(edge_item.get("label"), f"slides[{idx}].edges[{j}].label")
            edges.append(EdgeSpec(source=source, target=target, label=elabel))

        shots_raw: list[Any] = []
        for key in ("screenshots", "images"):
            val = item.get(key)
            if val is not None:
                if not isinstance(val, list):
                    raise KetchupRenderError(f"slides[{idx}].{key} must be a list")
                shots_raw.extend(val)

        screenshots: list[ScreenshotSpec] = []
        for j, shot_item in enumerate(shots_raw):
            if isinstance(shot_item, str):
                shot_path = _resolve_asset_path(shot_item, base_dir)
                caption = ""
            elif isinstance(shot_item, dict):
                raw_p = _as_str(shot_item.get("path"), f"slides[{idx}].screenshots[{j}].path")
                if not raw_p:
                    raise KetchupRenderError(f"slides[{idx}].screenshots[{j}].path cannot be empty")
                shot_path = _resolve_asset_path(raw_p, base_dir)
                caption = _as_str(shot_item.get("caption"), f"slides[{idx}].screenshots[{j}].caption")
            else:
                raise KetchupRenderError(f"slides[{idx}].screenshots[{j}] must be string or object")
            if not shot_path.is_file():
                raise KetchupRenderError(f"screenshot file not found: {shot_path}")
            screenshots.append(ScreenshotSpec(path=shot_path, caption=caption))

        slides.append(
            SlideSpec(
                title=title,
                subtitle=subtitle,
                labels=tuple(labels),
                nodes=tuple(nodes),
                edges=tuple(edges),
                screenshots=tuple(screenshots),
            )
        )

    return RenderSpec(
        width=width,
        height=height,
        strip_height=strip_height,
        fps=fps,
        transition_seconds=transition_seconds,
        slides=tuple(slides),
    )


def count_words(text: str) -> int:
    return len(text.split())


def compute_added_words(slide: SlideSpec, prev: SlideSpec | None) -> int:
    if prev is None:
        total = count_words(slide.title) + count_words(slide.subtitle)
        total += sum(count_words(lbl) for lbl in slide.labels)
        total += sum(count_words(n.label) for n in slide.nodes)
        total += sum(count_words(e.label) for e in slide.edges)
        return total

    total = count_words(slide.subtitle)
    if slide.title != prev.title:
        total += count_words(slide.title)

    prev_labels = Counter(prev.labels)
    for lbl in slide.labels:
        if prev_labels[lbl] > 0:
            prev_labels[lbl] -= 1
        else:
            total += count_words(lbl)

    prev_by_id = {n.id: n.label for n in prev.nodes if n.id is not None}
    prev_unkeyed = Counter(n.label for n in prev.nodes if n.id is None)
    for node in slide.nodes:
        if node.id is not None and node.id in prev_by_id:
            if prev_by_id[node.id] != node.label:
                total += count_words(node.label)
        elif prev_unkeyed[node.label] > 0:
            prev_unkeyed[node.label] -= 1
        else:
            total += count_words(node.label)

    prev_edges = Counter((e.source, e.target, e.label) for e in prev.edges)
    for edge in slide.edges:
        key = (edge.source, edge.target, edge.label)
        if prev_edges[key] > 0:
            prev_edges[key] -= 1
        else:
            total += count_words(edge.label)

    return total


def compute_timings(spec: RenderSpec) -> tuple[list[SlideTiming], float]:
    n = len(spec.slides)
    trans = spec.transition_seconds if n > 1 else 0.0
    holds: list[float] = []
    added_counts: list[int] = []

    for idx, slide in enumerate(spec.slides):
        prev = spec.slides[idx - 1] if idx > 0 else None
        added = compute_added_words(slide, prev)
        hold = max(2.0, float(math.ceil(added / 3)))
        added_counts.append(added)
        holds.append(hold)

    timings: list[SlideTiming] = []
    elapsed = 0.0
    for idx in range(n):
        hold = holds[idx]
        steady_start = round(elapsed + idx * trans, 6)
        steady_end = round(steady_start + hold, 6)
        if n == 1:
            input_dur = hold
        elif idx == 0 or idx == n - 1:
            input_dur = round(hold + trans, 6)
        else:
            input_dur = round(trans + hold + trans, 6)
        timings.append(
            SlideTiming(
                index=idx,
                added_words=added_counts[idx],
                hold_seconds=hold,
                steady_start=steady_start,
                steady_end=steady_end,
                input_duration=input_dur,
            )
        )
        elapsed += hold

    total_duration = round(sum(holds) + (n - 1) * trans, 6)
    return timings, total_duration


def _normalize_text(text: str) -> str:
    return text.translate(_UNICODE_ASCII_MAP)


def _wrap_text(
    text: str,
    max_width: int,
    scale: int,
    max_lines: int,
    text_backend: TextBackend,
) -> list[str]:
    clean = " ".join(_normalize_text(text).split())
    if not clean or max_lines <= 0 or max_width <= 0:
        return []

    lines: list[str] = []
    current = ""
    words = clean.split(" ")
    truncated = False

    for idx, word in enumerate(words):
        if text_backend.measure_width(word, scale) > max_width:
            if current:
                lines.append(current)
                current = ""
                if len(lines) == max_lines:
                    truncated = True
                    break
            rem = word
            while rem and text_backend.measure_width(rem, scale) > max_width:
                cut = 1
                while cut < len(rem) and text_backend.measure_width(rem[: cut + 1], scale) <= max_width:
                    cut += 1
                lines.append(rem[:cut])
                rem = rem[cut:]
                if len(lines) == max_lines:
                    truncated = bool(rem) or (idx + 1 < len(words))
                    break
            if len(lines) == max_lines:
                break
            current = rem
            continue

        candidate = word if not current else f"{current} {word}"
        if text_backend.measure_width(candidate, scale) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
            if len(lines) == max_lines:
                truncated = True
                break

    if not truncated and current:
        if len(lines) < max_lines:
            lines.append(current)
        else:
            truncated = True

    if truncated and lines:
        ellipsis = "..."
        if text_backend.measure_width(ellipsis, scale) <= max_width:
            last = lines[-1]
            while last and text_backend.measure_width(last.rstrip() + ellipsis, scale) > max_width:
                last = last[:-1]
            lines[-1] = (last.rstrip() + ellipsis) if last.rstrip() else ellipsis

    return lines


def _crc32_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def encode_png_rgb(width: int, height: int, raw_scanlines: bytes | bytearray, compress_level: int = 1) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    compressed = zlib.compress(raw_scanlines, level=compress_level)
    return b"".join((
        b"\x89PNG\r\n\x1a\n",
        _crc32_chunk(b"IHDR", ihdr),
        _crc32_chunk(b"IDAT", compressed),
        _crc32_chunk(b"IEND", b""),
    ))


def _paeth_predictor(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def decode_png_rgba(path: Path) -> tuple[int, int, bytes]:
    data = path.read_bytes()
    if len(data) < 8 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise KetchupRenderError(f"invalid PNG signature: {path}")

    pos = 8
    width = 0
    height = 0
    bit_depth = 0
    color_type = 0
    interlace = 0
    palette: bytes = b""
    trns: bytes = b""
    idat_parts: list[bytes] = []

    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        tag = data[pos + 4 : pos + 8]
        payload_start = pos + 8
        payload_end = payload_start + length
        if payload_end + 4 > len(data):
            raise KetchupRenderError(f"truncated PNG chunk in {path}")
        payload = data[payload_start:payload_end]
        pos = payload_end + 4

        if tag == b"IHDR":
            width, height, bit_depth, color_type, comp, flt, interlace = struct.unpack(">IIBBBBB", payload)
            if comp != 0 or flt != 0:
                raise KetchupRenderError(f"unsupported PNG compression/filter method in {path}")
        elif tag == b"PLTE":
            palette = payload
        elif tag == b"tRNS":
            trns = payload
        elif tag == b"IDAT":
            idat_parts.append(payload)
        elif tag == b"IEND":
            break

    if width <= 0 or height <= 0:
        raise KetchupRenderError(f"missing IHDR in {path}")
    if bit_depth != 8 or interlace != 0:
        raise KetchupRenderError(f"only non-interlaced 8-bit PNGs are supported: {path}")

    channels_map = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
    if color_type not in channels_map:
        raise KetchupRenderError(f"unsupported PNG color type {color_type} in {path}")
    bpp = channels_map[color_type]

    raw = zlib.decompress(b"".join(idat_parts))
    stride = width * bpp
    expected_len = height * (1 + stride)
    if len(raw) < expected_len:
        raise KetchupRenderError(f"corrupt PNG image data in {path}")

    prev_row = bytearray(stride)
    unfiltered = bytearray(height * stride)
    for y in range(height):
        src_off = y * (1 + stride)
        ftype = raw[src_off]
        row = bytearray(raw[src_off + 1 : src_off + 1 + stride])
        if ftype == 1:
            for i in range(bpp, stride):
                row[i] = (row[i] + row[i - bpp]) & 0xFF
        elif ftype == 2:
            for i in range(stride):
                row[i] = (row[i] + prev_row[i]) & 0xFF
        elif ftype == 3:
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + ((left + prev_row[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                up = prev_row[i]
                up_left = prev_row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + _paeth_predictor(left, up, up_left)) & 0xFF
        elif ftype != 0:
            raise KetchupRenderError(f"invalid PNG filter type {ftype} in {path}")
        unfiltered[y * stride : (y + 1) * stride] = row
        prev_row = row

    if color_type == 6:
        return width, height, bytes(unfiltered)

    rgba = bytearray(width * height * 4)
    if color_type == 2:
        for i in range(width * height):
            s = i * 3
            d = i * 4
            rgba[d : d + 3] = unfiltered[s : s + 3]
            rgba[d + 3] = 255
    elif color_type == 0:
        for i in range(width * height):
            v = unfiltered[i]
            d = i * 4
            rgba[d] = v
            rgba[d + 1] = v
            rgba[d + 2] = v
            rgba[d + 3] = 255
    elif color_type == 4:
        for i in range(width * height):
            s = i * 2
            v = unfiltered[s]
            d = i * 4
            rgba[d] = v
            rgba[d + 1] = v
            rgba[d + 2] = v
            rgba[d + 3] = unfiltered[s + 1]
    elif color_type == 3:
        if not palette:
            raise KetchupRenderError(f"indexed PNG missing PLTE in {path}")
        for i in range(width * height):
            idx = unfiltered[i]
            p = idx * 3
            d = i * 4
            rgba[d : d + 3] = palette[p : p + 3]
            rgba[d + 3] = trns[idx] if idx < len(trns) else 255

    return width, height, bytes(rgba)


class Canvas:
    def __init__(
        self,
        width: int,
        height: int,
        bg_rgb: tuple[int, int, int],
        text_backend: TextBackend | None = None,
    ) -> None:
        self.width = width
        self.height = height
        self.row_bytes = 1 + width * 3
        row = b"\x00" + bytes(bg_rgb) * width
        self.raw = bytearray(row * height)
        self.clip_x0 = 0
        self.clip_y0 = 0
        self.clip_x1 = width
        self.clip_y1 = height
        self.text_backend = text_backend if text_backend is not None else resolve_text_backend()

    def set_clip(self, x0: int, y0: int, x1: int, y1: int) -> None:
        self.clip_x0 = max(0, x0)
        self.clip_y0 = max(0, y0)
        self.clip_x1 = min(self.width, x1)
        self.clip_y1 = min(self.height, y1)

    def fill_rect(self, x0: int, y0: int, x1: int, y1: int, rgb: tuple[int, int, int]) -> None:
        cx0 = max(self.clip_x0, x0)
        cy0 = max(self.clip_y0, y0)
        cx1 = min(self.clip_x1, x1)
        cy1 = min(self.clip_y1, y1)
        if cx0 >= cx1 or cy0 >= cy1:
            return
        span = bytes(rgb) * (cx1 - cx0)
        span_len = len(span)
        row_bytes = self.row_bytes
        raw = self.raw
        base_x = 1 + cx0 * 3
        for y in range(cy0, cy1):
            off = y * row_bytes + base_x
            raw[off : off + span_len] = span

    def stroke_rect(self, x0: int, y0: int, x1: int, y1: int, rgb: tuple[int, int, int], thickness: int = 2) -> None:
        self.fill_rect(x0, y0, x1, y0 + thickness, rgb)
        self.fill_rect(x0, y1 - thickness, x1, y1, rgb)
        self.fill_rect(x0, y0, x0 + thickness, y1, rgb)
        self.fill_rect(x1 - thickness, y0, x1, y1, rgb)

    def draw_line(
        self,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        rgb: tuple[int, int, int],
        thickness: int = 2,
    ) -> None:
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        half = thickness // 2
        x, y = x0, y0
        while True:
            self.fill_rect(x - half, y - half, x - half + thickness, y - half + thickness, rgb)
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x += sx
            if e2 <= dx:
                err += dx
                y += sy

    def draw_arrow(self, x0: int, y0: int, x1: int, y1: int, rgb: tuple[int, int, int], thickness: int = 2) -> None:
        self.draw_line(x0, y0, x1, y1, rgb, thickness=thickness)
        angle = math.atan2(y1 - y0, x1 - x0)
        head_len = 11.0
        for delta in (2.65, -2.65):
            ax = int(round(x1 + head_len * math.cos(angle + delta)))
            ay = int(round(y1 + head_len * math.sin(angle + delta)))
            self.draw_line(x1, y1, ax, ay, rgb, thickness=thickness)

    def draw_text(self, x: int, y: int, text: str, rgb: tuple[int, int, int], scale: int = 2) -> None:
        self.text_backend.draw_on_canvas(self, x, y, text, rgb, scale=scale)

    def blit_rgba_scaled(
        self,
        src_w: int,
        src_h: int,
        src_rgba: bytes,
        dst_x: int,
        dst_y: int,
        dst_w: int,
        dst_h: int,
    ) -> None:
        if dst_w <= 0 or dst_h <= 0 or src_w <= 0 or src_h <= 0:
            return
        cx0 = max(self.clip_x0, dst_x)
        cy0 = max(self.clip_y0, dst_y)
        cx1 = min(self.clip_x1, dst_x + dst_w)
        cy1 = min(self.clip_y1, dst_y + dst_h)
        if cx0 >= cx1 or cy0 >= cy1:
            return

        x_map = [min(src_w - 1, ((dx - dst_x) * src_w) // dst_w) for dx in range(cx0, cx1)]
        row_bytes = self.row_bytes
        raw = self.raw
        for dy in range(cy0, cy1):
            sy = min(src_h - 1, ((dy - dst_y) * src_h) // dst_h)
            src_row = sy * src_w * 4
            dst_off = dy * row_bytes + 1 + cx0 * 3
            for sx in x_map:
                sp = src_row + sx * 4
                alpha = src_rgba[sp + 3]
                if alpha == 255:
                    raw[dst_off] = src_rgba[sp]
                    raw[dst_off + 1] = src_rgba[sp + 1]
                    raw[dst_off + 2] = src_rgba[sp + 2]
                elif alpha > 0:
                    inv = 255 - alpha
                    raw[dst_off] = (src_rgba[sp] * alpha + raw[dst_off] * inv) // 255
                    raw[dst_off + 1] = (src_rgba[sp + 1] * alpha + raw[dst_off + 1] * inv) // 255
                    raw[dst_off + 2] = (src_rgba[sp + 2] * alpha + raw[dst_off + 2] * inv) // 255
                dst_off += 3

    def to_png_bytes(self, compress_level: int = 1) -> bytes:
        return encode_png_rgb(self.width, self.height, self.raw, compress_level=compress_level)


def _node_colors(status: str) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    return STATUS_PALETTE.get(status, DEFAULT_NODE_COLORS)


def _compute_node_boxes(
    nodes: tuple[NodeSpec, ...],
    zone_x0: int,
    zone_y0: int,
    zone_x1: int,
    zone_y1: int,
    has_edge_labels: bool = False,
) -> dict[str, tuple[int, int, int, int, NodeSpec]]:
    n = len(nodes)
    zone_w = max(200, zone_x1 - zone_x0)
    zone_h = max(120, zone_y1 - zone_y0)
    cols = min(n, 3 if n > 4 else n)
    rows = math.ceil(n / max(1, cols))
    gap_x = 120 if (has_edge_labels and cols > 1) else 56
    gap_y = 64 if (has_edge_labels and rows > 1) else 44
    box_w = min(260, max(140, (zone_w - (cols + 1) * gap_x) // max(1, cols)))
    box_h = min(116, max(72, (zone_h - (rows + 1) * gap_y) // max(1, rows)))

    boxes: dict[str, tuple[int, int, int, int, NodeSpec]] = {}
    for idx, node in enumerate(nodes):
        key = node.id if node.id is not None else node.label
        if node.x is not None and node.y is not None:
            px = zone_x0 + int(node.x * zone_w) if 0.0 <= node.x <= 1.0 else int(node.x)
            py = zone_y0 + int(node.y * zone_h) if 0.0 <= node.y <= 1.0 else int(node.y)
            x0 = max(zone_x0 + 8, min(zone_x1 - box_w - 8, px - box_w // 2))
            y0 = max(zone_y0 + 8, min(zone_y1 - box_h - 8, py - box_h // 2))
        else:
            col = idx % cols
            row = idx // cols
            row_items = min(cols, n - row * cols)
            row_total_w = row_items * box_w + max(0, row_items - 1) * gap_x
            start_x = zone_x0 + (zone_w - row_total_w) // 2
            total_h = rows * box_h + max(0, rows - 1) * gap_y
            start_y = zone_y0 + (zone_h - total_h) // 2
            x0 = start_x + col * (box_w + gap_x)
            y0 = start_y + row * (box_h + gap_y)
        boxes[key] = (x0, y0, x0 + box_w, y0 + box_h, node)
    return boxes


def _draw_node_diagram(
    canvas: Canvas,
    nodes: tuple[NodeSpec, ...],
    edges: tuple[EdgeSpec, ...],
    zone_x0: int,
    zone_y0: int,
    zone_x1: int,
    zone_y1: int,
) -> None:
    has_edge_labels = any(bool(e.label) for e in edges)
    boxes = _compute_node_boxes(nodes, zone_x0, zone_y0, zone_x1, zone_y1, has_edge_labels=has_edge_labels)
    pending_pills: list[tuple[int, int, str]] = []

    for edge in edges:
        src_box = boxes.get(edge.source)
        dst_box = boxes.get(edge.target)
        if not src_box or not dst_box:
            continue
        sx0, sy0, sx1, sy1, _ = src_box
        dx0, dy0, dx1, dy1, _ = dst_box
        scx, scy = (sx0 + sx1) // 2, (sy0 + sy1) // 2
        dcx, dcy = (dx0 + dx1) // 2, (dy0 + dy1) // 2

        if abs(dcx - scx) >= abs(dcy - scy):
            p0 = (sx1 + 2, scy) if dcx >= scx else (sx0 - 2, scy)
            p1 = (dx0 - 4, dcy) if dcx >= scx else (dx1 + 4, dcy)
        else:
            p0 = (scx, sy1 + 2) if dcy >= scy else (scx, sy0 - 2)
            p1 = (dcx, dy0 - 4) if dcy >= scy else (dcx, dy1 + 4)

        canvas.draw_arrow(p0[0], p0[1], p1[0], p1[1], EDGE_COLOR, thickness=2)
        if edge.label:
            pending_pills.append(((p0[0] + p1[0]) // 2, (p0[1] + p1[1]) // 2, edge.label))

    backend = canvas.text_backend
    glyph_h2 = backend.glyph_height(2)
    gap2 = backend.line_gap(2)
    line_h2 = backend.line_step(2)

    for x0, y0, x1, y1, node in boxes.values():
        fill_rgb, border_rgb, text_rgb = _node_colors(node.status)
        canvas.fill_rect(x0, y0, x1, y1, fill_rgb)
        canvas.stroke_rect(x0, y0, x1, y1, border_rgb, thickness=2)
        inner_w = (x1 - x0) - 20
        lines = _wrap_text(node.label, inner_w, scale=2, max_lines=3, text_backend=backend)
        total_th = len(lines) * glyph_h2 + max(0, len(lines) - 1) * gap2 if lines else 0
        ty = y0 + max(8, ((y1 - y0) - total_th) // 2)
        for line in lines:
            tw = backend.measure_width(line, scale=2)
            tx = x0 + max(8, ((x1 - x0) - tw) // 2)
            canvas.draw_text(tx, ty, line, text_rgb, scale=2)
            ty += line_h2

    for mx, my, label in pending_pills:
        lines = _wrap_text(label, 140, scale=2, max_lines=1, text_backend=backend)
        if lines:
            tw = backend.measure_width(lines[0], scale=2)
            half_h = max(12, glyph_h2 // 2 + 5)
            px0, py0 = mx - tw // 2 - 8, my - half_h
            px1, py1 = mx + tw // 2 + 8, my + half_h
            canvas.fill_rect(px0, py0, px1, py1, EDGE_PILL_BG)
            canvas.stroke_rect(px0, py0, px1, py1, EDGE_PILL_BORDER, thickness=1)
            canvas.draw_text(mx - tw // 2, my - glyph_h2 // 2, lines[0], TEXT_PRIMARY, scale=2)


def _draw_labels_row(
    canvas: Canvas,
    labels: tuple[str, ...],
    zone_x0: int,
    zone_y0: int,
    zone_x1: int,
    zone_y1: int,
) -> None:
    backend = canvas.text_backend
    glyph_h2 = backend.glyph_height(2)
    gap2 = backend.line_gap(2)
    line_h2 = backend.line_step(2)
    n = len(labels)
    zone_w = max(160, zone_x1 - zone_x0)
    cols = min(n, 3)
    rows = math.ceil(n / cols)
    card_w = min(360, max(160, (zone_w - (cols + 1) * 20) // cols))
    card_h = min(84, max(48, ((zone_y1 - zone_y0) - (rows + 1) * 16) // rows))
    total_h = rows * card_h + max(0, rows - 1) * 16
    start_y = zone_y0 + max(4, ((zone_y1 - zone_y0) - total_h) // 2)

    for idx, label in enumerate(labels):
        row = idx // cols
        col = idx % cols
        row_items = min(cols, n - row * cols)
        row_w = row_items * card_w + max(0, row_items - 1) * 20
        start_x = zone_x0 + (zone_w - row_w) // 2
        x0 = start_x + col * (card_w + 20)
        y0 = start_y + row * (card_h + 16)
        x1 = x0 + card_w
        y1 = y0 + card_h

        canvas.fill_rect(x0, y0, x1, y1, LABEL_BG)
        canvas.stroke_rect(x0, y0, x1, y1, LABEL_BORDER, thickness=2)
        lines = _wrap_text(label, card_w - 20, scale=2, max_lines=2, text_backend=backend)
        th = len(lines) * glyph_h2 + max(0, len(lines) - 1) * gap2 if lines else 0
        ty = y0 + max(6, (card_h - th) // 2)
        for line in lines:
            tw = backend.measure_width(line, scale=2)
            tx = x0 + max(8, (card_w - tw) // 2)
            canvas.draw_text(tx, ty, line, TEXT_PRIMARY, scale=2)
            ty += line_h2


def _draw_screenshots(
    canvas: Canvas,
    screenshots: tuple[ScreenshotSpec, ...],
    zone_x0: int,
    zone_y0: int,
    zone_x1: int,
    zone_y1: int,
    image_cache: dict[Path, tuple[int, int, bytes]],
) -> None:
    backend = canvas.text_backend
    n = len(screenshots)
    cols = 1 if n == 1 else 2
    rows = math.ceil(n / cols)
    slot_w = max(80, (zone_x1 - zone_x0 - (cols + 1) * 16) // cols)
    slot_h = max(80, (zone_y1 - zone_y0 - (rows + 1) * 16) // rows)

    for idx, shot in enumerate(screenshots):
        col = idx % cols
        row = idx // cols
        sx0 = zone_x0 + 16 + col * (slot_w + 16)
        sy0 = zone_y0 + 16 + row * (slot_h + 16)

        if shot.path not in image_cache:
            image_cache[shot.path] = decode_png_rgba(shot.path)
        iw, ih, rgba = image_cache[shot.path]

        cap_reserve = 28 if shot.caption else 0
        avail_w = max(32, slot_w - 8)
        avail_h = max(32, slot_h - 8 - cap_reserve)
        scale = min(avail_w / iw, avail_h / ih)
        draw_w = max(1, int(iw * scale))
        draw_h = max(1, int(ih * scale))
        dx = sx0 + (slot_w - draw_w) // 2
        dy = sy0 + (avail_h - draw_h) // 2

        canvas.blit_rgba_scaled(iw, ih, rgba, dx, dy, draw_w, draw_h)
        canvas.stroke_rect(dx - 2, dy - 2, dx + draw_w + 2, dy + draw_h + 2, FRAME_BORDER, thickness=2)

        if shot.caption:
            cap_lines = _wrap_text(shot.caption, slot_w - 8, scale=2, max_lines=1, text_backend=backend)
            if cap_lines:
                tw = backend.measure_width(cap_lines[0], scale=2)
                canvas.draw_text(sx0 + max(0, (slot_w - tw) // 2), dy + draw_h + 8, cap_lines[0], TEXT_MUTED, scale=2)


def layout_subtitle(
    subtitle: str,
    width: int,
    strip_height: int,
    text_backend: TextBackend | None = None,
) -> tuple[int, list[str]]:
    backend = text_backend if text_backend is not None else resolve_text_backend()
    pad_x = 32
    avail_w = max(64, width - 2 * pad_x)
    avail_h = max(20, strip_height - 14)

    lines_3 = _wrap_text(subtitle, avail_w, scale=3, max_lines=10, text_backend=backend)
    h3 = backend.glyph_height(3)
    gap3 = backend.line_gap(3)
    if len(lines_3) <= 2 and (len(lines_3) * h3 + max(0, len(lines_3) - 1) * gap3) <= avail_h:
        return 3, lines_3

    h2 = backend.glyph_height(2)
    gap2 = backend.line_gap(2)
    line_step_2 = h2 + gap2
    max_lines_2 = max(1, (avail_h + gap2) // line_step_2)
    lines_2 = _wrap_text(subtitle, avail_w, scale=2, max_lines=max_lines_2, text_backend=backend)
    return 2, lines_2


def render_slide_canvas(
    spec: RenderSpec,
    slide: SlideSpec,
    image_cache: dict[Path, tuple[int, int, bytes]],
    text_backend: TextBackend | None = None,
) -> tuple[Canvas, tuple[str, ...]]:
    backend = text_backend if text_backend is not None else resolve_text_backend()
    canvas = Canvas(spec.width, spec.height, BG_SLIDE, text_backend=backend)
    strip_y = spec.height - spec.strip_height

    canvas.set_clip(0, 0, spec.width, strip_y)
    content_y0 = 24
    if slide.title:
        title_lines = _wrap_text(slide.title, spec.width - 72, scale=3, max_lines=1, text_backend=backend)
        if title_lines:
            canvas.draw_text(36, content_y0, title_lines[0], TEXT_PRIMARY, scale=3)
            content_y0 += max(36, backend.glyph_height(3) + 12)
            canvas.fill_rect(36, content_y0, spec.width - 36, content_y0 + 2, STRIP_DIVIDER)
            content_y0 += 14

    content_y1 = strip_y - 16
    content_x0 = 32
    content_x1 = spec.width - 32

    has_nodes = bool(slide.nodes)
    has_labels = bool(slide.labels)
    has_shots = bool(slide.screenshots)

    diag_x1 = content_x1
    if has_shots and (has_nodes or has_labels):
        split_x = content_x0 + int((content_x1 - content_x0) * 0.56)
        diag_x1 = split_x - 12
        _draw_screenshots(canvas, slide.screenshots, split_x + 12, content_y0, content_x1, content_y1, image_cache)
    elif has_shots:
        _draw_screenshots(canvas, slide.screenshots, content_x0, content_y0, content_x1, content_y1, image_cache)

    if has_nodes and has_labels:
        label_h = min(96, max(56, (content_y1 - content_y0) // 4))
        _draw_labels_row(canvas, slide.labels, content_x0, content_y0, diag_x1, content_y0 + label_h)
        _draw_node_diagram(canvas, slide.nodes, slide.edges, content_x0, content_y0 + label_h + 12, diag_x1, content_y1)
    elif has_nodes:
        _draw_node_diagram(canvas, slide.nodes, slide.edges, content_x0, content_y0, diag_x1, content_y1)
    elif has_labels:
        _draw_labels_row(canvas, slide.labels, content_x0, content_y0, diag_x1, content_y1)

    canvas.set_clip(0, strip_y, spec.width, spec.height)
    canvas.fill_rect(0, strip_y, spec.width, strip_y + 2, STRIP_DIVIDER)
    canvas.fill_rect(0, strip_y + 2, spec.width, spec.height, BG_STRIP)

    sub_scale, sub_lines = layout_subtitle(slide.subtitle, spec.width, spec.strip_height, text_backend=backend)
    if sub_lines:
        glyph_h = backend.glyph_height(sub_scale)
        gap_y = backend.line_gap(sub_scale)
        line_step = glyph_h + gap_y
        total_h = len(sub_lines) * glyph_h + max(0, len(sub_lines) - 1) * gap_y
        strip_inner_y = strip_y + 2
        strip_inner_h = spec.strip_height - 2
        ty = strip_inner_y + max(4, (strip_inner_h - total_h) // 2)
        for line in sub_lines:
            tw = backend.measure_width(line, sub_scale)
            tx = max(32, (spec.width - tw) // 2)
            canvas.draw_text(tx, ty, line, TEXT_SUBTITLE, scale=sub_scale)
            ty += line_step

    return canvas, tuple(sub_lines)


def _encode_mp4(
    ffmpeg_path: str,
    spec: RenderSpec,
    slide_paths: list[Path],
    timings: list[SlideTiming],
    out_path: Path,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = len(slide_paths)
    cmd: list[str] = [ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error"]
    for idx, slide_path in enumerate(slide_paths):
        cmd.extend(["-loop", "1", "-framerate", str(spec.fps), "-t", f"{timings[idx].input_duration:.6f}", "-i", str(slide_path)])

    if n == 1:
        cmd.extend(["-vf", f"fps={spec.fps},format=yuv420p"])
    else:
        trans = spec.transition_seconds
        filter_parts = [f"[{i}:v]fps={spec.fps},settb=1/{spec.fps},format=yuv420p[v{i}]" for i in range(n)]
        prev_label = "v0"
        cumulative_hold = timings[0].hold_seconds
        for k in range(n - 1):
            offset = round(cumulative_hold + k * trans, 6)
            out_label = "outv" if k == n - 2 else f"xf{k + 1}"
            filter_parts.append(
                f"[{prev_label}][v{k + 1}]xfade=transition=fade:duration={trans:.6f}:offset={offset:.6f}[{out_label}]"
            )
            prev_label = out_label
            cumulative_hold += timings[k + 1].hold_seconds
        cmd.extend(["-filter_complex", ";".join(filter_parts), "-map", "[outv]"])

    cmd.extend([
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-an",
        str(out_path),
    ])

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise KetchupRenderError(f"ffmpeg encode failed: {proc.stderr.strip() or proc.returncode}")


def _build_contact_sheet(
    ffmpeg_path: str,
    spec: RenderSpec,
    timings: list[SlideTiming],
    mp4_path: Path,
    sheet_path: Path,
) -> None:
    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    n = len(timings)
    cmd: list[str] = [ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error"]
    for timing in timings:
        midpoint = round((timing.steady_start + timing.steady_end) / 2.0, 4)
        cmd.extend(["-ss", f"{midpoint:.4f}", "-i", str(mp4_path)])

    if n == 1:
        tile_w, tile_h = spec.width, spec.height
        filter_complex = f"[0:v]trim=end_frame=1,setpts=PTS-STARTPTS,scale={tile_w}:{tile_h}[sheet]"
    else:
        cols = 2
        rows = math.ceil(n / cols)
        tile_w = 800
        tile_h = max(120, int(round(tile_w * spec.height / spec.width)))
        if tile_h % 2 != 0:
            tile_h += 1
        scales = [f"[{i}:v]trim=end_frame=1,setpts=PTS-STARTPTS,scale={tile_w}:{tile_h}[s{i}]" for i in range(n)]
        concat_inputs = "".join(f"[s{i}]" for i in range(n))
        scales.append(f"{concat_inputs}concat=n={n}:v=1:a=0,tile={cols}x{rows}:padding=8:color=0x090d16[sheet]")
        filter_complex = ";".join(scales)

    cmd.extend(["-filter_complex", filter_complex, "-map", "[sheet]", "-frames:v", "1", "-c:v", "png", str(sheet_path)])
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise KetchupRenderError(f"contact sheet generation failed: {proc.stderr.strip() or proc.returncode}")


def render_from_spec(spec_path: Path, out_path: Path, contact_sheet_path: Path | None) -> dict[str, Any]:
    env = check_environment()
    if not env.ok or not env.ffmpeg:
        raise KetchupRenderError(env.error or "ffmpeg environment check failed")

    try:
        raw_spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KetchupRenderError(f"failed to read spec {spec_path}: {exc}") from exc

    spec = parse_spec(raw_spec, spec_path.parent)
    timings, total_duration = compute_timings(spec)
    image_cache: dict[Path, tuple[int, int, bytes]] = {}
    text_backend = resolve_text_backend()

    with tempfile.TemporaryDirectory(prefix="ketchup-render-") as tmp_dir:
        tmp = Path(tmp_dir)
        slide_paths: list[Path] = []
        updated_timings: list[SlideTiming] = []
        for idx, slide in enumerate(spec.slides):
            canvas, sub_lines = render_slide_canvas(spec, slide, image_cache, text_backend=text_backend)
            slide_png = tmp / f"slide_{idx:03d}.png"
            slide_png.write_bytes(canvas.to_png_bytes(compress_level=1))
            slide_paths.append(slide_png)
            t = timings[idx]
            updated_timings.append(
                SlideTiming(
                    index=t.index,
                    added_words=t.added_words,
                    hold_seconds=t.hold_seconds,
                    steady_start=t.steady_start,
                    steady_end=t.steady_end,
                    input_duration=t.input_duration,
                    subtitle_lines=sub_lines,
                )
            )

        _encode_mp4(env.ffmpeg, spec, slide_paths, updated_timings, out_path)
        if contact_sheet_path is not None:
            _build_contact_sheet(env.ffmpeg, spec, updated_timings, out_path, contact_sheet_path)

    return {
        "ok": True,
        "out": str(out_path),
        "contact_sheet": str(contact_sheet_path) if contact_sheet_path is not None else None,
        "text_backend": text_backend.name,
        "font_path": text_backend.font_path,
        "total_duration": total_duration,
        "slides": [
            {
                "index": t.index,
                "added_words": t.added_words,
                "hold_seconds": t.hold_seconds,
                "steady_start": t.steady_start,
                "steady_end": t.steady_end,
                "subtitle_lines": list(t.subtitle_lines),
            }
            for t in updated_timings
        ],
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deterministic pure-Python + ffmpeg ketchup slide video renderer.")
    parser.add_argument("--check-env", action="store_true", help="Probe ffmpeg/ffprobe/encoder availability and exit.")
    parser.add_argument("--spec", type=Path, help="Path to slides.json spec file.")
    parser.add_argument("--out", type=Path, help="Output MP4 path.")
    parser.add_argument("--contact-sheet", type=Path, help="Output contact-sheet PNG path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if args.check_env:
        status = check_environment()
        print(json.dumps(status.to_dict(), indent=2))
        return 0 if status.ok else 1

    if not args.spec or not args.out:
        print(json.dumps({"ok": False, "error": "both --spec and --out are required unless --check-env is set"}))
        return 1

    try:
        summary = render_from_spec(args.spec, args.out, args.contact_sheet)
    except KetchupRenderError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
