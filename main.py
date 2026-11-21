#!/usr/bin/env python3
"""WORLD IN A DAY - the news of Saturday 21 November 2026 on one screen.

The program draws a dark "news dashboard" poster, 1024 x 1024, that sums up
the day's world news: a lead panel on the NATO / Poland airspace crisis, two
side panels (Iran, Riyadh), six story tiles (Ukraine funding, COP31, the AI
market sell-off, the Riemann hypothesis claim, the killer-robots talks and
the Peru earthquake) and a wire strip of four shorter items.

Pure Python standard library: the picture is rasterised by the small stroke
renderer below (own framebuffer, own stroke typeface, own PNG writer) and
written to $MAKEFUN_OUTPUT_DIR/entry.png (or /output/entry.png).  The output
is a pure function of the constants in this file, so two runs write the same
bytes.
"""

import math
import os
import struct
import zlib

WIDTH = 1024
HEIGHT = 1024

# ---------------------------------------------------------------- PNG sink

def encode_png(pixels, width, height):
    """pixels: bytearray of RGB triplets, row major. Returns PNG bytes."""
    stride = width * 3
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0 (None) for every row
        raw += pixels[y * stride:(y + 1) * stride]

    def chunk(tag, payload):
        body = tag + payload
        return (struct.pack(">I", len(payload)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


# ------------------------------------------------------------ frame buffer

class Canvas:
    def __init__(self, width, height, top, bottom):
        self.w = width
        self.h = height
        self.px = bytearray(width * height * 3)
        # vertical gradient background, one colour per row
        for y in range(height):
            t = y / (height - 1)
            r = round(top[0] + (bottom[0] - top[0]) * t)
            g = round(top[1] + (bottom[1] - top[1]) * t)
            b = round(top[2] + (bottom[2] - top[2]) * t)
            row = bytes((r, g, b)) * width
            self.px[y * width * 3:(y + 1) * width * 3] = row

    def set(self, x, y, color):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.px[i] = color[0]
            self.px[i + 1] = color[1]
            self.px[i + 2] = color[2]

    def rect(self, x, y, w, h, color):
        x0, x1 = max(0, x), min(self.w, x + w)
        y0, y1 = max(0, y), min(self.h, y + h)
        if x0 >= x1 or y0 >= y1:
            return
        row = bytes(color) * (x1 - x0)
        for yy in range(y0, y1):
            i = (yy * self.w + x0) * 3
            self.px[i:i + len(row)] = row

    def frame(self, x, y, w, h, color, t=1):
        self.rect(x, y, w, t, color)
        self.rect(x, y + h - t, w, t, color)
        self.rect(x, y, t, h, color)
        self.rect(x + w - t, y, t, h, color)

    def line(self, x1, y1, x2, y2, color, t=1):
        # thick Bresenham: stamp a t-by-t brush along the segment
        x1, y1, x2, y2 = round(x1), round(y1), round(x2), round(y2)
        dx, dy = abs(x2 - x1), abs(y2 - y1)
        steps = max(dx, dy, 1)
        r = t // 2
        for s in range(steps + 1):
            cx = x1 + (x2 - x1) * s / steps
            cy = y1 + (y2 - y1) * s / steps
            self.rect(round(cx) - r, round(cy) - r, t, t, color)

    def dashed_line(self, x1, y1, x2, y2, color, t=1, dash=9, gap=7):
        x1, y1, x2, y2 = float(x1), float(y1), float(x2), float(y2)
        length = max(abs(x2 - x1), abs(y2 - y1), 1)
        pos = 0.0
        while pos < length:
            end = min(pos + dash, length)
            ax = x1 + (x2 - x1) * pos / length
            ay = y1 + (y2 - y1) * pos / length
            bx = x1 + (x2 - x1) * end / length
            by = y1 + (y2 - y1) * end / length
            self.line(ax, ay, bx, by, color, t)
            pos = end + gap

    def circle(self, cx, cy, rad, color, t=1, fill=False):
        if fill:
            for yy in range(cy - rad, cy + rad + 1):
                span = int((rad * rad - (yy - cy) ** 2) ** 0.5)
                self.rect(cx - span, yy, span * 2 + 1, 1, color)
            return
        steps = max(24, rad * 6)
        for s in range(steps + 1):
            a = 2 * math.pi * s / steps
            self.rect(round(cx + rad * math.cos(a)) - t // 2,
                      round(cy + rad * math.sin(a)) - t // 2, t, t, color)

    def bezier(self, p0, p1, p2, color, t=1, steps=48):
        prev = None
        for s in range(steps + 1):
            u = s / steps
            x = (1 - u) ** 2 * p0[0] + 2 * (1 - u) * u * p1[0] + u ** 2 * p2[0]
            y = (1 - u) ** 2 * p0[1] + 2 * (1 - u) * u * p1[1] + u ** 2 * p2[1]
            if prev is not None:
                self.line(prev[0], prev[1], x, y, color, t)
            prev = (x, y)

    def polygon(self, points, color):
        # scanline fill of a simple polygon
        ys = [p[1] for p in points]
        for yy in range(int(min(ys)), int(max(ys)) + 1):
            nodes = []
            n = len(points)
            for i in range(n):
                x1, y1 = points[i]
                x2, y2 = points[(i + 1) % n]
                if (y1 <= yy < y2) or (y2 <= yy < y1):
                    nodes.append(x1 + (yy - y1) * (x2 - x1) / (y2 - y1))
            nodes.sort()
            for i in range(0, len(nodes) - 1, 2):
                self.rect(round(nodes[i]), yy,
                          max(1, round(nodes[i + 1]) - round(nodes[i])), 1, color)

    def polyline(self, points, color, t=1, close=False):
        for i in range(len(points) - 1):
            self.line(points[i][0], points[i][1],
                      points[i + 1][0], points[i + 1][1], color, t)
        if close and len(points) > 2:
            self.line(points[-1][0], points[-1][1],
                      points[0][0], points[0][1], color, t)


# ---------------------------------------------------------- stroke typeface
# Each glyph is drawn with straight strokes on a 4-wide, 6-tall grid
# (y grows downward, 0 is the cap line, 6 the baseline; a few tails reach 7).
# A spec is "x1,y1 x2,y2;x1,y1 x2,y2;..." - one item per stroke.

GLYPH_SPEC = {
    "A": "0,6 2,0;2,0 4,6;1,3 3,3",
    "B": "0,0 0,6;0,0 3,0;3,0 4,1;4,1 3,3;0,3 3,3;3,3 4,4;4,4 3,6;0,6 3,6",
    "C": "4,1 3,0;3,0 1,0;1,0 0,2;0,2 0,4;0,4 1,6;1,6 3,6;3,6 4,5",
    "D": "0,0 0,6;0,0 2,0;2,0 4,2;4,2 4,4;4,4 2,6;2,6 0,6",
    "E": "4,0 0,0;0,0 0,6;0,6 4,6;0,3 3,3",
    "F": "4,0 0,0;0,0 0,6;0,3 3,3",
    "G": "4,1 3,0;3,0 1,0;1,0 0,2;0,2 0,4;0,4 1,6;1,6 3,6;3,6 4,4;4,4 2,4",
    "H": "0,0 0,6;4,0 4,6;0,3 4,3",
    "I": "2,0 2,6;0,0 4,0;0,6 4,6",
    "J": "4,0 4,5;4,5 3,6;3,6 1,6;1,6 0,5",
    "K": "0,0 0,6;4,0 0,3;0,3 4,6",
    "L": "0,0 0,6;0,6 4,6",
    "M": "0,6 0,0;0,0 2,3;2,3 4,0;4,0 4,6",
    "N": "0,6 0,0;0,0 4,6;4,6 4,0",
    "O": "1,0 3,0;3,0 4,1;4,1 4,5;4,5 3,6;3,6 1,6;1,6 0,5;0,5 0,1;0,1 1,0",
    "P": "0,6 0,0;0,0 3,0;3,0 4,1;4,1 3,3;3,3 0,3",
    "Q": "1,0 3,0;3,0 4,1;4,1 4,5;4,5 3,6;3,6 1,6;1,6 0,5;0,5 0,1;0,1 1,0;2,4 4,6",
    "R": "0,6 0,0;0,0 3,0;3,0 4,1;4,1 3,3;3,3 0,3;2,3 4,6",
    "S": "4,1 3,0;3,0 1,0;1,0 0,1;0,1 0,2;0,2 1,3;1,3 3,3;3,3 4,4;4,4 4,5;4,5 3,6;3,6 1,6;1,6 0,5",
    "T": "0,0 4,0;2,0 2,6",
    "U": "0,0 0,5;0,5 1,6;1,6 3,6;3,6 4,5;4,5 4,0",
    "V": "0,0 2,6;2,6 4,0",
    "W": "0,0 1,6;1,6 2,2;2,2 3,6;3,6 4,0",
    "X": "0,0 4,6;4,0 0,6",
    "Y": "0,0 2,3;4,0 2,3;2,3 2,6",
    "Z": "0,0 4,0;4,0 0,6;0,6 4,6",
    "0": "1,0 3,0;3,0 4,1;4,1 4,5;4,5 3,6;3,6 1,6;1,6 0,5;0,5 0,1;0,1 1,0",
    "1": "1,1 2,0;2,0 2,6;0,6 4,6",
    "2": "0,1 1,0;1,0 3,0;3,0 4,1;4,1 0,6;0,6 4,6",
    "3": "0,1 1,0;1,0 3,0;3,0 4,1;4,1 3,3;0,3 3,3;3,3 4,4;4,4 3,6;3,6 1,6;1,6 0,5",
    "4": "3,6 3,0;3,0 0,4;0,4 4,4",
    "5": "4,0 0,0;0,0 0,3;0,3 3,3;3,3 4,4;4,4 3,6;3,6 1,6;1,6 0,5",
    "6": "3,0 1,1;1,1 0,3;0,3 0,5;0,5 1,6;1,6 3,6;3,6 4,5;4,5 3,3;3,3 0,3",
    "7": "0,0 4,0;4,0 1,6",
    "8": "1,0 3,0;3,0 4,1;4,1 3,3;3,3 1,3;1,3 0,1;0,1 1,0;1,3 0,4;0,4 1,6;1,6 3,6;3,6 4,4;4,4 3,3",
    "9": "0,5 1,6;1,6 3,5;3,5 4,3;4,3 4,1;4,1 3,0;3,0 1,0;1,0 0,1;0,1 1,3;1,3 4,3",
    ".": "2,6 2,6",
    ",": "2,5 1,7",
    "'": "2,0 1,2",
    ":": "2,1 2,1;2,5 2,5",
    ";": "2,1 2,1;2,5 1,7",
    "!": "2,0 2,4;2,6 2,6",
    "?": "0,1 1,0;1,0 3,0;3,0 4,1;4,1 2,3;2,3 2,4;2,6 2,6",
    "-": "1,3 3,3",
    "\u2013": "0,3 4,3",
    "\u2014": "0,3 4,3",
    "/": "0,6 4,0",
    "(": "3,0 1,2;1,2 1,4;1,4 3,6",
    ")": "1,0 3,2;3,2 3,4;3,4 1,6",
    "+": "2,2 2,4;1,3 3,3",
    "%": "4,0 0,6;0,0 1,0;1,0 0,1;0,1 0,0;3,5 4,5;4,5 3,6;3,6 3,5",
    '"': "1,0 1,2;3,0 3,2",
    "*": "2,1 2,5;0,2 4,4;4,2 0,4",
    "=": "0,2 4,2;0,4 4,4",
    "\u00b7": "2,3 2,3",
    "\u2022": "2,3 2,3",
}


def _parse_glyphs():
    glyphs = {}
    for ch, spec in GLYPH_SPEC.items():
        strokes = []
        for part in spec.split(";"):
            a, b = part.split()
            x1, y1 = (float(v) for v in a.split(","))
            x2, y2 = (float(v) for v in b.split(","))
            strokes.append((x1, y1, x2, y2))
        glyphs[ch] = strokes
    return glyphs


GLYPHS = _parse_glyphs()

ADVANCE = 5.2          # grid units per character cell
NARROW = ".,':;!\"·•"
NARROW_ADVANCE = 2.8


def char_advance(ch, scale):
    if ch == " ":
        return 3.2 * scale
    if ch in NARROW:
        return NARROW_ADVANCE * scale
    return ADVANCE * scale


def text_width(text, scale):
    return sum(char_advance(ch, scale) for ch in text.upper()) - 1.2 * scale


def draw_text(cv, x, y, text, scale, color, weight=1):
    """Draw text with its cap line at y; returns the x just past the text."""
    cx = float(x)
    for ch in text.upper():
        strokes = GLYPHS.get(ch)
        if strokes:
            for (x1, y1, x2, y2) in strokes:
                cv.line(cx + x1 * scale, y + y1 * scale,
                        cx + x2 * scale, y + y2 * scale, color, weight)
        cx += char_advance(ch, scale)
    return cx


def wrap_text(text, scale, max_width):
    words = text.split()
    lines = []
    current = ""
    for word in words:
        trial = word if not current else current + " " + word
        if text_width(trial, scale) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_paragraph(cv, x, y, text, scale, color, max_width, leading, weight=1):
    lines = wrap_text(text, scale, max_width)
    for i, line in enumerate(lines):
        draw_text(cv, x, y + i * leading, line, scale, color, weight)
    return y + len(lines) * leading


# ------------------------------------------------------------------ palette

INK = (238, 242, 248)      # primary text
SOFT = (170, 184, 210)     # secondary text
FAINT = (105, 123, 159)    # muted text
PANEL = (19, 29, 52)       # card fill
PANEL_EDGE = (44, 62, 102)  # card border
BAND = (9, 14, 26)         # wire strip fill
RED = (232, 84, 88)
AMBER = (242, 169, 55)
CYAN = (66, 199, 224)
GREEN = (94, 203, 140)
VIOLET = (158, 132, 228)
ROSE = (240, 120, 160)


# -------------------------------------------------------------- ui helpers

def panel(cv, x, y, w, h, accent):
    cv.rect(x, y, w, h, PANEL)
    cv.frame(x, y, w, h, PANEL_EDGE, 1)
    cv.rect(x, y, w, 4, accent)


def kicker(cv, x, y, text, color):
    cv.rect(x, y + 3, 8, 8, color)
    draw_text(cv, x + 16, y, text, 1.6, color, 2)


def chip(cv, x, y, text, color):
    w = round(text_width(text, 1.45)) + 22
    cv.frame(x, y, w, 30, color, 1)
    draw_text(cv, x + 11, y + 8, text, 1.45, color, 2)
    return x + w


def star(cv, cx, cy, r, color):
    pts = []
    for i in range(10):
        rad = r if i % 2 == 0 else r * 0.45
        a = -math.pi / 2 + i * math.pi / 5
        pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
    cv.polygon(pts, color)


def burst(cv, cx, cy, color):
    for i in range(8):
        a = i * math.pi / 4
        cv.line(cx, cy, cx + 11 * math.cos(a), cy + 11 * math.sin(a), color, 2)


# ------------------------------------------------------------------- icons
# Each icon draws inside a 40x40 box whose top-left corner is (x, y).

def icon_coin(cv, x, y, color):
    cv.circle(x + 20, y + 20, 15, color, 3)
    cv.circle(x + 20, y + 20, 8, color, 2)


def icon_leaf(cv, x, y, color):
    cv.bezier((x + 8, y + 32), (x + 4, y + 10), (x + 24, y + 4), color, 3)
    cv.bezier((x + 24, y + 4), (x + 38, y + 12), (x + 30, y + 30), color, 3)
    cv.line(x + 8, y + 32, x + 30, y + 30, color, 3)
    cv.line(x + 10, y + 30, x + 26, y + 12, color, 2)


def icon_chart_down(cv, x, y, color):
    pts = [(x + 4, y + 8), (x + 14, y + 16), (x + 20, y + 12),
           (x + 30, y + 26), (x + 36, y + 30)]
    cv.polyline(pts, color, 3)
    cv.line(x + 36, y + 30, x + 26, y + 30, color, 3)
    cv.line(x + 36, y + 30, x + 36, y + 20, color, 3)


def icon_proof(cv, x, y, color):
    cv.bezier((x + 4, y + 26), (x + 12, y + 6), (x + 20, y + 34), color, 3)
    cv.bezier((x + 20, y + 34), (x + 26, y + 12), (x + 30, y + 14), color, 3)
    cv.line(x + 24, y + 28, x + 30, y + 34, color, 3)
    cv.line(x + 30, y + 34, x + 38, y + 22, color, 3)


def icon_robot(cv, x, y, color):
    cv.frame(x + 6, y + 12, 28, 22, color, 3)
    cv.line(x + 20, y + 12, x + 20, y + 5, color, 3)
    cv.circle(x + 20, y + 4, 3, color, 2, fill=True)
    cv.circle(x + 14, y + 21, 2, color, 2, fill=True)
    cv.circle(x + 26, y + 21, 2, color, 2, fill=True)
    cv.line(x + 13, y + 29, x + 27, y + 29, color, 2)


def icon_peaks(cv, x, y, color):
    cv.polyline([(x + 2, y + 28), (x + 14, y + 10), (x + 22, y + 20),
                 (x + 28, y + 12), (x + 38, y + 28)], color, 3)
    cv.polyline([(x + 6, y + 36), (x + 12, y + 32), (x + 18, y + 36),
                 (x + 24, y + 32), (x + 30, y + 36)], color, 2)


def icon_missile(cv, x, y, color):
    cv.line(x + 10, y + 30, x + 28, y + 12, color, 4)
    cv.line(x + 28, y + 12, x + 33, y + 7, color, 3)
    cv.line(x + 10, y + 30, x + 6, y + 22, color, 3)
    cv.line(x + 10, y + 30, x + 18, y + 34, color, 3)
    cv.dashed_line(x + 8, y + 34, x + 2, y + 40, color, 2, 4, 4)


def icon_shield(cv, x, y, color):
    pts = [(x + 20, y + 3), (x + 35, y + 8), (x + 35, y + 20),
           (x + 20, y + 37), (x + 5, y + 20), (x + 5, y + 8)]
    cv.polyline(pts, color, 3, close=True)
    cv.line(x + 12, y + 20, x + 18, y + 26, color, 3)
    cv.line(x + 18, y + 26, x + 29, y + 13, color, 3)


# ------------------------------------------------------------- lead picture

def lead_scene(cv):
    """Missile arcs cross a dashed border; a shield with a star holds."""
    # the border, dashed, and the ground it stands on
    cv.dashed_line(520, 396, 520, 498, FAINT, 2, 10, 8)
    cv.line(404, 500, 614, 500, PANEL_EDGE, 2)
    draw_text(cv, 528, 512, "POLAND", 1.5, FAINT, 2)
    draw_text(cv, 424, 512, "RUSSIA", 1.5, FAINT, 2)
    # three incoming arcs, west to east
    cv.bezier((408, 492), (430, 372), (508, 404), RED, 3)
    cv.bezier((420, 496), (462, 392), (534, 430), AMBER, 3)
    cv.bezier((400, 486), (486, 356), (556, 402), RED, 3)
    burst(cv, 508, 404, AMBER)
    burst(cv, 534, 430, RED)
    burst(cv, 556, 402, AMBER)
    # the shield that answers them
    shield = [(574, 420), (605, 432), (605, 466), (574, 497), (543, 466),
              (543, 432)]
    cv.polyline(shield, CYAN, 3, close=True)
    star(cv, 574, 459, 15, AMBER)


# ------------------------------------------------------------------- build

def build():
    cv = Canvas(WIDTH, HEIGHT, (11, 18, 33), (13, 22, 42))

    # masthead ------------------------------------------------------------
    cv.rect(28, 40, 12, 12, RED)
    draw_text(cv, 52, 30, "WORLD IN A DAY", 5.6, INK, 4)
    draw_text(cv, 28, 84, "THE WHOLE PLANET, SUMMED UP IN A SINGLE FRAME",
              1.6, SOFT, 2)
    sat = "SATURDAY"
    draw_text(cv, 996 - text_width(sat, 3.0), 30, sat, 3.0, AMBER, 3)
    date = "21 NOVEMBER 2026"
    draw_text(cv, 996 - text_width(date, 3.0), 58, date, 3.0, INK, 3)
    cv.line(28, 116, 996, 116, PANEL_EDGE, 2)

    # lead panel ----------------------------------------------------------
    panel(cv, 28, 132, 608, 434, RED)
    kicker(cv, 52, 152, "EUROPE - NATO / WARSAW", RED)
    draw_text(cv, 52, 182, "MISSILES OVER", 5.0, INK, 4)
    draw_text(cv, 52, 228, "THE BORDER", 5.0, INK, 4)
    draw_paragraph(cv, 52, 292,
                   "Russian missiles and a drone crossed into Poland on "
                   "Friday. In Warsaw, NATO chief Mark Rutte promised the "
                   "alliance will defend every inch of Polish territory.",
                   1.95, SOFT, 336, 25, 1)
    lead_scene(cv)
    nxt = chip(cv, 52, 512, "3 OBJECTS CROSSED", AMBER)
    chip(cv, nxt + 12, 512, "NATO COUNCIL MEETS MONDAY", CYAN)

    # right rail ----------------------------------------------------------
    panel(cv, 652, 132, 344, 212, AMBER)
    kicker(cv, 672, 152, "MIDDLE EAST - IRAN", AMBER)
    icon_missile(cv, 938, 146, AMBER)
    draw_text(cv, 672, 184, "IRAN BIDS FOR TALKS;", 2.5, INK, 3)
    draw_text(cv, 672, 218, "TRUMP SAYS NO DEAL", 2.5, INK, 3)
    draw_paragraph(cv, 672, 258,
                   "Tehran urges diplomacy to end the war. Trump calls its "
                   "terms unacceptable and weighs new strikes as Israel "
                   "presses for action.",
                   1.65, SOFT, 304, 21, 1)

    panel(cv, 652, 360, 344, 206, CYAN)
    kicker(cv, 672, 380, "SAUDI ARABIA - RIYADH", CYAN)
    icon_shield(cv, 938, 374, CYAN)
    draw_text(cv, 672, 412, "MISSILES OVER RIYADH", 2.5, INK, 3)
    draw_text(cv, 672, 446, "ALL THREE DOWNED", 2.5, INK, 3)
    draw_paragraph(cv, 672, 486,
                   "Houthi forces fire on the Saudi capital after a "
                   "coalition operation; air defences intercept three "
                   "ballistic missiles.",
                   1.65, SOFT, 304, 21, 1)

    # story tiles ---------------------------------------------------------
    tiles = [
        ("KYIV - WASHINGTON", CYAN, icon_coin,
         "TRUMP TO EUROPE:", "SPEND IT AT HOME",
         "Zelenskiy says Trump told Europe its Ukraine billions could "
         "be spent at home if a peace deal is reached."),
        ("CLIMATE - ANTALYA", GREEN, icon_leaf,
         "TALKS ON THE BRINK", "",
         "COP31 runs deep into overtime over fossil fuels. EU climate "
         "chief: a good deal, or no deal."),
        ("MARKETS - AI TRADE", AMBER, icon_chart_down,
         "REALITY CHECK", "FOR THE AI TRADE",
         "Wall Street's worst week in 18 months as tech sells off; "
         "Anthropic stumbles days after its record debut."),
        ("SCIENCE - MATHEMATICS", VIOLET, icon_proof,
         "THE RIDDLE", "OF 1859",
         "Alpoge says he and Claude proved the Riemann hypothesis. "
         "A claim only - experts are checking."),
        ("GENEVA - ARMS TALKS", ROSE, icon_robot,
         "FIRST RULES FOR", "KILLER ROBOTS",
         "UN talks open the path to a pact on autonomous weapons, "
         "pledging draft rules by 2028."),
        ("PERU - THE ANDES", CYAN, icon_peaks,
         "6.8 QUAKE SHAKES", "THE ANDES",
         "A magnitude 6.8 quake near Junin sends Lima residents into "
         "the streets. No casualties reported."),
    ]
    for i, (kick, color, icon, h1, h2, body) in enumerate(tiles):
        tx = 28 + (i % 3) * 328
        ty = 582 + (i // 3) * 168
        panel(cv, tx, ty, 312, 152, color)
        kicker(cv, tx + 16, ty + 14, kick, color)
        icon(cv, tx + 258, ty + 8, color)
        draw_text(cv, tx + 16, ty + 44, h1, 2.25, INK, 3)
        lines = 1
        if h2:
            draw_text(cv, tx + 16, ty + 74, h2, 2.25, INK, 3)
            lines = 2
        draw_paragraph(cv, tx + 16, ty + 52 + lines * 30, body,
                       1.5, SOFT, 280, 19, 1)

    # wire strip ----------------------------------------------------------
    cv.rect(28, 918, 968, 40, BAND)
    cv.frame(28, 918, 968, 40, PANEL_EDGE, 1)
    cv.rect(40, 928, 56, 20, RED)
    draw_text(cv, 48, 931, "WIRE", 1.5, INK, 2)
    items = ["MEXICO NABS 'EL CHAPO ISIDRO'",
             "GAZA AID VEHICLE HIT - 3 DEAD",
             "DENMARK EXPELS RUSSIAN DIPLOMAT",
             "FRANCE MARCHES EASE"]
    wx = 116.0
    for j, item in enumerate(items):
        if j:
            cv.polygon([(wx - 14, 938), (wx - 9, 933), (wx - 4, 938),
                        (wx - 9, 943)], AMBER)
        draw_text(cv, wx, 930, item, 1.45, SOFT, 2)
        wx += text_width(item, 1.45) + 30

    # footer --------------------------------------------------------------
    draw_text(cv, 28, 976, "SATURDAY 21 NOVEMBER 2026 - ONE DAY, ONE IMAGE",
              1.5, FAINT, 2)
    credit = "FROM THE DAY'S WIRE REPORTS"
    draw_text(cv, 996 - text_width(credit, 1.5), 976, credit, 1.5, FAINT, 2)

    return encode_png(cv.px, WIDTH, HEIGHT)


def main():
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    data = build()
    path = os.path.join(out_dir, "entry.png")
    with open(path, "wb") as fh:
        fh.write(data)
    print("wrote", path, len(data), "bytes")


if __name__ == "__main__":
    main()
