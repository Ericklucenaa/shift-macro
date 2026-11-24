"""Integração com mouse, teclado e tela de verdade.

MOVE O MOUSE E DIGITA. Só roda com SHIFTMACRO_REAL_INPUT=1:
    set SHIFTMACRO_REAL_INPUT=1 && python -m pytest tests/test_real_input.py -s

Abre uma janela de teste por cima de tudo e verifica, com o sistema real:
- Smart Click encontra a imagem na tela e clica nela (PyAutoGUI + OpenCV + MSS);
- Digitar texto com acentos chega no campo (pynput);
- F8 de verdade (RegisterHotKey) para um loop infinito;
- a gravação (ganchos do pynput) capta clique e texto e vira etapas.
"""
from __future__ import annotations

import os
import threading
import time

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(os.environ.get("SHIFTMACRO_REAL_INPUT") != "1", reason="move o mouse; ligue com SHIFTMACRO_REAL_INPUT=1")


@pytest.fixture(scope="module")
def env():
    from shiftmacro.utils.winapi import ensure_dpi_aware

    ensure_dpi_aware()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QVBoxLayout, QWidget

    from shiftmacro.actions.inputs import PyAutoGuiBackend
    from shiftmacro.ui.overlay import to_qimage
    from shiftmacro.vision import matcher

    app = QApplication.instance() or QApplication([])
    rng = np.random.default_rng(11)
    tile = rng.integers(0, 255, size=(48, 120, 3), dtype=np.uint8)
    tile[:6] = (0, 140, 255)

    class Win(QWidget):
        def __init__(self):
            super().__init__(None, Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
            self.clicks = 0
            self.setStyleSheet("background:#202226; color:white;")
            lay = QVBoxLayout(self)
            self.target = QLabel()
            self.target.setPixmap(QPixmap.fromImage(to_qimage(tile)))
            self.target.setFixedSize(120, 48)
            self.target.mousePressEvent = lambda e: setattr(self, "clicks", self.clicks + 1)
            self.edit = QLineEdit()
            self.edit.setFixedWidth(300)
            lay.addWidget(self.target)
            lay.addSpacing(20)
            lay.addWidget(self.edit)

    w = Win()
    w.move(300, 300)
    w.show()
    w.raise_()
    w.activateWindow()
    pump(app, 0.6)
    inputs = PyAutoGuiBackend()
    start_pos = inputs.position()
    yield app, w, inputs, {"alvo": matcher.encode_png(tile)}
    inputs.move(*start_pos)
    w.close()


def pump(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def run_engine(app, engine, timeout=10.0, **kw):
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("r", engine.run(**kw)))
    t.start()
    end = time.time() + timeout
    while t.is_alive() and time.time() < end:
        pump(app, 0.02)
    t.join(0.1)
    return out.get("r")


def test_smart_click_e_digitar_de_verdade(env):
    from shiftmacro.actions.registry import make
    from shiftmacro.core.engine import Engine
    from shiftmacro.core.model import Macro

    app, w, inputs, images = env
    m = Macro(images=images, commands=[
        make("smart_click", image="alvo", threshold=90, timeout_ms=3000, on_found="left", on_not_found="stop"),
        make("delay", ms=150),
        # o campo de texto está ~60 px abaixo do centro do alvo
        make("smart_click", image="alvo", threshold=90, timeout_ms=3000, on_found="offset", offset_x=0, offset_y=62),
        make("type_text", text="Olá, ação {repeticao}", interval_ms=5),
    ])
    r = run_engine(app, Engine(m, inputs))
    pump(app, 0.3)
    assert r and r.completed, r.error if r else "sem resultado"
    assert w.clicks == 1
    assert w.edit.text() == "Olá, ação 1"


def test_f8_de_verdade_para_loop_infinito(env):
    import pyautogui

    from shiftmacro.actions.registry import make
    from shiftmacro.core.engine import Engine
    from shiftmacro.core.model import Macro
    from shiftmacro.utils.winapi import GlobalHotkeys

    app, w, inputs, images = env
    eng = Engine(Macro(commands=[make("loop", count="0"), make("delay", ms=50), make("end_loop")]), inputs)
    hk = GlobalHotkeys(lambda a: eng.stop() if a == "stop" else None)
    assert hk.start({"stop": "F8"}) == {}
    try:
        threading.Timer(0.5, lambda: pyautogui.press("f8")).start()
        t0 = time.time()
        r = run_engine(app, eng, timeout=5)
        assert r is not None and r.stopped
        assert time.time() - t0 < 1.5
    finally:
        hk.stop()


def test_gravacao_de_verdade(env):
    import pyautogui

    from shiftmacro.recorder.convert import convert
    from shiftmacro.recorder.recorder import Recorder

    app, w, inputs, images = env
    w.edit.clear()
    rec = Recorder(mode="all")
    rec.start()
    pump(app, 0.3)
    c = w.edit.mapToGlobal(w.edit.rect().center())
    # coordenadas lógicas -> físicas
    dpr = w.edit.devicePixelRatioF()
    x, y = int(c.x() * dpr), int(c.y() * dpr)
    inputs.move(x, y)
    pyautogui.click()
    pump(app, 0.2)
    pyautogui.write("abc", interval=0.05)
    pump(app, 0.3)
    events = rec.stop()
    cmds = convert(events, mode="all", record_moves=False)
    types = [c.type for c in cmds]
    assert "left_click" in types, types
    assert any(c.type == "type_text" and c.params["text"] == "abc" for c in cmds), [(c.type, c.params) for c in cmds]
    click = next(c for c in cmds if c.type == "left_click")
    assert abs(click.params["x"] - x) <= 2 and abs(click.params["y"] - y) <= 2
