#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MAKE A WISH - AN INTERACTIVE BIRTHDAY EXPERIENCE
A magical birthday celebration using Python, Pygame and NumPy.

    pip install pygame numpy
    python make_a_wish.py

CONTROLS
    SPACE  - hold to make your wish (builds wind), release to blow out the candles
    ENTER  - start the celebration (also skips ahead during the intro scenes)
    R      - restart the birthday experience
    F      - toggle fullscreen
    ESC    - exit

No external image / video / audio assets are used: everything is drawn procedurally.
"""

import math
import random
import sys

import numpy as np
import pygame

# --------------------------------------------------------------------------------------
# Constants & palette
# --------------------------------------------------------------------------------------
W, H = 800, 1200
FPS = 60

IVORY = (246, 237, 217)
CHAMPAGNE = (236, 208, 140)
GOLD = (214, 178, 96)

CW, CH = 560, 520            # cake surface size
CAKE_X0 = 120                # screen x of cake surface (centres cake on x = 400)
CAKE_Y = 330                 # final screen y of cake surface
N_CANDLES = 9

SPARK_COLORS = {
    "gold": (255, 208, 110),
    "white": (255, 244, 225),
    "rose": (255, 170, 150),
    "blue": (170, 205, 255),
    "amber": (255, 150, 60),
    "champ": (245, 222, 160),
}
COL_NAMES = list(SPARK_COLORS.keys())


# --------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------
def clamp(v, a=0.0, b=1.0):
    return a if v < a else b if v > b else v


def lerp(a, b, t):
    return a + (b - a) * t


def smooth(t):
    t = clamp(t)
    return t * t * (3 - 2 * t)


def ease_out_cubic(t):
    t = clamp(t)
    return 1 - (1 - t) ** 3


def ease_out_back(t, s=1.6):
    t = clamp(t) - 1.0
    return 1 + t * t * ((s + 1) * t + s)


def approach(cur, target, rate, dt):
    return cur + (target - cur) * (1.0 - math.exp(-rate * dt))


def scale_col(c, k):
    return (int(clamp(c[0] * k, 0, 255)), int(clamp(c[1] * k, 0, 255)), int(clamp(c[2] * k, 0, 255)))


def shade(nx):
    """Cylinder shading across x in [-1, 1] (light from the upper left)."""
    s = 0.60 + 0.40 * math.sqrt(max(0.0, 1 - nx * nx)) - 0.12 * nx
    s += 0.16 * math.exp(-((nx + 0.5) / 0.13) ** 2)
    return clamp(s, 0.25, 1.25)


def cat_attrs(obj, new):
    for k, v in new.items():
        setattr(obj, k, np.concatenate([getattr(obj, k), v]))


def filt_attrs(obj, names, mask):
    for k in names:
        setattr(obj, k, getattr(obj, k)[mask])


# --------------------------------------------------------------------------------------
# Procedural sprites
# --------------------------------------------------------------------------------------
def make_radial(w, h, cx, cy, rx, ry, color, power=2.0, normalize=False):
    xs = (np.arange(w) + 0.5 - cx) / rx
    ys = (np.arange(h) + 0.5 - cy) / ry
    d = np.sqrt(xs[:, None] ** 2 + ys[None, :] ** 2)
    f = np.clip(1.0 - d, 0.0, 1.0) ** power
    if normalize and f.max() > 0:
        f = f / f.max()
    arr = (f[:, :, None] * np.array(color, dtype=np.float32)[None, None, :]).astype(np.uint8)
    return pygame.surfarray.make_surface(arr).convert()


def glow_surf(rx, ry, color, power=2.0):
    return make_radial(int(rx * 2), int(ry * 2), rx, ry, rx, ry, color, power)


class Glow:
    """Additive light sprite with optional cached intensity levels."""

    def __init__(self, surf, cache=True):
        self.base = surf
        self.w, self.h = surf.get_size()
        self.cache = {} if cache else None

    def _get(self, k):
        lvl = int(clamp(k) * 24 + 0.5)
        if lvl <= 0:
            return None
        if self.cache is not None and lvl in self.cache:
            return self.cache[lvl]
        s = self.base.copy()
        v = int(255 * lvl / 24)
        s.fill((v, v, v), special_flags=pygame.BLEND_RGB_MULT)
        if self.cache is not None:
            self.cache[lvl] = s
        return s

    def add(self, dest, x, y, k):
        if k < 0.02:
            return
        s = self._get(k)
        if s is not None:
            dest.blit(s, (int(x - self.w / 2), int(y - self.h / 2)), special_flags=pygame.BLEND_RGB_ADD)


class SparkBank:
    """Tiny additive glow dots in several colours / sizes / brightness levels."""

    def __init__(self):
        self.c = {}

    def get(self, name, r, lvl):
        key = (name, r, lvl)
        s = self.c.get(key)
        if s is None:
            col = [int(v * lvl / 15.0) for v in SPARK_COLORS[name]]
            s = make_radial(2 * r, 2 * r, r, r, r, r, col, 2.0, normalize=True)
            self.c[key] = s
        return s


def make_puff(size):
    s = pygame.Surface((size, size), pygame.SRCALPHA)
    xs = (np.arange(size) + 0.5 - size / 2) / (size / 2)
    d = np.sqrt(xs[:, None] ** 2 + xs[None, :] ** 2)
    a = (np.clip(1 - d, 0, 1) ** 1.4 * 255).astype(np.uint8)
    rgb = pygame.surfarray.pixels3d(s)
    rgb[:, :, 0] = 214
    rgb[:, :, 1] = 214
    rgb[:, :, 2] = 228
    del rgb
    al = pygame.surfarray.pixels_alpha(s)
    al[:, :] = a
    del al
    return s


def make_beam(w=520, h=720):
    ys = np.arange(h) / float(h)
    hw = 40 + 210 * ys
    xs = np.arange(w) - w / 2 + 0.5
    prof = np.exp(-((xs[:, None] / hw[None, :]) ** 2) * 2.6)
    along = (0.25 + 0.75 * ys ** 0.8) * np.clip(1 - ys ** 5, 0, 1)
    f = prof * along[None, :]
    arr = (f[:, :, None] * np.array((255, 226, 160), dtype=np.float32)[None, None, :] * 0.55).astype(np.uint8)
    return pygame.surfarray.make_surface(arr).convert()


def build_background():
    t = np.linspace(0, 1, H)
    top = np.array([5, 8, 26], dtype=np.float32)
    mid = np.array([13, 21, 60], dtype=np.float32)
    bot = np.array([3, 5, 15], dtype=np.float32)
    k1 = np.clip(t / 0.55, 0, 1)[:, None]
    k2 = np.clip((t - 0.55) / 0.45, 0, 1)[:, None]
    col = np.where((t < 0.55)[:, None], top * (1 - k1) + mid * k1, mid * (1 - k2) + bot * k2)
    arr = np.repeat(col[None, :, :], W, axis=0).astype(np.float32)
    xs = (np.arange(W) - 400) / 430.0
    ys = (np.arange(H) - 590) / 600.0
    d = np.sqrt(xs[:, None] ** 2 + ys[None, :] ** 2)
    arr += (np.clip(1 - d, 0, 1) ** 1.8)[:, :, None] * np.array([14, 26, 66], dtype=np.float32)
    rng = np.random.default_rng(3)
    for _ in range(180):
        x = int(rng.integers(1, W - 1))
        y = int(rng.integers(1, int(H * 0.62)))
        b = float(rng.uniform(25, 95))
        arr[x, y, :] += np.array([b * 0.9, b * 0.95, b], dtype=np.float32)
        if rng.random() < 0.18:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                arr[x + dx, y + dy, :] += b * 0.3
    return pygame.surfarray.make_surface(np.clip(arr, 0, 255).astype(np.uint8)).convert()


def build_vignette():
    w, h = W // 2, H // 2
    xs = (np.arange(w) + 0.5 - w / 2) / (w / 2)
    ys = (np.arange(h) + 0.5 - h / 2) / (h / 2)
    r = np.sqrt(xs[:, None] ** 2 * 0.85 + ys[None, :] ** 2 * 0.85)
    v = 1 - 0.62 * np.clip(r / 1.15, 0, 1) ** 2.2
    arr = np.repeat((v * 255)[:, :, None], 3, axis=2).astype(np.uint8)
    return pygame.surfarray.make_surface(arr).convert()


# --------------------------------------------------------------------------------------
# The cake (drawn once at 2x and smooth-scaled for anti-aliasing)
# --------------------------------------------------------------------------------------
def build_cake(candle_pos):
    K = 2
    S = pygame.Surface((CW * K, CH * K), pygame.SRCALPHA)
    rnd = random.Random(21)
    cx = 280

    def P(v):
        return int(round(v * K))

    def ell(x, y, rx, ry, col, width=0):
        r = pygame.Rect(0, 0, max(2, P(rx * 2)), max(2, P(ry * 2)))
        r.center = (P(x), P(y))
        pygame.draw.ellipse(S, col, r, P(width) if width else 0)

    def slices(x, rx, ya, yb, ry, color, k=1.0):
        for X in range(P(x - rx), P(x + rx)):
            nx = (X + 0.5 - x * K) / (rx * K)
            if abs(nx) >= 1.0:
                continue
            e = math.sqrt(1 - nx * nx) * ry
            pygame.draw.line(S, scale_col(color, shade(nx) * k), (X, P(ya + e)), (X, P(yb + e)))

    def pearl(x, y, r, k=1.0):
        ell(x, y + 0.5, r, r, scale_col((140, 108, 52), k))
        ell(x, y, r * 0.92, r * 0.92, scale_col((238, 212, 152), k))
        ell(x - r * 0.28, y - r * 0.3, r * 0.34, r * 0.28, (255, 251, 238))

    def rosette(x, y, r, k):
        ell(x, y + 0.7, r, r * 0.85, scale_col((190, 172, 140), k))
        ell(x, y, r * 0.96, r * 0.86, scale_col((253, 249, 238), k))
        rect = pygame.Rect(P(x - r * 0.6), P(y - r * 0.5), P(r * 1.2), P(r * 1.0))
        pygame.draw.arc(S, scale_col((205, 188, 156), k), rect, 0.4, 4.4, P(0.9))
        ell(x - r * 0.25, y - r * 0.3, r * 0.26, r * 0.2, (255, 255, 252))

    def drips(x, rx, yt, ry, lo, hi, color):
        xx = x - rx + 14
        while xx < x + rx - 12:
            nx = (xx - x) / rx
            e = math.sqrt(max(0.0, 1 - nx * nx)) * ry
            L = rnd.uniform(lo, hi)
            wd = rnd.uniform(10, 15)
            col = scale_col(color, shade(nx) * 0.98)
            ye = yt + e
            pygame.draw.rect(S, col, (P(xx - wd / 2), P(ye - 2), P(wd), P(L + 2)))
            pygame.draw.circle(S, col, (P(xx), P(ye + L)), P(wd / 2))
            pygame.draw.line(S, scale_col((255, 255, 250), shade(nx)),
                             (P(xx - wd * 0.18), P(ye + 2)), (P(xx - wd * 0.18), P(ye + L - 1)), P(1.2))
            xx += rnd.uniform(17, 26)

    def flakes(x, rx, ya, yb, ry, n, gold):
        for _ in range(n):
            nx = rnd.uniform(-0.88, 0.88)
            e = math.sqrt(1 - nx * nx) * ry
            px = x + rx * nx
            py = rnd.uniform(ya, yb) + e
            r = rnd.uniform(1.6, 3.4)
            pts = [(P(px + math.cos(a) * r * rnd.uniform(0.5, 1.2)), P(py + math.sin(a) * r * rnd.uniform(0.5, 1.2)))
                   for a in np.linspace(0, 2 * math.pi, 6, endpoint=False)]
            pygame.draw.polygon(S, scale_col(gold, shade(nx) * rnd.uniform(0.85, 1.1)), pts)

    CREAM = (238, 226, 200)
    FROST = (253, 249, 238)
    NAVY = (16, 26, 70)
    GL = (214, 178, 96)
    GLH = (248, 226, 158)

    # --- plate / stand --------------------------------------------------------------
    ell(cx, 466, 270, 45, (84, 62, 26))
    ell(cx, 456, 270, 45, (228, 196, 128))
    ell(cx, 456, 254, 40, (206, 172, 98))
    ell(cx, 454, 238, 36, (240, 220, 172))
    ell(cx, 456, 270, 45, (255, 236, 178), width=1.5)
    shd = pygame.Surface(S.get_size(), pygame.SRCALPHA)
    xs = (np.arange(S.get_width()) + 0.5 - P(cx)) / P(214)
    ys = (np.arange(S.get_height()) + 0.5 - P(454)) / P(46)
    dd = np.sqrt(xs[:, None] ** 2 + ys[None, :] ** 2)
    al = pygame.surfarray.pixels_alpha(shd)
    al[:, :] = (np.clip(1 - dd, 0, 1) ** 0.55 * 150).astype(np.uint8)
    del al
    S.blit(shd, (0, 0))

    # --- bottom tier ----------------------------------------------------------------
    bx, bry, byt, byb = 190, 38, 336, 446
    slices(cx, bx, byt, byb, bry, CREAM)
    # navy ribbon with gold trim
    slices(cx, bx, byb - 60, byb - 24, bry, NAVY)
    slices(cx, bx, byb - 52, byb - 50, bry, (44, 60, 128))
    slices(cx, bx, byb - 62, byb - 59, bry, GL)
    slices(cx, bx, byb - 25, byb - 22, bry, GL)
    slices(cx, bx, byb - 62, byb - 61, bry, GLH)
    for a in np.arange(-78, 79, 7.5):
        rad = math.radians(a)
        px = cx + bx * math.sin(rad)
        py = byb - 42 + math.cos(rad) * bry
        s = shade(math.sin(rad))
        pygame.draw.circle(S, scale_col(GLH, s), (P(px), P(py)), P(2.2))
        pygame.draw.circle(S, scale_col((255, 250, 225), s), (P(px - 0.5), P(py - 0.6)), P(0.8))
    flakes(cx, bx, byb - 20, byb - 9, bry, 12, GL)
    for a in np.arange(-86, 87, 4.8):
        rad = math.radians(a)
        pearl(cx + bx * math.sin(rad), byb + math.cos(rad) * bry - 3.5, 3.3, shade(math.sin(rad)))
    drips(cx, bx, byt, bry, 12, 36, FROST)
    ell(cx, byt, bx, bry, scale_col(FROST, 0.93))
    ell(cx, byt + 0.8, bx - 4, bry - 1.8, FROST)
    ell(cx - 14, byt - 1, bx * 0.78, bry * 0.55, (255, 253, 246))
    ell(cx, byt, bx, bry, (255, 255, 250), width=1)

    def rosette_ring(front):
        for a in np.arange(0, 360, 9):
            rad = math.radians(a)
            sx, sy = math.cos(rad), math.sin(rad)
            if (sy >= 0) != front:
                continue
            rosette(cx + 162 * sx, byt + 32 * sy, 6.2, shade(sx))

    rosette_ring(False)

    # --- top tier -------------------------------------------------------------------
    tx, try_, tyt, tyb = 125, 25, 241, 336
    CREAM2 = (242, 231, 208)
    slices(cx, tx, tyt, tyb, try_, CREAM2)
    flakes(cx, tx, tyt + 62, tyb - 12, try_, 16, GL)
    # pearl swags
    angs = np.linspace(-70, 70, 7)
    pts = []
    for a in angs:
        rad = math.radians(a)
        pts.append((cx + tx * math.sin(rad), tyt + 44 + math.cos(rad) * try_, math.sin(rad)))
    for (x1, y1, n1), (x2, y2, n2) in zip(pts, pts[1:]):
        for j in range(1, 6):
            u = j / 6.0
            pearl(lerp(x1, x2, u), lerp(y1, y2, u) + 13 * math.sin(math.pi * u), 2.1, shade(lerp(n1, n2, u)))
    for (x1, y1, n1) in pts:
        pearl(x1, y1, 3.2, shade(n1))
    for a in np.arange(-86, 87, 6.0):
        rad = math.radians(a)
        pearl(cx + tx * math.sin(rad), tyb + math.cos(rad) * try_ - 3.3, 3.0, shade(math.sin(rad)))
    drips(cx, tx, tyt, try_, 10, 30, FROST)
    ell(cx, tyt, tx, try_, scale_col(FROST, 0.93))
    ell(cx, tyt + 0.8, tx - 4, try_ - 1.6, FROST)
    ell(cx - 12, tyt - 1, tx * 0.74, try_ * 0.55, (255, 253, 246))
    ell(cx, tyt, tx, try_, (255, 255, 250), width=1)
    for a in np.arange(0, 360, 9):
        rad = math.radians(a)
        pearl(cx + 112 * math.cos(rad), tyt + 22 * math.sin(rad), 3.0, 0.95)
    # gold dust on the top face
    for _ in range(26):
        a = rnd.uniform(0, 2 * math.pi)
        r = math.sqrt(rnd.uniform(0, 1)) * 0.8
        pygame.draw.circle(S, (230, 196, 112), (P(cx + tx * r * math.cos(a)), P(tyt + try_ * r * math.sin(a))),
                           P(rnd.uniform(0.5, 1.1)))
    # candle contact shadows
    for (x, y) in candle_pos:
        sh = pygame.Surface((P(24), P(10)), pygame.SRCALPHA)
        pygame.draw.ellipse(sh, (120, 95, 50, 110), sh.get_rect())
        S.blit(sh, (P(x - 12), P(y - 5)))

    rosette_ring(True)
    return pygame.transform.smoothscale(S, (CW, CH))


def make_candle(kind):
    K = 3
    cw, ch = 9, 58
    SW, SH = 18, 72
    ox, by = 9, 65
    S = pygame.Surface((SW * K, SH * K), pygame.SRCALPHA)

    def P(v):
        return int(round(v * K))

    bodies = [(250, 243, 226), (234, 208, 144), (24, 34, 84)]
    stripes = [(214, 178, 96), (252, 244, 226), (214, 178, 96)]
    body, st = bodies[kind], stripes[kind]
    for X in range(P(ox - cw / 2), P(ox + cw / 2)):
        nx = (X + 0.5 - ox * K) / (cw / 2 * K)
        pygame.draw.line(S, scale_col(body, shade(nx)), (X, P(by - ch)), (X, P(by)))
    pygame.draw.ellipse(S, scale_col(body, 0.7), pygame.Rect(P(ox - cw / 2), P(by - 1.6), P(cw), P(3.2)))
    for yy in range(-6, ch, 9):
        y0 = by - ch + yy
        for X in range(P(ox - cw / 2), P(ox + cw / 2)):
            nx = (X + 0.5 - ox * K) / (cw / 2 * K)
            yl = y0 + (nx + 1) * 0.5 * 4.5
            if by - ch + 1 <= yl <= by - 1:
                pygame.draw.line(S, scale_col(st, shade(nx)), (X, P(yl)), (X, P(yl) + P(1.1)))
    pygame.draw.ellipse(S, scale_col(body, 1.08), pygame.Rect(P(ox - cw / 2), P(by - ch - 1.6), P(cw), P(3.2)))
    pygame.draw.ellipse(S, scale_col(body, 0.55), pygame.Rect(P(ox - 2.4), P(by - ch - 0.7), P(4.8), P(1.4)))
    pygame.draw.line(S, (36, 28, 26), (P(ox), P(by - ch)), (P(ox + 0.4), P(by - ch - 4.5)), P(1.2))
    return pygame.transform.smoothscale(S, (SW, SH))


# --------------------------------------------------------------------------------------
# Text
# --------------------------------------------------------------------------------------
def make_font(size, bold=False, italic=False):
    names = "georgia,palatinolinotype,palatino,garamond,bookantiqua,timesnewroman,dejavuserif,serif"
    return pygame.font.SysFont(names, size, bold=bold, italic=italic)


def render_spaced(font, text, color, spacing):
    if spacing == 0:
        return font.render(text, True, color).convert_alpha()
    glyphs = [font.render(ch, True, color) for ch in text]
    widths = [font.size(ch)[0] for ch in text]
    total = sum(widths) + spacing * (len(text) - 1)
    surf = pygame.Surface((max(1, total), font.get_height()), pygame.SRCALPHA)
    x = 0
    for g, w in zip(glyphs, widths):
        surf.blit(g, (x, 0))
        x += w + spacing
    return surf


def gold_gradient(surf):
    w, h = surf.get_size()
    t = np.linspace(0, 1, h)
    xs = [0.0, 0.5, 1.0]
    cs = [(255, 246, 214), (238, 203, 122), (176, 134, 56)]
    cols = np.zeros((h, 3))
    for c in range(3):
        cols[:, c] = np.interp(t, xs, [k[c] for k in cs])
    arr = np.repeat(cols[None, :, :], w, axis=0).astype(np.uint8)
    g = pygame.surfarray.make_surface(arr)
    out = surf.copy()
    out.blit(g, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
    return out


class LetterLine:
    """A line of gold letters that can animate in one by one."""

    def __init__(self, text, font, spacing):
        self.letters = []
        x = 0
        for ch in text:
            w = font.size(ch)[0]
            if ch == " ":
                self.letters.append((None, x, w))
            else:
                s = gold_gradient(font.render(ch, True, (255, 255, 255)).convert_alpha())
                self.letters.append((s, x, w))
            x += w + spacing
        self.width = x - spacing

    def draw(self, scr, cx, cy, t, alpha=1.0, wave_t=None, stagger=0.07):
        x0 = cx - self.width / 2
        for i, (s, x, w) in enumerate(self.letters):
            if s is None:
                continue
            lt = (t - i * stagger) / 0.8
            if lt <= 0:
                continue
            e = ease_out_cubic(lt)
            a = clamp(lt * 1.8) * alpha
            if a <= 0.01:
                continue
            yo = (1 - e) * 60
            if wave_t is not None:
                yo += math.sin(wave_t * 2.0 + i * 0.55) * 3.0
            spr = s
            if lt < 1.0:
                sc = lerp(1.5, 1.0, ease_out_back(lt))
                spr = pygame.transform.smoothscale(s, (max(1, int(s.get_width() * sc)), max(1, int(s.get_height() * sc))))
            spr.set_alpha(int(255 * clamp(a)))
            scr.blit(spr, spr.get_rect(center=(int(x0 + x + w / 2), int(cy + yo))))


# --------------------------------------------------------------------------------------
# Particle systems (NumPy-vectorised updates)
# --------------------------------------------------------------------------------------
class Motes:
    """Ambient floating golden dust."""

    def __init__(self, n, rng):
        self.p = np.stack([rng.uniform(0, W, n), rng.uniform(0, H, n)], 1)
        self.v = np.stack([rng.uniform(-8, 8, n), rng.uniform(-24, -6, n)], 1)
        self.ph = rng.uniform(0, 6.283, n)
        self.tw = rng.uniform(0.8, 2.4, n)
        self.sz = rng.choice([2, 2, 3, 3, 4], n)

    def update(self, dt, t, wind):
        self.p[:, 0] += (self.v[:, 0] + np.sin(t * 0.6 + self.ph) * 10 + wind * 60) * dt
        self.p[:, 1] += self.v[:, 1] * dt
        self.p[:, 0] %= W
        self.p[:, 1] %= H

    def draw(self, scr, bank, t, k):
        lv = ((0.25 + 0.75 * (0.5 + 0.5 * np.sin(t * self.tw + self.ph))) * k * 13).astype(int)
        for (x, y), s, l in zip(self.p.tolist(), self.sz.tolist(), lv.tolist()):
            if l <= 0:
                continue
            spr = bank.get("gold", s, l)
            r = spr.get_width() // 2
            scr.blit(spr, (int(x) - r, int(y) - r), special_flags=pygame.BLEND_RGB_ADD)


class Sparks:
    """Generic additive spark system (reveal burst, fireworks, snuff sparks)."""

    NAMES = ["p", "v", "age", "life", "drag", "grav", "size", "col"]

    def __init__(self):
        self.p = np.zeros((0, 2))
        self.v = np.zeros((0, 2))
        self.age = np.zeros(0)
        self.life = np.zeros(0)
        self.drag = np.zeros(0)
        self.grav = np.zeros(0)
        self.size = np.zeros(0, dtype=int)
        self.col = np.zeros(0, dtype=int)

    def add(self, pos, vel, life, drag, grav, size, col):
        n = len(life)
        cat_attrs(self, dict(p=np.asarray(pos, dtype=float), v=np.asarray(vel, dtype=float), age=np.zeros(n),
                             life=np.asarray(life, dtype=float), drag=np.asarray(drag, dtype=float),
                             grav=np.asarray(grav, dtype=float), size=np.asarray(size, dtype=int),
                             col=np.asarray(col, dtype=int)))

    def update(self, dt):
        if len(self.age) == 0:
            return
        self.v *= np.exp(-self.drag * dt)[:, None]
        self.v[:, 1] += self.grav * dt
        self.p += self.v * dt
        self.age += dt
        keep = self.age < self.life
        if not keep.all():
            filt_attrs(self, self.NAMES, keep)

    def draw(self, surf, bank, scale=1.0):
        if len(self.age) == 0:
            return
        f = np.clip(1 - self.age / self.life, 0, 1)
        lv = (f ** 0.6 * 15).astype(int)
        for (x, y), s, c, l in zip(self.p.tolist(), self.size.tolist(), self.col.tolist(), lv.tolist()):
            if l <= 0:
                continue
            spr = bank.get(COL_NAMES[c], s, l)
            r = spr.get_width() // 2
            surf.blit(spr, (int(x * scale) - r, int(y * scale) - r), special_flags=pygame.BLEND_RGB_ADD)


class Gather:
    """Golden particles that spiral in towards the candles (wish energy)."""

    NAMES = ["p", "v", "tg", "age", "life", "sz"]

    def __init__(self):
        self.p = np.zeros((0, 2))
        self.v = np.zeros((0, 2))
        self.tg = np.zeros((0, 2))
        self.age = np.zeros(0)
        self.life = np.zeros(0)
        self.sz = np.zeros(0, dtype=int)

    def spawn(self, n, center, rmin, rmax, targets, rng):
        if n <= 0 or len(targets) == 0:
            return
        ang = rng.uniform(0, 2 * np.pi, n)
        r = rng.uniform(rmin, rmax, n)
        pos = np.stack([center[0] + np.cos(ang) * r, center[1] + np.sin(ang) * r * 0.75], 1)
        tg = targets[rng.integers(0, len(targets), n)]
        vel = np.stack([-np.sin(ang), np.cos(ang)], 1) * rng.uniform(40, 120, n)[:, None]
        cat_attrs(self, dict(p=pos, v=vel, tg=tg, age=np.zeros(n), life=rng.uniform(1.6, 2.6, n),
                             sz=rng.choice([2, 3, 3, 4], n)))

    def update(self, dt):
        if len(self.age) == 0:
            return
        d = self.tg - self.p
        self.v += d * 3.2 * dt
        self.v *= math.exp(-1.7 * dt)
        self.p += self.v * dt
        self.age += dt
        dist = np.sqrt((d ** 2).sum(1))
        keep = (self.age < self.life) & (dist > 5)
        if not keep.all():
            filt_attrs(self, self.NAMES, keep)

    def draw(self, scr, bank):
        if len(self.age) == 0:
            return
        fade = np.clip(self.age / 0.3, 0, 1) * np.clip((self.life - self.age) / 0.5, 0, 1)
        lv = (fade * 15).astype(int)
        for (x, y), s, l in zip(self.p.tolist(), self.sz.tolist(), lv.tolist()):
            if l <= 0:
                continue
            spr = bank.get("gold", s, l)
            r = spr.get_width() // 2
            scr.blit(spr, (int(x) - r, int(y) - r), special_flags=pygame.BLEND_RGB_ADD)


class WindFX:
    """Faint streaks flowing from the viewer towards the candles."""

    NAMES = ["p", "v", "tg", "age"]

    def __init__(self):
        self.p = np.zeros((0, 2))
        self.v = np.zeros((0, 2))
        self.tg = np.zeros((0, 2))
        self.age = np.zeros(0)

    def update(self, dt, wind, rng):
        if wind > 0.04:
            n = int(rng.poisson(wind * 95 * dt))
            if n > 0:
                x = 400 + rng.normal(0, 150, n)
                y = rng.uniform(1000, 1170, n)
                tx = 400 + rng.uniform(-80, 80, n)
                ty = rng.uniform(535, 585, n)
                d = np.stack([tx - x, ty - y], 1)
                d /= np.linalg.norm(d, axis=1)[:, None]
                v = d * rng.uniform(520, 820, n)[:, None]
                cat_attrs(self, dict(p=np.stack([x, y], 1), v=v, tg=np.stack([tx, ty], 1), age=np.zeros(n)))
        if len(self.age) == 0:
            return
        self.p += self.v * dt
        self.age += dt
        d = self.tg - self.p
        dist = np.sqrt((d ** 2).sum(1))
        near = dist < 170
        self.v[near, 0] += (1 - dist[near] / 170) * 1300 * dt
        self.v[near, 1] *= (1 - 2.0 * dt)
        keep = (dist > 24) & (self.age < 2.2)
        if not keep.all():
            filt_attrs(self, self.NAMES, keep)

    def draw(self, scr, bank, wind):
        if len(self.age) == 0 or wind < 0.03:
            return
        for (x, y), (vx, vy), (tx, ty), age in zip(self.p.tolist(), self.v.tolist(), self.tg.tolist(), self.age.tolist()):
            dist = math.hypot(tx - x, ty - y)
            a = wind * clamp(age / 0.2) * (0.35 + 0.65 * clamp(dist / 450))
            l = int(a * 12)
            if l <= 0:
                continue
            for k in range(4):
                q = k * 0.011
                spr = bank.get("blue", 2 if k < 2 else 1, max(1, l - k * 2))
                r = spr.get_width() // 2
                scr.blit(spr, (int(x - vx * q) - r, int(y - vy * q) - r), special_flags=pygame.BLEND_RGB_ADD)


class Smoke:
    """Curling smoke rising from extinguished wicks."""

    SIZES = [4, 6, 8, 11, 15, 20, 27, 36, 48, 64]
    NAMES = ["p", "age", "life", "s0", "ph", "a0"]

    def __init__(self):
        self.sprites = [make_puff(s) for s in self.SIZES]
        self.sz_arr = np.array(self.SIZES, dtype=np.float32)
        self.clear()

    def clear(self):
        self.p = np.zeros((0, 2))
        self.age = np.zeros(0)
        self.life = np.zeros(0)
        self.s0 = np.zeros(0)
        self.ph = np.zeros(0)
        self.a0 = np.zeros(0)

    def emit(self, x, y, n, rng, a0, s0, life=(3.0, 4.6)):
        if n <= 0:
            return
        cat_attrs(self, dict(p=np.stack([x + rng.normal(0, 0.8, n), y + rng.normal(0, 0.8, n)], 1),
                             age=np.zeros(n), life=rng.uniform(life[0], life[1], n),
                             s0=np.full(n, float(s0)) * rng.uniform(0.8, 1.2, n),
                             ph=rng.uniform(0, 6.283, n), a0=np.full(n, float(a0))))

    def update(self, dt, wind):
        if len(self.age) == 0:
            return
        an = self.age / self.life
        curl = (np.sin(self.age * 2.2 + self.ph + self.p[:, 1] * 0.017) * (5 + 36 * an)
                + np.sin(self.age * 4.3 + self.ph * 1.7) * (2 + 9 * an))
        vx = curl + wind * 170 * (0.4 + an)
        vy = -(58 - 30 * an)
        self.p[:, 0] += vx * dt
        self.p[:, 1] += vy * dt
        self.age += dt
        keep = self.age < self.life
        if not keep.all():
            filt_attrs(self, self.NAMES, keep)

    def draw(self, scr):
        if len(self.age) == 0:
            return
        an = self.age / self.life
        size = self.s0 * (1 + 5.0 * an)
        idx = np.clip(np.searchsorted(self.sz_arr, size), 0, len(self.SIZES) - 1)
        alpha = self.a0 * (1 - an) ** 1.5 * np.clip(self.age / 0.3, 0, 1)
        for (x, y), i, a in zip(self.p.tolist(), idx.tolist(), alpha.tolist()):
            a8 = int(a * 255)
            if a8 <= 1:
                continue
            spr = self.sprites[i]
            spr.set_alpha(a8)
            scr.blit(spr, (int(x - spr.get_width() / 2), int(y - spr.get_height() / 2)))


class Confetti:
    PAL = np.array([(238, 206, 128), (214, 176, 96), (252, 240, 214), (190, 150, 70),
                    (246, 222, 170), (255, 255, 250), (205, 160, 110), (226, 190, 150)], dtype=np.float32)
    NAMES = ["p", "vy", "ph", "ang", "spin", "flip", "fsp", "w", "h", "col"]

    def __init__(self):
        self.clear()

    def clear(self):
        self.p = np.zeros((0, 2))
        for k in self.NAMES[1:-1]:
            setattr(self, k, np.zeros(0))
        self.col = np.zeros((0, 3))

    def spawn(self, n, ylo, yhi, rng):
        if n <= 0:
            return
        cat_attrs(self, dict(
            p=np.stack([rng.uniform(-20, W + 20, n), rng.uniform(ylo, yhi, n)], 1),
            vy=rng.uniform(70, 170, n), ph=rng.uniform(0, 6.283, n), ang=rng.uniform(0, 6.283, n),
            spin=rng.uniform(-4, 4, n), flip=rng.uniform(0, 6.283, n), fsp=rng.uniform(3, 9, n),
            w=rng.uniform(5, 10, n), h=rng.uniform(9, 17, n),
            col=self.PAL[rng.integers(0, len(self.PAL), n)]))

    def update(self, dt, t, wind=0.0):
        if len(self.vy) == 0:
            return
        self.p[:, 1] += self.vy * dt
        self.p[:, 0] += (np.sin(t * 1.6 + self.ph) * 32 + wind * 40) * dt
        self.ang += self.spin * dt
        self.flip += self.fsp * dt
        keep = self.p[:, 1] < H + 30
        if not keep.all():
            filt_attrs(self, self.NAMES, keep)

    def draw(self, scr):
        n = len(self.vy)
        if n == 0:
            return
        fw = np.abs(np.cos(self.flip))
        hw = self.w * 0.5 * fw
        hh = self.h * 0.5
        lx = np.stack([-hw, hw, hw, -hw], 1)
        ly = np.stack([-hh, -hh, hh, hh], 1)
        cs, sn = np.cos(self.ang)[:, None], np.sin(self.ang)[:, None]
        X = self.p[:, 0:1] + lx * cs - ly * sn
        Y = self.p[:, 1:2] + lx * sn + ly * cs
        pts = np.stack([X, Y], 2).tolist()
        cols = (self.col * (0.55 + 0.45 * fw)[:, None]).astype(int).tolist()
        ys = self.p[:, 1].tolist()
        for i in range(n):
            if ys[i] < -20:
                continue
            pygame.draw.polygon(scr, cols[i], pts[i])


class Fireworks:
    """Rockets and bursts rendered into a half-res, fading trail layer behind the cake."""

    def __init__(self):
        self.layer = pygame.Surface((W // 2, 320), 0, 32)
        self.full = pygame.Surface((W, 640), 0, 32)
        self.reset()

    def reset(self):
        self.sparks = Sparks()
        self.rockets = []
        self.flashes = []
        self.timer = 0.3
        self.cool = 0.0
        self.dt = 1 / 60.0
        self.layer.fill((0, 0, 0))

    def launch(self, rng):
        self.rockets.append({
            "x": float(rng.uniform(120, 680)), "y": 800.0, "vy": -float(rng.uniform(560, 680)),
            "ty": float(rng.uniform(140, 420)),
            "kind": str(rng.choice(["peony", "ring", "willow", "peony"])),
            "col": str(rng.choice(["gold", "champ", "white", "rose", "blue", "gold"]))})

    def explode(self, x, y, r, rng):
        kind, col = r["kind"], r["col"]
        if kind == "peony":
            n = 110
            ang = rng.uniform(0, 2 * np.pi, n)
            sp = 300 * np.sqrt(rng.uniform(0.05, 1, n))
            drag, grav, life = 1.5, 75.0, rng.uniform(1.4, 2.1, n)
            vel = np.stack([np.cos(ang) * sp, np.sin(ang) * sp], 1)
        elif kind == "ring":
            n = 84
            ang = np.linspace(0, 2 * np.pi, n, endpoint=False)
            sq = rng.uniform(0.35, 1.0)
            rot = rng.uniform(0, np.pi)
            vx, vy = np.cos(ang) * 250, np.sin(ang) * 250 * sq
            vel = np.stack([vx * np.cos(rot) - vy * np.sin(rot), vx * np.sin(rot) + vy * np.cos(rot)], 1)
            drag, grav, life = 1.4, 55.0, rng.uniform(1.6, 2.2, n)
        else:
            n = 100
            ang = rng.uniform(0, 2 * np.pi, n)
            sp = rng.uniform(90, 250, n)
            drag, grav, life = 2.0, 120.0, rng.uniform(2.2, 3.2, n)
            vel = np.stack([np.cos(ang) * sp, np.sin(ang) * sp], 1)
            col = "gold" if rng.random() < 0.6 else "champ"
        main = COL_NAMES.index(col)
        cols = np.where(rng.random(n) < 0.75, main, COL_NAMES.index("white"))
        self.sparks.add(np.tile([x, y], (n, 1)), vel, life, np.full(n, drag), np.full(n, grav),
                        rng.choice([1, 2], n), cols)
        self.flashes.append((x, y, col))

    def update(self, dt, active, rng):
        self.dt = dt
        if active:
            self.timer -= dt
            if self.timer <= 0:
                self.launch(rng)
                self.timer = float(rng.uniform(0.5, 1.2))
        for r in self.rockets[:]:
            r["y"] += r["vy"] * dt
            r["vy"] *= (1 - 0.9 * dt)
            if r["y"] <= r["ty"] or r["vy"] > -110:
                self.explode(r["x"], r["y"], r, rng)
                self.rockets.remove(r)
        self.sparks.update(dt)
        if active or self.rockets or len(self.sparks.age):
            self.cool = 1.4
        else:
            self.cool = max(0.0, self.cool - dt)

    def draw(self, scr, bank):
        if self.cool <= 0:
            return
        fv = int(255 * 0.9 ** (self.dt * 60))
        self.layer.fill((fv, fv, fv), special_flags=pygame.BLEND_RGB_MULT)
        self.layer.fill((6, 6, 6), special_flags=pygame.BLEND_RGB_SUB)
        for x, y, col in self.flashes:
            spr = bank.get(col, 16, 11)
            self.layer.blit(spr, (int(x / 2) - 16, int(y / 2) - 16), special_flags=pygame.BLEND_RGB_ADD)
        self.flashes = []
        for r in self.rockets:
            if r["y"] < 640:
                spr = bank.get("white", 2, 15)
                self.layer.blit(spr, (int(r["x"] / 2) - 2, int(r["y"] / 2) - 2), special_flags=pygame.BLEND_RGB_ADD)
        self.sparks.draw(self.layer, bank, 0.5)
        pygame.transform.smoothscale(self.layer, (W, 640), self.full)
        scr.blit(self.full, (0, 0), special_flags=pygame.BLEND_RGB_ADD)


# --------------------------------------------------------------------------------------
# Candle
# --------------------------------------------------------------------------------------
class Candle:
    def __init__(self, i, lx, ly, kind, thr, order, rnd):
        self.i, self.lx, self.ly, self.kind = i, lx, ly, kind
        self.thr = thr                  # blow strength needed to put this one out
        self.order = order              # reveal order
        self.reveal = 0.0
        self.state = "idle"             # idle -> burning -> snuffing -> out
        self.f = 0.0                    # flame intensity 0..1
        self.wait = 0.0
        self.out_t = 0.0
        self.smoke_acc = 0.0
        self.flick = 1.0
        self.ph = [rnd.uniform(0, 6.283) for _ in range(5)]
        self.sx = self.sy = self.fy = 0.0

    def flicker(self, t):
        p = self.ph
        return (0.5 * math.sin(t * 5.1 + p[0])
                + 0.3 * math.sin(t * 8.3 + p[1] + 1.3 * math.sin(t * 1.7 + p[4]))
                + 0.2 * math.sin(t * 13.7 + p[2]))


# --------------------------------------------------------------------------------------
# The game
# --------------------------------------------------------------------------------------
class Game:
    def __init__(self):
        pygame.init()
        try:
            self.screen = pygame.display.set_mode((W, H), pygame.SCALED)
        except pygame.error:
            self.screen = pygame.display.set_mode((W, H))
        pygame.display.set_caption("Make a Wish")
        pygame.mouse.set_visible(False)
        self.clock = pygame.time.Clock()
        self.nr = np.random.default_rng()
        self.build_assets()
        self.reset("title")

    # ------------------------------------------------------------------ assets
    def build_assets(self):
        self.bg = build_background()
        self.vig = build_vignette()
        self.lm = pygame.Surface((W // 2, H // 2), 0, 32)
        self.lm_full = pygame.Surface((W, H), 0, 32)
        self.bank = SparkBank()
        self.gl_candle = Glow(glow_surf(120, 120, (255, 196, 128), 2.0))
        self.gl_spot = Glow(glow_surf(190, 250, (255, 228, 172), 1.5), cache=False)
        self.gl_flame = Glow(glow_surf(50, 50, (255, 176, 80), 2.2))
        self.gl_halo = Glow(glow_surf(130, 130, (255, 150, 60), 2.6))
        self.gl_aura = Glow(glow_surf(320, 260, (255, 205, 120), 2.0), cache=False)
        self.gl_ember = Glow(glow_surf(18, 18, (255, 120, 50), 2.0))
        self.gl_text = Glow(glow_surf(300, 70, (255, 205, 120), 2.0), cache=False)
        self.gold_glow = Glow(make_radial(W, H, 400, 570, 540, 720, (255, 190, 100), 1.6), cache=False)
        self.beam = Glow(make_beam(), cache=False)
        self.flame_big = pygame.Surface((192, 224), pygame.SRCALPHA)
        self.flame_small = pygame.Surface((96, 112), pygame.SRCALPHA)

        self.candle_pos = []
        for k in range(N_CANDLES):
            a = math.pi / 2 + 2 * math.pi * k / N_CANDLES
            self.candle_pos.append((280 + 86 * math.cos(a), 241 + 17 * math.sin(a)))
        self.cake = build_cake(self.candle_pos)
        self.candle_sprites = [make_candle(k) for k in range(3)]

        rows = 150
        crop = self.cake.subsurface(pygame.Rect(0, 507 - rows, CW, rows)).copy()
        refl = pygame.transform.flip(crop, False, True)
        refl = pygame.transform.smoothscale(refl, (CW, int(rows * 0.75)))
        hh = refl.get_height()
        al = pygame.surfarray.pixels_alpha(refl)
        g = (np.clip(1 - np.arange(hh) / hh, 0, 1) ** 1.7) * 0.30
        al[:, :] = (al * g[None, :]).astype(np.uint8)
        del al
        self.refl = refl

        self.smoke = Smoke()
        self.fw = Fireworks()
        self.motes = Motes(90, self.nr)
        self.build_texts()

    def build_texts(self):
        ivory = (244, 234, 214)
        f_it34 = make_font(34, italic=True)
        f_it28 = make_font(28, italic=True)
        f_it24 = make_font(24, italic=True)
        f_small = make_font(17)
        f_title = make_font(66, bold=True)
        f_wish = make_font(66, bold=True)
        f_hb = make_font(86, bold=True)
        f_cd = make_font(170)
        tx = {}
        tx["t1"] = render_spaced(f_it34, "Someone special is celebrating today...", ivory, 0)
        tx["t2a"] = render_spaced(f_it34, "Before we celebrate...", ivory, 0)
        tx["t2b"] = render_spaced(f_it34, "Close your eyes and make a wish.", ivory, 0)
        for d in "321":
            tx["cd" + d] = gold_gradient(render_spaced(f_cd, d, (255, 255, 255), 0))
        tx["instr"] = render_spaced(f_it28, "Press and hold SPACE to make your wish.", ivory, 0)
        tx["keep"] = render_spaced(f_it28, "Keep holding...", ivory, 0)
        tx["release"] = render_spaced(f_it28, "Now - release.", (255, 226, 160), 0)
        tx["almost"] = render_spaced(f_it28, "So close - one more try. Hold a little longer.", ivory, 0)
        tx["short"] = render_spaced(f_it28, "Hold a little longer...", ivory, 0)
        tx["title"] = gold_gradient(render_spaced(f_title, "MAKE A WISH", (255, 255, 255), 12))
        tx["title_sub"] = render_spaced(f_it28, "an interactive birthday surprise", ivory, 0)
        tx["press_enter"] = render_spaced(f_it28, "Press ENTER to begin", (255, 226, 160), 0)
        tx["sub_wish"] = render_spaced(f_it34, "Now let the beautiful things begin.", ivory, 0)
        tx["sub_hb"] = render_spaced(f_it34, "May every little wish find its way to you.", ivory, 0)
        tx["replay"] = render_spaced(f_it24, "Press R to replay", (255, 226, 160), 0)
        tx["footer"] = render_spaced(f_small, "R  restart        F  fullscreen        ESC  exit", (200, 190, 170), 1)
        self.tx = tx
        self.ln_wish = LetterLine("WISH MADE.", f_wish, 8)
        self.ln_happy = LetterLine("HAPPY", f_hb, 7)
        self.ln_bday = LetterLine("BIRTHDAY!", f_hb, 7)

    # ------------------------------------------------------------------ state
    def reset(self, to="intro"):
        rnd = random.Random()
        thr = list(np.linspace(0.15, 0.82, N_CANDLES))
        rnd.shuffle(thr)
        order = list(range(N_CANDLES))
        rnd.shuffle(order)
        self.candles = [Candle(i, lx, ly, i % 3, float(thr[i]), order[i], rnd)
                        for i, (lx, ly) in enumerate(self.candle_pos)]
        self.t = 0.0
        self.ts = 0.0
        self.smoke.clear()
        self.gather = Gather()
        self.burst = Sparks()
        self.windfx = WindFX()
        self.conf = Confetti()
        self.fw.reset()
        self.amb = 1.0
        self.amb_t = 1.0
        self.amb_rate = 2.0
        self.warm = 0.0
        self.warm_t = 0.0
        self.gold = 0.0
        self.gold_t = 0.0
        self.gold_rate = 3.0
        self.spot = 0.0
        self.spot_t = 0.0
        self.flash = 0.0
        self.wind = 0.0
        self.aura = 0.0
        self.charge = 0.0
        self.gust = 0.0
        self.rel_t = 0.0
        self.pending = []
        self.chosen_count = 0
        self.blow_phase = "ready"
        self.msg = ""
        self.msg_t = 99.0
        self.cake_p = 0.0
        self.cake_y = CAKE_Y + 720
        self.revealed = False
        self.state = ""
        self.set_state(to)

    def prepare_candles(self):
        for c in self.candles:
            c.reveal = 1.0
            if c.state == "idle":
                c.state = "burning"
                c.f = max(c.f, 0.4)

    def set_state(self, name):
        self.state = name
        self.ts = 0.0
        if name == "title":
            self.cake_p = 0.0
            self.amb_t = 1.0
        elif name == "intro":
            self.cake_p = 0.0
            self.amb_t, self.amb_rate = 0.8, 2.0
        elif name == "wish":
            self.cake_p = 1.0
            self.prepare_candles()
            self.amb_t, self.amb_rate = 0.2, 1.4
        elif name == "blow":
            self.cake_p = 1.0
            self.prepare_candles()
            self.blow_phase = "ready"
            self.charge = 0.0
            self.msg, self.msg_t = "", 99.0
            self.amb_t, self.amb_rate = 0.2, 2.0
        elif name == "reveal":
            self.revealed = False
            self.amb_t, self.amb_rate = 0.05, 3.0
        elif name == "celebrate":
            self.amb_t, self.amb_rate = 0.92, 1.2
            self.warm_t = 1.0
            self.gold_t, self.gold_rate = 0.42, 0.8
            self.spot_t = 1.0
            self.conf.spawn(220, -760, -20, self.nr)

    def on_enter(self):
        s = self.state
        if s == "title":
            self.set_state("intro")
        elif s == "intro":
            self.set_state("wish")
        elif s == "wish":
            self.set_state("blow")
        elif s == "reveal" and self.ts > 2.0:
            self.set_state("celebrate")

    # ------------------------------------------------------------------ update
    def update(self, dt):
        self.t += dt
        self.ts += dt
        space = pygame.key.get_pressed()[pygame.K_SPACE]
        getattr(self, "upd_" + self.state)(dt, space)

        if self.state != "blow":
            self.wind = approach(self.wind, 0.0, 5.0, dt)
        self.amb = approach(self.amb, self.amb_t, self.amb_rate, dt)
        self.warm = approach(self.warm, self.warm_t, 1.5, dt)
        self.gold = approach(self.gold, self.gold_t, self.gold_rate, dt)
        self.spot = approach(self.spot, self.spot_t, 1.4, dt)
        self.flash = max(0.0, self.flash - dt * 1.8)
        aura_t = 0.0
        if self.state == "blow":
            aura_t = 0.62 * self.charge if self.blow_phase == "holding" else (0.7 * self.wind if self.blow_phase == "release" else 0.0)
        self.aura = approach(self.aura, aura_t, 8.0, dt)

        self.cake_y = CAKE_Y + (1 - ease_out_cubic(self.cake_p)) * 720
        self.update_candles(dt)
        self.smoke.update(dt, self.wind)
        self.motes.update(dt, self.t, self.wind)
        self.gather.update(dt)
        self.burst.update(dt)
        self.windfx.update(dt, self.wind, self.nr)
        self.fw.update(dt, self.state == "celebrate", self.nr)
        self.conf.update(dt, self.t, self.wind)

    def targets(self):
        return np.array([[c.sx, c.fy - 12] for c in self.candles], dtype=float)

    def upd_title(self, dt, space):
        pass

    def upd_intro(self, dt, space):
        ts = self.ts
        self.cake_p = clamp((ts - 0.5) / 3.8)
        for c in self.candles:
            c.reveal = clamp((ts - 4.2 - c.order * 0.3) / 0.55)
        if ts >= 8.6:
            self.set_state("wish")

    def upd_wish(self, dt, space):
        ts = self.ts
        if ts > 1.0:
            rate = min(1.0, (ts - 1.0) / 2.0) * 55
            self.gather.spawn(int(self.nr.poisson(rate * dt)), (400, 570), 150, 330, self.targets(), self.nr)
        if ts >= 8.0:
            self.set_state("blow")

    def upd_blow(self, dt, space):
        active = any(c.state in ("burning", "snuffing") for c in self.candles)
        self.amb_t = 0.2 if active else 0.06
        self.msg_t += dt
        ph = self.blow_phase
        if ph == "ready":
            self.charge = max(0.0, self.charge - dt * 2.0)
            self.wind = approach(self.wind, 0.0, 5.0, dt)
            if space:
                self.blow_phase = "holding"
                self.msg_t = 99.0
        elif ph == "holding":
            self.charge = min(1.0, self.charge + dt / 2.0)
            self.wind = approach(self.wind, 0.95 * smooth(self.charge) + 0.05, 6.0, dt)
            if self.charge > 0.05:
                self.gather.spawn(int(self.nr.poisson(70 * self.charge * dt)), (400, 570), 120, 270,
                                  self.targets(), self.nr)
            if not space:
                self.release_blow()
        else:
            self.rel_t += dt
            self.wind = approach(self.wind, self.gust * math.exp(-self.rel_t * 1.5), 16.0, dt)
            still = []
            for item in self.pending:
                if self.rel_t >= item[0]:
                    item[1].state = "snuffing"
                else:
                    still.append(item)
            self.pending = still
            busy = bool(self.pending) or any(c.state == "snuffing" for c in self.candles)
            if not busy and self.rel_t > 1.1:
                if any(c.state == "burning" for c in self.candles):
                    self.blow_phase = "ready"
                    self.charge = 0.0
                    self.msg = "almost" if self.chosen_count > 0 else "short"
                    self.msg_t = 0.0
                else:
                    self.set_state("reveal")

    def release_blow(self):
        lit = sorted([c for c in self.candles if c.state == "burning"], key=lambda c: c.thr)
        if self.charge >= 0.88:
            chosen = lit
        else:
            chosen = [c for c in lit if c.thr <= self.charge]
        self.chosen_count = len(chosen)
        self.pending = [[0.10 + i * 0.14 + random.uniform(0, 0.05), c] for i, c in enumerate(chosen)]
        self.gust = 0.7 + 0.4 * self.charge
        self.rel_t = 0.0
        self.blow_phase = "release"

    def upd_reveal(self, dt, space):
        ts = self.ts
        if ts >= 1.5 and not self.revealed:
            self.revealed = True
            self.flash = 1.0
            self.gold_t, self.gold_rate = 1.0, 8.0
            self.amb_t, self.amb_rate = 1.0, 7.0
            self.warm_t = 0.6
            self.burst_reveal()
        if ts >= 7.6:
            self.set_state("celebrate")

    def upd_celebrate(self, dt, space):
        self.conf.spawn(int(self.nr.poisson(34 * dt)), -30, -10, self.nr)

    def burst_reveal(self):
        rng = self.nr
        n = 420
        ang = rng.uniform(0, 2 * np.pi, n)
        fast = rng.random(n) < 0.45
        sp = np.where(fast, rng.uniform(420, 860, n), rng.uniform(120, 420, n))
        vel = np.stack([np.cos(ang) * sp, np.sin(ang) * sp * 0.9 - 40], 1)
        pos = np.tile(np.array([400.0, 540.0]), (n, 1)) + rng.normal(0, 6, (n, 2))
        self.burst.add(pos, vel, rng.uniform(1.6, 3.4, n), rng.uniform(0.9, 1.8, n), np.full(n, 45.0),
                       rng.choice([2, 3, 5], n, p=[0.6, 0.3, 0.1]),
                       rng.choice([0, 5, 1, 4], n, p=[0.5, 0.3, 0.15, 0.05]))

    def update_candles(self, dt):
        t = self.t
        for c in self.candles:
            c.sx = CAKE_X0 + c.lx
            c.sy = self.cake_y + c.ly
            c.fy = c.sy - 62.5
            c.flick = 0.86 + 0.14 * c.flicker(t * 1.2)
            if c.state == "idle":
                if c.reveal >= 1.0:
                    c.wait += dt
                    if c.wait > 0.25:
                        c.state = "burning"
            elif c.state == "burning":
                c.f = min(1.0, c.f + dt * 1.7)
            elif c.state == "snuffing":
                c.f -= dt / 0.32
                if c.f <= 0:
                    c.f = 0.0
                    c.state = "out"
                    c.out_t = 0.0
                    self.on_out(c)
            elif c.state == "out":
                c.out_t += dt
                c.smoke_acc += (5.0 + 20.0 * math.exp(-c.out_t / 2.2)) * dt
                n = int(c.smoke_acc)
                if n:
                    c.smoke_acc -= n
                    self.smoke.emit(c.sx + 0.3, c.fy, n, self.nr, 0.17, 5.0)

    def on_out(self, c):
        rng = self.nr
        self.smoke.emit(c.sx, c.fy, 4, rng, 0.30, 7.0, (3.4, 5.0))
        n = 6
        vel = np.stack([rng.uniform(-35, 35, n), -rng.uniform(40, 120, n)], 1)
        self.burst.add(np.tile([c.sx, c.fy], (n, 1)), vel, rng.uniform(0.4, 0.9, n), np.full(n, 2.0),
                       np.full(n, 20.0), np.full(n, 2), np.full(n, 4))

    # ------------------------------------------------------------------ draw
    def blit_center(self, surf, cx, cy, a, scale=1.0):
        if a <= 0.01:
            return
        if scale != 1.0:
            surf = pygame.transform.smoothscale(
                surf, (max(1, int(surf.get_width() * scale)), max(1, int(surf.get_height() * scale))))
        surf.set_alpha(int(255 * clamp(a)))
        self.screen.blit(surf, surf.get_rect(center=(int(cx), int(cy))))

    def draw_cake(self):
        scr = self.screen
        y0 = int(self.cake_y)
        scr.blit(self.refl, (CAKE_X0, y0 + 507))
        scr.blit(self.cake, (CAKE_X0, y0))
        for c in sorted(self.candles, key=lambda c: c.ly):
            r = ease_out_cubic(c.reveal)
            if r <= 0:
                continue
            spr = self.candle_sprites[c.kind]
            dy = (1 - r) * 68
            scr.set_clip(pygame.Rect(int(c.sx) - 14, 0, 28, int(c.sy) + 2))
            scr.blit(spr, (int(c.sx) - 9, int(c.sy) - 65 + int(dy)))
            scr.set_clip(None)

    def apply_lighting(self):
        lm = self.lm
        lm.blit(self.vig, (0, 0))
        a = self.amb
        cool, warm = (0.78, 0.86, 1.0), (1.0, 0.93, 0.82)
        col = tuple(int(clamp(a * lerp(cool[i], warm[i], self.warm), 0, 1) * 255) for i in range(3))
        lm.fill(col, special_flags=pygame.BLEND_RGB_MULT)
        for c in self.candles:
            if c.f > 0.02:
                self.gl_candle.add(lm, c.sx / 2, (c.fy - 14) / 2, 0.26 * c.f * c.flick)
        spot_k = min(1.0, self.spot * 0.8 + self.gold * 0.55)
        if spot_k > 0.02:
            self.gl_spot.add(lm, 200, 295, spot_k)
        pygame.transform.smoothscale(lm, (W, H), self.lm_full)
        self.screen.blit(self.lm_full, (0, 0), special_flags=pygame.BLEND_RGB_MULT)

    def draw_flame(self, c):
        if c.f <= 0.02:
            return
        t = self.t
        wl = clamp(self.wind * (0.85 + 0.3 * math.sin(c.ph[3] + t * 0.7)), 0, 1.2)
        n1 = c.flicker(t)
        n2 = c.flicker(t * 1.31 + 4.0)
        f = c.f
        Hh = 42 * f * (1 + 0.11 * n1 + 0.05 * math.sin(t * 23 + c.ph[3])) * (1 - 0.34 * wl)
        Ww = 7.4 * (0.55 + 0.45 * f) * (1 - 0.1 * wl) * (1 + 0.06 * n2)
        lean = wl * 17 + (n2 * 2.6) * (1 + 2.2 * wl)
        sway = n1 * 1.6 * (1 + 1.5 * wl)
        ox, oy = 48, 100
        fs = self.flame_big
        fs.fill((255, 110, 20, 0))

        def poly(hs, ws, color):
            left, right = [], []
            N = 14
            for i in range(N + 1):
                u = i / N
                w = ws * math.sin(math.pi * u ** 0.62)
                cx = ox + lean * u ** 1.7 + sway * u
                y = oy - hs * u
                left.append((cx - w, y))
                right.append((cx + w, y))
            pts = [(x * 2, y * 2) for x, y in left + right[::-1]]
            pygame.draw.polygon(fs, color, pts)

        poly(Hh * 1.18, Ww * 1.5, (255, 96, 16, 60))
        poly(Hh * 1.08, Ww * 1.22, (255, 140, 28, 130))
        poly(Hh, Ww, (255, 190, 60, 235))
        poly(Hh * 0.72, Ww * 0.66, (255, 232, 150, 255))
        poly(Hh * 0.40, Ww * 0.34, (255, 252, 232, 255))
        pygame.draw.ellipse(fs, (80, 130, 255, 150),
                            pygame.Rect(int((ox - Ww * 0.5) * 2), int((oy - 5) * 2), max(2, int(Ww * 2)), 14))
        pygame.transform.smoothscale(fs, (96, 112), self.flame_small)
        gx, gy = c.sx + lean * 0.45, c.fy - Hh * 0.45
        self.gl_halo.add(self.screen, gx, gy, 0.20 * f * c.flick)
        self.gl_flame.add(self.screen, gx, gy, 0.55 * f * c.flick)
        self.screen.blit(self.flame_small, (int(c.sx) - ox, int(c.fy) - oy))

    def draw(self):
        scr = self.screen
        st, t = self.state, self.t
        scr.blit(self.bg, (0, 0))
        if self.gold > 0.01:
            self.gold_glow.add(scr, W / 2, H / 2, self.gold)
        self.fw.draw(scr, self.bank)
        if st != "title":
            self.draw_cake()
        self.apply_lighting()

        # --- foreground / emissive layers ----------------------------------------
        self.motes.draw(scr, self.bank, t, 0.6 if st == "celebrate" else 1.0)
        if self.aura > 0.02:
            self.gl_aura.add(scr, 400, 565, self.aura * (0.85 + 0.15 * math.sin(t * 9)))
        self.gather.draw(scr, self.bank)
        self.windfx.draw(scr, self.bank, self.wind)
        for c in sorted(self.candles, key=lambda c: c.ly):
            self.draw_flame(c)
            if c.state == "out":
                e = math.exp(-c.out_t / 1.7)
                if e > 0.05:
                    self.gl_ember.add(scr, c.sx, c.fy, 0.9 * e)
                    if e > 0.2:
                        pygame.draw.circle(scr, (255, 130, 60), (int(c.sx), int(c.fy)), 1)
        self.smoke.draw(scr)
        self.burst.draw(scr, self.bank)
        if self.spot > 0.02:
            self.beam.add(scr, 400, 360, self.spot * 0.7)
        if self.flash > 0.01:
            v = self.flash
            scr.fill((int(255 * v * 0.9), int(215 * v * 0.8), int(140 * v * 0.7)), special_flags=pygame.BLEND_RGB_ADD)
        self.conf.draw(scr)
        self.draw_ui()

    def draw_ui(self):
        scr, st, ts, t, tx = self.screen, self.state, self.ts, self.t, self.tx
        if st == "title":
            a = smooth(t / 1.2)
            self.gl_text.add(scr, 400, 470, 0.22 * a)
            self.blit_center(tx["title"], 400, 470, a)
            self.blit_center(tx["title_sub"], 400, 548, smooth((t - 0.8) / 1.0) * 0.9)
            self.blit_center(tx["press_enter"], 400, 700, smooth((t - 1.6) / 0.8) * (0.55 + 0.45 * math.sin(t * 2.4)))
        elif st == "intro":
            a = smooth((ts - 1.8) / 1.2) * (1 - smooth((ts - 7.6) / 0.9))
            self.blit_center(tx["t1"], 400, 170, a)
        elif st == "wish":
            fade = 1 - smooth((ts - 4.4) / 0.6)
            self.blit_center(tx["t2a"], 400, 150, smooth((ts - 0.8) / 1.0) * fade)
            self.blit_center(tx["t2b"], 400, 215, smooth((ts - 2.2) / 1.0) * fade)
            for i, d in enumerate("321"):
                lt = ts - 5.0 - i * 1.0
                if 0 <= lt < 1.0:
                    a = smooth(lt / 0.25) * (1 - smooth((lt - 0.62) / 0.38))
                    self.blit_center(tx["cd" + d], 400, 300, a, lerp(1.35, 1.0, ease_out_cubic(lt / 0.9)))
        elif st == "blow":
            fade_in = smooth(ts / 1.0)
            pulse = 0.6 + 0.4 * math.sin(t * 2.6)
            if self.blow_phase == "holding":
                key = "release" if self.charge >= 0.97 else "keep"
                self.blit_center(tx[key], 400, 1005, 0.6 + 0.4 * math.sin(t * 6) if key == "release" else 0.85)
            elif self.blow_phase == "ready" and self.msg_t < 4.6:
                a = smooth(self.msg_t / 0.3) * (1 - smooth((self.msg_t - 3.8) / 0.8))
                self.blit_center(tx[self.msg], 400, 1005, a)
            elif self.blow_phase == "ready":
                self.blit_center(tx["instr"], 400, 1005, fade_in * pulse)
            # breath meter
            if self.blow_phase != "release":
                x0, x1, y = 250, 550, 1062
                base = 0.35 * fade_in
                pygame.draw.line(scr, scale_col((120, 110, 90), base), (x0, y), (x1, y), 2)
                if self.charge > 0.01:
                    xe = int(lerp(x0, x1, self.charge))
                    pygame.draw.line(scr, (236, 204, 130), (x0, y), (xe, y), 3)
                    self.gl_flame.add(scr, xe, y, 0.7)
        elif st == "reveal":
            if self.revealed:
                tt = ts - 2.3
                self.gl_text.add(scr, 400, 190, 0.25 * smooth(tt / 1.0) * (1 - smooth((ts - 6.8) / 0.8)))
                self.ln_wish.draw(scr, 400, 190, tt, alpha=1 - smooth((ts - 7.0) / 0.6), wave_t=t)
                self.blit_center(tx["sub_wish"], 400, 265, smooth((ts - 3.6) / 1.1) * (1 - smooth((ts - 7.0) / 0.6)))
        elif st == "celebrate":
            fo = 1 - smooth(ts / 0.9)
            if fo > 0.01:
                self.ln_wish.draw(scr, 400, 190, 99, alpha=fo)
                self.blit_center(tx["sub_wish"], 400, 265, fo)
            self.gl_text.add(scr, 400, 995, 0.38 * smooth((ts - 0.3) / 1.2))
            self.ln_happy.draw(scr, 400, 950, ts - 0.5, wave_t=t)
            self.ln_bday.draw(scr, 400, 1035, ts - 0.9, wave_t=t)
            self.blit_center(tx["sub_hb"], 400, 1110, smooth((ts - 2.8) / 1.2))
            if ts > 9.0:
                self.blit_center(tx["replay"], 400, 1148, smooth((ts - 9.0) / 1.0) * (0.5 + 0.5 * math.sin(t * 2.2)))
        if st not in ("celebrate",) or ts < 9.0:
            self.blit_center(tx["footer"], 400, 1176, 0.36)

    # ------------------------------------------------------------------ main loop
    def run(self):
        while True:
            dt = min(self.clock.tick(FPS) / 1000.0, 0.05)
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    return
                if e.type == pygame.KEYDOWN:
                    if e.key == pygame.K_ESCAPE:
                        return
                    elif e.key == pygame.K_f:
                        try:
                            pygame.display.toggle_fullscreen()
                        except pygame.error:
                            pass
                    elif e.key == pygame.K_r:
                        self.reset("intro")
                    elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        self.on_enter()
            self.update(dt)
            self.draw()
            pygame.display.flip()


def main():
    game = Game()
    game.run()
    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
