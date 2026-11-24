"""Execução de mouse e teclado.

PyAutoGUI move, clica e pressiona teclas; o texto é digitado com pynput
(SendInput Unicode), que aceita acentos e qualquer caractere; a roda do mouse
usa mouse_event direto porque o PyAutoGUI não faz rolagem horizontal no Windows.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import sys
from typing import Protocol

BUTTONS = ("left", "right", "middle")

# nomes de tecla aceitos (padrão PyAutoGUI)
SPECIAL_KEYS = [
    "enter", "esc", "tab", "space", "backspace", "delete", "insert", "home", "end",
    "pageup", "pagedown", "up", "down", "left", "right", "capslock", "numlock",
    "scrolllock", "printscreen", "pause", "ctrl", "ctrlleft", "ctrlright", "shift",
    "shiftleft", "shiftright", "alt", "altleft", "altright", "win", "winleft",
    "winright", "apps", "volumeup", "volumedown", "volumemute", "playpause",
    "nexttrack", "prevtrack",
    *[f"f{i}" for i in range(1, 25)],
    *[f"num{i}" for i in range(10)],
    "multiply", "add", "subtract", "decimal", "divide",
]
KEY_ALIASES = {
    "control": "ctrl", "return": "enter", "escape": "esc", "del": "delete", "ins": "insert",
    "pgup": "pageup", "pgdn": "pagedown", "pagedn": "pagedown", "windows": "win", "cmd": "win",
    "super": "win", "menu": "apps", "espaco": "space", "espaço": "space", "seta_cima": "up",
    "seta_baixo": "down", "seta_esquerda": "left", "seta_direita": "right", "prtsc": "printscreen",
}


def normalize_key(name: str) -> str:
    k = (name or "").strip().lower()
    k = KEY_ALIASES.get(k, k)
    if len(k) == 1 or k in SPECIAL_KEYS:
        return k
    raise ValueError(f"Tecla desconhecida: '{name}'")


def parse_combo(text: str) -> list[str]:
    parts = [p for p in (text or "").replace(" ", "").split("+") if p]
    if not parts:
        raise ValueError("Combinação vazia")
    return [normalize_key(p) for p in parts]


class InputBackend(Protocol):
    def position(self) -> tuple[int, int]: ...
    def move(self, x: int, y: int) -> None: ...
    def down(self, button: str) -> None: ...
    def up(self, button: str) -> None: ...
    def click(self, button: str, clicks: int = 1) -> None: ...
    def scroll(self, vertical: int, horizontal: int) -> None: ...
    def key_down(self, key: str) -> None: ...
    def key_up(self, key: str) -> None: ...
    def type_char(self, ch: str) -> None: ...


class PyAutoGuiBackend:
    def __init__(self, failsafe: bool = False):
        import pyautogui
        from pynput.keyboard import Controller

        pyautogui.PAUSE = 0
        pyautogui.MINIMUM_DURATION = 0
        pyautogui.FAILSAFE = failsafe  # canto superior esquerdo aborta, se ligado
        self.pg = pyautogui
        self.kb = Controller()

    def position(self) -> tuple[int, int]:
        if sys.platform == "win32":
            pt = ctypes.wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            return pt.x, pt.y
        p = self.pg.position()
        return int(p[0]), int(p[1])

    def move(self, x: int, y: int) -> None:
        if sys.platform == "win32":
            # SetCursorPos aceita coordenadas negativas (monitores à esquerda/acima)
            ctypes.windll.user32.SetCursorPos(int(x), int(y))
        else:
            self.pg.moveTo(int(x), int(y), _pause=False)

    def down(self, button: str) -> None:
        self.pg.mouseDown(button=button, _pause=False)

    def up(self, button: str) -> None:
        self.pg.mouseUp(button=button, _pause=False)

    def click(self, button: str, clicks: int = 1) -> None:
        self.pg.click(button=button, clicks=max(1, int(clicks)), interval=0.05, _pause=False)

    def scroll(self, vertical: int, horizontal: int) -> None:
        if sys.platform != "win32":
            if vertical:
                self.pg.scroll(vertical)
            if horizontal:
                self.pg.hscroll(horizontal)
            return
        MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL, WHEEL_DELTA = 0x0800, 0x01000, 120
        if vertical:
            ctypes.windll.user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, ctypes.c_ulong(int(vertical) * WHEEL_DELTA & 0xFFFFFFFF), 0)
        if horizontal:
            ctypes.windll.user32.mouse_event(MOUSEEVENTF_HWHEEL, 0, 0, ctypes.c_ulong(int(horizontal) * WHEEL_DELTA & 0xFFFFFFFF), 0)

    def key_down(self, key: str) -> None:
        self.pg.keyDown(key, _pause=False)

    def key_up(self, key: str) -> None:
        self.pg.keyUp(key, _pause=False)

    def type_char(self, ch: str) -> None:
        if ch == "\n":
            self.pg.press("enter", _pause=False)
        elif ch == "\t":
            self.pg.press("tab", _pause=False)
        else:
            self.kb.type(ch)
