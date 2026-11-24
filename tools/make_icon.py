"""Gera assets/shiftmacro.ico (16 a 256 px, entradas PNG) a partir do ícone vetorial do app."""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def main() -> None:
    app = QApplication.instance() or QApplication([])  # noqa: F841
    from shiftmacro.ui import icons

    ic = icons.app_icon()
    sizes = [16, 24, 32, 48, 64, 128, 256]
    pngs = []
    for s in sizes:
        pm = ic.pixmap(s, s)
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        pm.save(buf, "PNG")
        pngs.append(bytes(ba))
    out = ROOT / "assets"
    out.mkdir(exist_ok=True)
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries, data = b"", b""
    for s, png in zip(sizes, pngs):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(png), offset + len(data))
        data += png
    (out / "shiftmacro.ico").write_bytes(header + entries + data)
    (out / "shiftmacro.png").write_bytes(pngs[-1])
    print("Ícone gerado em", out / "shiftmacro.ico")


if __name__ == "__main__":
    main()
