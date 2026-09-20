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

IMAGE_ID = 0x5A17                 # the drifting light
BACKDROP_ID = 0x5A18              # the city behind it
SPRITE = 192                      # sprite is square, scaled at placement time

# kitty draws z<0 below the text. Below -1073741824 it also goes under the
# cell backgrounds, where the terminal's own background hides it — so both
# of ours sit just above that line, the backdrop under the light.
Z_LIGHT = -1_000_000_000
Z_BACKDROP = -1_050_000_000


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


DIM = 0.42                        # how far the finished backdrop is taken down


def backdrop_rgba(width: int = 640, height: int = 360) -> bytes:
    """A city at night, procedurally: haze, horizon, grid, scanlines, grain.

    Everything here is kept very dark on purpose. This sits under text that
    has to stay readable, so the brightest thing in it is about a sixth of
    full brightness, and the middle of the frame — where the board's columns
    live — is darkened further by the vignette.
    """
    horizon = int(height * 0.62)
    pixels = bytearray()
    for y in range(height):
        # Vertical wash: near-black at the top, a deep violet toward the floor.
        v = y / height
        base_r = 8 + 20 * v
        base_g = 6 + 10 * v
        base_b = 14 + 42 * v

        # A band of neon haze sitting on the horizon, magenta above, cyan below.
        d = abs(y - horizon) / (height * 0.22)
        if d < 1.0:
            haze = (1.0 - d) ** 2
            if y < horizon:
                base_r += 60 * haze
                base_b += 40 * haze
            else:
                base_g += 26 * haze
                base_b += 60 * haze

        for x in range(width):
            r, g, b = base_r, base_g, base_b
            u = x / width

            # Perspective grid below the horizon, converging on the middle.
            if y > horizon:
                depth = (y - horizon) / max(1, height - horizon)
                spacing = 0.02 + depth * 0.16
                offset = (u - 0.5) / max(0.05, depth)
                if abs((offset % spacing) - spacing / 2) < spacing * 0.06:
                    line = (1.0 - depth) * 70
                    r += line * 0.6
                    g += line * 0.2
                    b += line
                # Horizontal rungs, tighter toward the horizon.
                if int(depth * 26) != int(((y - 1) - horizon) /
                                          max(1, height - horizon) * 26):
                    r += 22
                    g += 8
                    b += 34

            # Two slabs of colour, far off, like light off something tall.
            for cx, tint in ((0.18, (46, 8, 30)), (0.83, (6, 30, 44))):
                dx = abs(u - cx)
                if dx < 0.16 and y < horizon:
                    glowing = (1 - dx / 0.16) ** 2 * (1 - y / horizon)
                    r += tint[0] * glowing
                    g += tint[1] * glowing
                    b += tint[2] * glowing

            # Scanlines, and a vignette so the centre stays readable.
            if y % 3 == 0:
                r, g, b = r * 0.72, g * 0.72, b * 0.72
            vignette = 1.0 - 0.55 * ((u - 0.5) ** 2 + (y / height - 0.5) ** 2) * 2
            r, g, b = r * vignette, g * vignette, b * vignette

            # Everything above is composed at a comfortable brightness and
            # then taken right down. Text has to win against this, and a
            # backdrop you can read the board over is the only kind worth
            # having — the peak here lands around a seventh of full.
            r, g, b = r * DIM, g * DIM, b * DIM
            pixels += bytes((max(0, min(255, int(r))),
                             max(0, min(255, int(g))),
                             max(0, min(255, int(b))), 255))
    return bytes(pixels)


class KittyGlow:
    """Transmit once, then move it."""

    def __init__(self, fd: int | None = None):
        self.fd = fd if fd is not None else sys.__stdout__.fileno()
        self.sent = False
        self.placed = False
        self.backdrop_size: tuple[int, int] | None = None

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
            f"a=p,i={IMAGE_ID},z={Z_LIGHT},c={cols},r={rows},C=1,q=2"))
        self.placed = True

    def backdrop(self, cols: int, rows: int) -> None:
        """Lay the city behind everything. Sent once, re-placed on resize."""
        if self.backdrop_size == (cols, rows):
            return
        if self.backdrop_size is None:
            blob = base64.b64encode(zlib.compress(backdrop_rgba(), 6))
            chunks = [blob[i:i + 4096] for i in range(0, len(blob), 4096)]
            for index, chunk in enumerate(chunks):
                last = index == len(chunks) - 1
                control = (f"a=t,i={BACKDROP_ID},f=32,s=640,v=360,o=z,q=2,"
                           f"m={0 if last else 1}") if index == 0 else \
                          f"m={0 if last else 1},q=2"
                self._write(self._cmd(control, chunk))
        else:
            self._write(self._cmd(f"a=d,d=i,i={BACKDROP_ID},q=2"))
        self._write(b"\033[1;1H")
        self._write(self._cmd(
            f"a=p,i={BACKDROP_ID},z={Z_BACKDROP},c={cols},r={rows},C=1,q=2"))
        self.backdrop_size = (cols, rows)

    def clear(self) -> None:
        if self.placed or self.sent:
            self._write(self._cmd(f"a=d,d=i,i={IMAGE_ID},q=2"))
            self.placed = False

    def forget(self) -> None:
        """Delete both images entirely — on the way out."""
        self.clear()
        if self.sent:
            self._write(self._cmd(f"a=d,d=I,i={IMAGE_ID},q=2"))
            self.sent = False
        if self.backdrop_size is not None:
            self._write(self._cmd(f"a=d,d=I,i={BACKDROP_ID},q=2"))
            self.backdrop_size = None
