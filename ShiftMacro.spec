# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: gera dist/ShiftMacro/ShiftMacro.exe (pasta única, abre rápido).
from pathlib import Path

root = Path(SPECPATH)

# módulos do Qt que o app não usa (reduz bastante o tamanho)
qt_excludes = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DExtras",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQml", "PySide6.QtQuickWidgets", "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtNetworkAuth", "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtLocation",
    "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner",
    "PySide6.QtHelp", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtRemoteObjects",
    "PySide6.QtScxml", "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech", "PySide6.QtHttpServer",
    "PySide6.QtWebSockets", "PySide6.QtNfc", "PySide6.QtStateMachine", "PySide6.QtUiTools",
]

a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / "assets" / "shiftmacro.ico"), "assets")],
    hiddenimports=[
        "pynput.keyboard._win32", "pynput.mouse._win32", "pynput._util.win32",
        "PySide6.QtSvg",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=qt_excludes + ["tkinter", "matplotlib", "pytest", "IPython", "PIL"],
    noarchive=False,
)
# binários que entram por dependência mas o app não usa: codec de vídeo do OpenCV,
# OpenGL por software (só widgets) e Qt Quick/QML/PDF puxados por plugins
_drop = ("opencv_videoio_ffmpeg", "opengl32sw", "qt6quick", "qt6qml", "qt6pdf", "qtvirtualkeyboard",
         "qpdf", "qt6virtualkeyboard")
a.binaries = [b for b in a.binaries if not any(d in b[0].lower().replace("\\", "/").split("/")[-1] for d in _drop)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ShiftMacro",
    icon=str(root / "assets" / "shiftmacro.ico"),
    console=False,
    disable_windowed_traceback=False,
    version=str(root / "assets" / "version.txt"),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ShiftMacro")
