"""A real light, for terminals that can draw one.

kitty can composite images into the grid, so the ambient glow does not have
to be made of characters: it is an actual RGBA sprite with a smooth falloff,
placed *below* the text layer and moved around. Everywhere else this is
unavailable and the board falls back to tinting empty cells, which is the
best a character grid can do.

The sprite is sent once, compressed, and then only moved — a placement costs
a few dozen bytes, where re-sending the pixels would cost a megabyte a frame.
"""

from __future__ import annotations

import base64
import math
import os
import sys
import zlib

# One id per light. They live at the left and right edges and never cross
# the middle, where everything you actually read is.
EDGE_IDS = {"left": 0x5A19, "right": 0x5A1A}
EDGE_COLOURS = {"left": (255, 43, 214), "right": (0, 200, 255)}
EDGE_SIZE = 96                    # sprite is EDGE_SIZE x EDGE_SIZE*2
SPRITE = 192                      # sprite is square, scaled at placement time

# kitty draws z<0 below the text. Below -1073741824 it also goes under the
# cell backgrounds, where the terminal's own background hides it — so both
# of ours sit just above that line, the backdrop under the light.
Z_LIGHT = -1_000_000_000


def supported() -> bool:
    """Is this a terminal that can draw an image behind the text?"""
    if os.environ.get("SPACE_NO_GRAPHICS"):
        return False
    if os.environ.get("KITTY_WINDOW_ID"):
        return True
    return "kitty" in os.environ.get("TERM", "").lower()


def sprite_rgba(size: int = SPRITE) -> bytes:
    """A round blue light: bright core, long soft falloff, transparent edge.

    The alpha curve is what sells it. A linear ramp reads as a flat disc with
    a hard rim; this is smoothstep cubed, which is close enough to how light
    actually falls off that the eye stops seeing an edge at all.
    """
    out = bytearray()
    centre = (size - 1) / 2
    for y in range(size):
        dy = (y - centre) / centre
        for x in range(size):
            dx = (x - centre) / centre
            dist = math.sqrt(dx * dx + dy * dy)
            if dist >= 1.0:
                out += b"\0\0\0\0"
                continue
            t = 1.0 - dist
            smooth = t * t * (3 - 2 * t)          # smoothstep
            alpha = smooth ** 3
            # Cooler at the rim, whiter in the core, the way a real source
            # looks through anything at all.
            core = smooth ** 6
            r = int(30 + 150 * core)
            g = int(70 + 165 * core)
            b = int(190 + 65 * core)
            out += bytes((r, g, b, int(alpha * 235)))
    return bytes(out)


def half_orb_rgba(size: int, rgb: tuple[int, int, int], side: str) -> bytes:
    """Half a soft light, flat edge against the screen edge.

    Generated as a half rather than cropped at placement time, so it can sit
    at column zero with its centre effectively off-screen: only the falloff
    shows, which is what makes it read as light coming in from outside the
    window rather than a ball sitting in the corner.
    """
    width, height = size, size * 2
    centre_y = (height - 1) / 2
    centre_x = -0.5 if side == "left" else width - 0.5
    reach = float(width)
    out = bytearray()
    for y in range(height):
        dy = (y - centre_y) / (height / 2)
        for x in range(width):
            dx = (x - centre_x) / reach
            dist = math.sqrt(dx * dx + dy * dy)
            if dist >= 1.0:
                out += b"\0\0\0\0"
                continue
            t = 1.0 - dist
            smooth = t * t * (3 - 2 * t)
            alpha = smooth ** 2.2 * 190
            core = smooth ** 5
            out += bytes((min(255, int(rgb[0] * (0.55 + 0.45 * core))),
                          min(255, int(rgb[1] * (0.55 + 0.45 * core))),
                          min(255, int(rgb[2] * (0.55 + 0.45 * core))),
                          int(alpha)))
    return bytes(out)


class KittyGlow:
    """Two lights at the edges. Transmit once each, then only move them."""

    def __init__(self, fd: int | None = None):
        self.fd = fd if fd is not None else sys.__stdout__.fileno()
        self.sent: set[str] = set()
        self.placed: set[str] = set()

    def _write(self, payload: bytes) -> None:
        try:
            os.write(self.fd, payload)
        except OSError:
            pass

    def _cmd(self, control: str, data: bytes = b"") -> bytes:
        return b"\033_G" + control.encode() + (b";" + data if data else b"") + b"\033\\"

    def send(self, side: str) -> None:
        if side in self.sent:
            return
        image = half_orb_rgba(EDGE_SIZE, EDGE_COLOURS[side], side)
        blob = base64.b64encode(zlib.compress(image, 6))
        chunks = [blob[i:i + 4096] for i in range(0, len(blob), 4096)] or [b""]
        for index, chunk in enumerate(chunks):
            last = index == len(chunks) - 1
            control = (f"a=t,i={EDGE_IDS[side]},f=32,s={EDGE_SIZE},"
                       f"v={EDGE_SIZE * 2},o=z,q=2,m={0 if last else 1}") \
                if index == 0 else f"m={0 if last else 1},q=2"
            self._write(self._cmd(control, chunk))
        self.sent.add(side)

    def move(self, side: str, row: int, col: int, cols: int, rows: int) -> None:
        self.send(side)
        self.clear(side)
        self._write(f"\033[{row + 1};{col + 1}H".encode())
        self._write(self._cmd(
            f"a=p,i={EDGE_IDS[side]},z={Z_LIGHT},c={cols},r={rows},C=1,q=2"))
        self.placed.add(side)

    def clear(self, side: str | None = None) -> None:
        for name in ([side] if side else list(self.placed)):
            if name in self.placed:
                self._write(self._cmd(f"a=d,d=i,i={EDGE_IDS[name]},q=2"))
                self.placed.discard(name)

    def forget(self) -> None:
        self.clear()
        for side in list(self.sent):
            self._write(self._cmd(f"a=d,d=I,i={EDGE_IDS[side]},q=2"))
            self.sent.discard(side)
