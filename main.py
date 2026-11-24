"""Shift Macro Recorder — inicialização.

Uso:
    python main.py [arquivo.shiftmacro]
    python main.py --run arquivo.shiftmacro      (executa sem abrir a janela; F8 para parar)
"""
from __future__ import annotations

import os
import sys


def _run_headless(path: str) -> int:
    """Executa uma macro pelo terminal (útil em agendadores de tarefa)."""
    from shiftmacro.actions.inputs import PyAutoGuiBackend
    from shiftmacro.core.engine import Engine, Listener
    from shiftmacro.storage.appdata import AppSettings
    from shiftmacro.storage.project import load_macro
    from shiftmacro.utils.winapi import GlobalHotkeys

    macro = load_macro(path)
    settings = AppSettings.load()

    class Printer(Listener):
        def on_log(self, e):
            if e.level in ("warn", "error", "ok") or e.step is None:
                step = f"[{e.step + 1}] " if e.step is not None else ""
                print(f"{e.level.upper():5} {step}{e.message}", flush=True)

    from pathlib import Path

    eng = Engine(macro, PyAutoGuiBackend(failsafe=settings.failsafe), listener=Printer(), base_dir=Path(path).resolve().parent)
    hk = GlobalHotkeys(lambda a: eng.stop() if a == "stop" else eng.toggle_pause() if a == "pause" else None)
    hk.start({"stop": settings.hotkeys.get("stop", "F8"), "pause": settings.hotkeys.get("pause", "F7")})
    try:
        res = eng.run()
    except KeyboardInterrupt:
        eng.stop()
        return 130
    finally:
        hk.stop()
    return 0 if res.completed else 1


def main() -> int:
    from shiftmacro.utils.winapi import ensure_dpi_aware

    ensure_dpi_aware()  # antes de qualquer janela: coordenadas físicas em todos os monitores
    args = sys.argv[1:]
    if args and args[0] == "--run" and len(args) > 1:
        return _run_headless(args[1])

    os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.window=false")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from shiftmacro import APP_NAME
    from shiftmacro.storage.appdata import AppSettings
    from shiftmacro.ui import icons, theme
    from shiftmacro.ui.main_window import MainWindow

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Shift")
    app.setQuitOnLastWindowClosed(False)  # a bandeja mantém o app; Sair fecha de verdade
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Shift.MacroRecorder")
    settings = AppSettings.load()
    theme.apply(app, settings.theme)
    app.setWindowIcon(icons.app_icon())
    path = next((a for a in args if not a.startswith("-")), None)
    win = MainWindow(settings, path)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
