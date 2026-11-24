"""Verificação e instalação de atualizações (interface)."""
from __future__ import annotations

import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QTextBrowser, QVBoxLayout,
)

from .. import APP_NAME, __version__
from ..utils import updater
from . import theme


class _Signals(QObject):
    checked = Signal(object, object)  # Release | None, erro | None
    progress = Signal(int, int)
    downloaded = Signal(object, object)  # caminho | None, erro | None


def check_async(callback) -> None:
    """Consulta o GitHub numa thread e chama `callback(release, erro)` na thread do Qt."""
    sig = _Signals()

    def work():
        try:
            sig.checked.emit(updater.check(__version__), None)
        except updater.UpdateError as e:
            sig.checked.emit(None, str(e))
        except Exception as e:  # nunca derrubar o app por causa da verificação
            sig.checked.emit(None, f"{type(e).__name__}: {e}")

    sig.checked.connect(lambda r, e: (callback(r, e), sig.deleteLater()))
    threading.Thread(target=work, name="update-check", daemon=True).start()


class UpdateDialog(QDialog):
    """Mostra a versão nova, as notas e baixa/instala."""

    def __init__(self, rel: updater.Release, parent=None):
        super().__init__(parent)
        self.rel = rel
        self.skip_requested = False
        self.ready_zip: Path | None = None
        self._cancel = False
        self.sig = _Signals()
        self.sig.progress.connect(self._on_progress)
        self.sig.downloaded.connect(self._on_downloaded)
        self.setWindowTitle("Atualização disponível")
        t = theme.current()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 14)
        lay.setSpacing(10)
        title = QLabel(f"Shift Macro {rel.version} está disponível")
        f = title.font()
        f.setPointSizeF(f.pointSizeF() + 3)
        f.setWeight(f.Weight.DemiBold)
        title.setFont(f)
        lay.addWidget(title)
        sub = QLabel(f"Você está usando a versão {__version__}.")
        sub.setObjectName("muted")
        lay.addWidget(sub)
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(rel.notes or "_Sem notas para esta versão._")
        notes.setStyleSheet(f"QTextBrowser {{ background:{t.panel}; border:1px solid {t.line}; border-radius:4px; padding:8px; }}")
        lay.addWidget(notes, 1)
        self.bar = QProgressBar()
        self.bar.setTextVisible(True)
        self.bar.hide()
        lay.addWidget(self.bar)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        row = QHBoxLayout()
        self.b_skip = QPushButton("Pular esta versão")
        self.b_skip.setProperty("flat", True)
        self.b_skip.clicked.connect(self._skip)
        self.b_page = QPushButton("Ver no GitHub")
        self.b_page.setProperty("flat", True)
        self.b_page.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(rel.url)))
        self.b_later = QPushButton("Depois")
        self.b_later.clicked.connect(self._later)
        self.b_install = QPushButton("Baixar e instalar")
        self.b_install.setDefault(True)
        self.b_install.clicked.connect(self._start)
        if updater.app_dir() is None:
            # rodando pelo código-fonte: não há pasta de executável para trocar
            self.b_install.setText("Abrir a página de download")
            self.b_install.clicked.disconnect()
            self.b_install.clicked.connect(lambda: (QDesktopServices.openUrl(QUrl(rel.url)), self.reject()))
        row.addWidget(self.b_skip)
        row.addWidget(self.b_page)
        row.addStretch(1)
        row.addWidget(self.b_later)
        row.addWidget(self.b_install)
        lay.addLayout(row)
        self.resize(560, 460)

    def _skip(self):
        self.skip_requested = True
        self.reject()

    def _later(self):
        self._cancel = True
        self.reject()

    def _start(self):
        self.b_install.setEnabled(False)
        self.b_skip.setEnabled(False)
        self.b_later.setText("Cancelar")
        self.bar.show()
        self.bar.setRange(0, 0)
        self.status.setText("Baixando…")
        dest = Path(tempfile.gettempdir()) / "shiftmacro-update"

        def work():
            try:
                p = updater.download(self.rel, dest, progress=lambda d, t: self.sig.progress.emit(d, t),
                                     cancelled=lambda: self._cancel)
                self.sig.downloaded.emit(p, None)
            except updater.UpdateError as e:
                self.sig.downloaded.emit(None, str(e))
            except Exception as e:
                self.sig.downloaded.emit(None, f"{type(e).__name__}: {e}")

        threading.Thread(target=work, name="update-download", daemon=True).start()

    def _on_progress(self, done: int, total: int):
        if total > 0:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(done * 1000 / total))
            self.bar.setFormat(f"{done / 1e6:.1f} de {total / 1e6:.1f} MB".replace(".", ","))
        else:
            self.bar.setFormat(f"{done / 1e6:.1f} MB".replace(".", ","))

    def _on_downloaded(self, path, error):
        if self._cancel:
            return
        if error:
            self.bar.hide()
            self.status.setText(f"<span style='color:{theme.current().error}'>{error}</span>")
            self.b_install.setEnabled(True)
            self.b_install.setText("Tentar de novo")
            self.b_skip.setEnabled(True)
            self.b_later.setText("Depois")
            return
        self.ready_zip = path
        self.status.setText("Download conferido. O Shift Macro vai fechar, atualizar e abrir de novo.")
        self.accept()


def run_check(window, manual: bool) -> None:
    """Verifica e, se houver versão nova, oferece instalar. `manual` mostra o
    resultado mesmo quando não há novidade ou quando a consulta falha."""
    s = window.settings

    def done(rel, err):
        if err:
            if manual:
                QMessageBox.information(window, "Atualizações", f"Não foi possível verificar agora: {err}")
            return
        if rel is None:
            if manual:
                QMessageBox.information(window, "Atualizações", f"Você já tem a versão mais recente ({__version__}).")
            return
        if not manual and rel.version == s.update_skip:
            return
        if window.is_running() or window.is_recording():
            window.statusBar().showMessage(f"Versão {rel.version} disponível: Ajuda > Verificar atualizações.", 15000)
            return
        d = UpdateDialog(rel, window)
        accepted = d.exec() == QDialog.DialogCode.Accepted
        if d.skip_requested:
            s.update_skip = rel.version
            s.save()
        if accepted and d.ready_zip:
            if not window._confirm_discard():
                return
            try:
                updater.apply_update(d.ready_zip)
            except updater.UpdateError as e:
                QMessageBox.warning(window, APP_NAME, str(e))
                return
            window.dirty = False
            window.close()

    check_async(done)
