"""Comportamento da janela principal (Qt sem tela: plataforma offscreen)."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from shiftmacro.actions.registry import make  # noqa: E402
from shiftmacro.core.model import Macro  # noqa: E402
from shiftmacro.storage import appdata  # noqa: E402
from shiftmacro.storage.project import load_macro  # noqa: E402


@pytest.fixture()
def win(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTMACRO_HOME", str(tmp_path / "home"))
    app = QApplication.instance() or QApplication([])
    from shiftmacro.ui import theme
    from shiftmacro.ui.main_window import MainWindow

    theme.apply(app, "dark")
    w = MainWindow(appdata.AppSettings.load())
    w.hotkeys.stop()
    m = Macro(name="Teste", commands=[make("type_text", text=t) for t in "abcde"])
    w._set_macro(m, None)
    yield w
    w.dirty = False
    w.hotkeys.stop()
    w.close()
    w.tray.hide()
    w.deleteLater()
    QApplication.processEvents()


def texts(w):
    return "".join(c.params.get("text", "|") if c.type == "type_text" else f"[{c.type}]" for c in w.macro.commands)


def test_duplicar_excluir_desfazer_refazer(win):
    win.select_rows([1, 2])
    win.duplicate()
    assert texts(win) == "abcbcde"
    assert win.selected_rows() == [3, 4]
    win.delete_selected()
    assert texts(win) == "abcde"
    win.undo()
    assert texts(win) == "abcbcde"
    win.undo()
    assert texts(win) == "abcde"
    win.redo()
    assert texts(win) == "abcbcde"
    assert win.dirty


def test_mover_e_arrastar(win):
    win.select_rows([0])
    win.move_selected(1)
    assert texts(win) == "bacde"
    win.move_rows([0, 1], 5)  # arrastar as duas primeiras para o fim
    assert texts(win) == "cdeba"
    assert win.selected_rows() == [3, 4]
    win.move_rows([4], 0)
    assert texts(win) == "acdeb"


def test_ativar_desativar_e_delay_em_lote(win):
    win.select_rows([0, 1])
    win.toggle_selected()
    assert [c.enabled for c in win.macro.commands] == [False, False, True, True, True]
    win._delay_edited(0, 250)
    assert [c.delay_ms for c in win.macro.commands[:3]] == [250, 250, 0]
    win.undo()
    win.undo()
    assert all(c.enabled for c in win.macro.commands)


def test_inserir_loop_envolve_selecao(win, monkeypatch):
    from shiftmacro.ui import dialogs

    class Fake:
        def __init__(self, cmd, *a):
            self.cmd = cmd

        def exec(self):
            return QDialog.DialogCode.Accepted

        def result_command(self):
            self.cmd.params["count"] = "2"
            return self.cmd

    monkeypatch.setattr(dialogs, "edit_dialog_for", Fake)
    win.select_rows([1, 2, 3])
    win.insert_type("loop")
    assert texts(win) == "a[loop]bcd[end_loop]e"
    assert win.model.structure.ok
    # If sozinho insere também o End If
    win.select_rows([0])
    win.insert_type("if")
    assert texts(win).startswith("a[if][end_if]")


def test_copiar_colar_com_imagem(win):
    win.macro.images["botao"] = b"png-a"
    win.macro.commands.append(make("smart_click", image="botao"))
    win.model.refresh()
    win.select_rows([5])
    win.copy()
    win.macro.images["botao"] = b"png-diferente"  # conflito de nome com bytes diferentes
    win.select_rows([0])
    win.paste()
    pasted = win.macro.commands[1]
    assert pasted.type == "smart_click" and pasted.params["image"] != "botao"
    assert win.macro.images[pasted.params["image"]] == b"png-a"
    QApplication.clipboard().clear()  # a plataforma offscreen cai se sair dona da área de transferência


def test_painel_de_propriedades_aplica_e_desfaz(win):
    win.select_rows([2])
    ed = win.props.editor
    form_editor = ed.form.editors[0]
    form_editor.edit.setPlainText("novo texto")  # "Digitar texto" usa campo de várias linhas
    ed.common.delay.setValue(300)
    win._apply_properties()
    c = win.macro.commands[2]
    assert c.params["text"] == "novo texto" and c.delay_ms == 300
    win.undo()
    assert win.macro.commands[2].params["text"] == "c"


def test_estrutura_quebrada_bloqueia_execucao(win, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]))
    win.macro.commands.insert(0, make("loop", count="2"))
    win.model.refresh()
    win._refresh_status()
    assert "problema" in win.structure_label.text()
    win.run()
    assert shown and "não foi fechado" in shown[0]
    assert win.engine is None


def test_salvar_e_reabrir(win, tmp_path):
    p = tmp_path / "saida.shiftmacro"
    assert win._write(str(p))
    assert not win.dirty
    m = load_macro(p)
    assert [c.params["text"] for c in m.commands] == list("abcde")
    assert str(p.resolve()) in win.settings.recent[0]


def test_gravacao_inserida_apos_selecao(win):
    from shiftmacro.recorder.convert import RawEvent as E
    from shiftmacro.recorder.convert import convert

    cmds = convert([E(0, "down", 5, 5, button="left"), E(0.05, "up", 5, 5, button="left")], mode="clicks")
    win.select_rows([0])
    win.insert_commands(cmds)
    assert win.macro.commands[1].type == "left_click"
