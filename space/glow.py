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

IMAGE_ID = 0x5A17                 # any stable id; ours alone
SPRITE = 192                      # sprite is square, scaled at placement time

# Below the text *and* below cell backgrounds, so nothing occludes it.
Z_BELOW_EVERYTHING = -1_000_000_000


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


class KittyGlow:
    """Transmit once, then move it."""

    def __init__(self, fd: int | None = None):
        self.fd = fd if fd is not None else sys.__stdout__.fileno()
        self.sent = False
        self.placed = False

    def _write(self, payload: bytes) -> None:
        try:
            os.write(self.fd, payload)
        except OSError:
            pass

    def _cmd(self, control: str, data: bytes = b"") -> bytes:
        return b"\033_G" + control.encode() + (b";" + data if data else b"") + b"\033\\"

    def send(self) -> None:
        """Hand the pixels over once, zlib-compressed and chunked."""
        if self.sent:
            return
        blob = base64.b64encode(zlib.compress(sprite_rgba(), 6))
        chunks = [blob[i:i + 4096] for i in range(0, len(blob), 4096)] or [b""]
        for index, chunk in enumerate(chunks):
            first, last = index == 0, index == len(chunks) - 1
            control = (f"a=t,i={IMAGE_ID},f=32,s={SPRITE},v={SPRITE},o=z,"
                       f"q=2,m={0 if last else 1}") if first else \
                      f"m={0 if last else 1},q=2"
            self._write(self._cmd(control, chunk))
        self.sent = True

    def move(self, row: int, col: int, cols: int, rows: int) -> None:
        """Put the light at a cell, scaled to cover `cols` x `rows` cells."""
        self.send()
        self.clear()
        # Position the cursor without curses' knowledge, place with C=1 so the
        # cursor is left where it was.
        self._write(f"\033[{row + 1};{col + 1}H".encode())
        self._write(self._cmd(
            f"a=p,i={IMAGE_ID},z={Z_BELOW_EVERYTHING},c={cols},r={rows},"
            f"C=1,q=2"))
        self.placed = True

    def clear(self) -> None:
        if self.placed or self.sent:
            self._write(self._cmd(f"a=d,d=i,i={IMAGE_ID},q=2"))
            self.placed = False

    def forget(self) -> None:
        """Delete the image entirely — on the way out."""
        self.clear()
        if self.sent:
            self._write(self._cmd(f"a=d,d=I,i={IMAGE_ID},q=2"))
            self.sent = False
