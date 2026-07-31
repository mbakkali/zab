#!/usr/bin/env python3
"""Génère les icônes PNG de la PWA de contrôle sans dépendance externe.

iOS n'accepte pas de SVG pour `apple-touch-icon`, et le manifeste demande des
PNG carrés. Plutôt que d'ajouter Pillow au projet pour trois images figées, on
écrit directement le PNG : un fond arrondi et un symbole d'alimentation.

Usage : `python3 scripts/gen_pwa_icons.py` depuis la racine du dépôt.
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "zab" / "pwa" / "icons"

BACKGROUND = (11, 11, 12)
ACCENT = (16, 185, 129)
SIZES = {"icon-192.png": 192, "icon-512.png": 512, "apple-touch-icon.png": 180}

# Le fond de l'icône iOS est déjà masqué par le système : le rayon d'arrondi
# n'est appliqué que pour les autres plateformes.
ROUNDED = {"icon-192.png", "icon-512.png"}


def _coverage(distance: float, edge: float) -> float:
    """Anticrénelage : fraction du pixel couverte à `distance` du bord `edge`."""
    return min(1.0, max(0.0, edge - distance + 0.5))


def _mix(base: tuple[int, int, int], top: tuple[int, int, int], alpha: float) -> tuple[int, int, int]:
    return (
        round(base[0] + (top[0] - base[0]) * alpha),
        round(base[1] + (top[1] - base[1]) * alpha),
        round(base[2] + (top[2] - base[2]) * alpha),
    )


def _render(size: int, *, rounded: bool) -> bytearray:
    center = (size - 1) / 2
    corner_radius = size * 0.22
    ring_radius = size * 0.30
    ring_width = size * 0.085
    bar_half_width = ring_width / 2
    bar_top = center - size * 0.40
    bar_bottom = center - size * 0.06
    # Ouverture du haut de l'anneau, pour laisser passer la barre.
    gap_half_angle = math.radians(38)

    rows = bytearray()
    for y in range(size):
        rows.append(0)  # filtre PNG « None »
        for x in range(size):
            colour = BACKGROUND
            alpha_bg = 1.0
            if rounded:
                # Distance au rectangle arrondi, pour un bord net mais lissé.
                dx = abs(x - center) - (size / 2 - corner_radius)
                dy = abs(y - center) - (size / 2 - corner_radius)
                if dx > 0 and dy > 0:
                    alpha_bg = _coverage(math.hypot(dx, dy), corner_radius)

            dx = x - center
            dy = y - center
            distance = math.hypot(dx, dy)
            # Angle mesuré depuis le haut, pour situer l'ouverture.
            angle = abs(math.atan2(dx, -dy))
            on_ring = 0.0
            if angle > gap_half_angle:
                on_ring = _coverage(abs(distance - ring_radius), ring_width / 2)

            on_bar = 0.0
            if bar_top <= y <= bar_bottom:
                on_bar = _coverage(abs(dx), bar_half_width)
                if y < bar_top + 1:
                    on_bar *= _coverage(bar_top - y, 1.0)

            mark = max(on_ring, on_bar)
            if mark > 0:
                colour = _mix(colour, ACCENT, mark)

            if alpha_bg >= 1.0:
                rows.extend(colour)
                rows.append(255)
            else:
                rows.extend(colour)
                rows.append(round(255 * alpha_bg))
    return rows


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    )


def write_png(path: Path, size: int, *, rounded: bool) -> None:
    raw = _render(size, rounded=rounded)
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # RGBA 8 bits
    data = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _chunk(b"IEND", b"")
    )
    path.write_bytes(data)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, size in SIZES.items():
        write_png(OUT_DIR / name, size, rounded=name in ROUNDED)
        print(f"{name}: {size}x{size}")


if __name__ == "__main__":
    main()
