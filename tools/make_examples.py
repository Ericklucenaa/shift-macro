"""Gera as macros de exemplo em examples/ (rode: python tools/make_examples.py)."""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shiftmacro.actions.registry import make  # noqa: E402
from shiftmacro.core.model import Macro, RunSettings  # noqa: E402
from shiftmacro.storage.project import save_macro  # noqa: E402
from shiftmacro.vision import matcher  # noqa: E402

OUT = ROOT / "examples"


def named(cmd, name="", comment="", delay=0):
    cmd.name, cmd.comment, cmd.delay_ms = name, comment, delay
    return cmd


def target_png() -> bytes:
    """Botão "ALVO" com textura própria (fácil de reconhecer, difícil de confundir)."""
    w, h = 132, 44
    img = np.full((h, w, 3), (40, 42, 46), np.uint8)
    cv2.rectangle(img, (1, 1), (w - 2, h - 2), (59, 169, 242), -1)  # âmbar (BGR)
    cv2.rectangle(img, (1, 1), (w - 2, h - 2), (20, 90, 150), 2)
    for i in range(0, w, 11):
        cv2.line(img, (i, h - 7), (i + 5, h - 7), (20, 90, 150), 2)
    cv2.circle(img, (22, h // 2 - 2), 9, (30, 30, 30), 2)
    cv2.circle(img, (22, h // 2 - 2), 3, (30, 30, 30), -1)
    cv2.putText(img, "ALVO", (40, 29), cv2.FONT_HERSHEY_DUPLEX, 0.8, (25, 25, 25), 2, cv2.LINE_AA)
    return matcher.encode_png(img)


def notepad() -> Macro:
    m = Macro(name="Bloco de Notas: digitar texto", description="Abre o Bloco de Notas, espera a janela e digita linhas numeradas. Não salva nada.")
    m.commands = [
        named(make("comment", text="Exemplo básico: abrir programa, esperar janela, digitar, loop e combinação de teclas."), ""),
        named(make("open_program", path="notepad.exe"), "Abrir o Bloco de Notas"),
        named(make("wait_window", window="Bloco de Notas", timeout_ms=15000, activate=True, on_not_found="stop"),
              "Esperar a janela", "Em Windows em inglês, troque por Notepad", 600),
        make("type_text", text="Olá! Este texto foi digitado pelo Shift Macro.\nAcentuação funciona: ação, você, pão.\n\n", interval_ms=12),
        make("loop", count="5", counter="volta"),
        make("type_text", text="Linha {volta} de 5", interval_ms=8),
        make("key_press", key="enter"),
        make("end_loop"),
        named(make("hotkey", keys="ctrl+home"), "Voltar ao início", delay=300),
        make("notify", title="Shift Macro", message="Exemplo do Bloco de Notas concluído. Feche sem salvar."),
    ]
    return m


def logic() -> Macro:
    m = Macro(name="Variáveis, condições e funções", variables={"meta": 10},
              description="Demonstra Loop, While, If/Else If/Else, Break/Continue, Go To, funções e variáveis. "
                          "Não move o mouse nem digita: acompanhe pelo Log e pela aba Variáveis.")
    m.commands = [
        make("comment", text="Nenhuma ação de mouse/teclado aqui: execute e veja o Log e a aba Variáveis."),
        make("set_var", name="soma", value="0"),
        make("set_var", name="pares", value="0"),
        make("loop", count="meta", counter="i"),
        make("if", cond="expr", expr="i % 2 == 0"),
        make("set_var", name="pares", op="+=", value="1"),
        make("else_if", cond="expr", expr="i == 7"),
        named(make("continue"), "Pular o 7"),
        make("else"),
        make("set_var", name="soma", op="+=", value="i"),
        make("end_if"),
        make("end_loop"),
        make("call_function", name="relatorio"),
        make("set_var", name="n", value="1"),
        make("while", cond="expr", expr="n < 1000"),
        make("set_var", name="n", op="*=", value="3"),
        make("if", cond="expr", expr="n > 200"),
        named(make("break"), "Sair cedo"),
        make("end_if"),
        make("end_while"),
        make("set_var", name="sorteio", value="random(1, 6)"),
        make("if", cond="expr", expr="sorteio >= 4"),
        make("goto", target="sorte"),
        make("end_if"),
        make("notify", title="Dado", message="Saiu {sorteio}: não foi dessa vez."),
        make("goto", target="fim"),
        make("label", label="sorte"),
        make("notify", title="Dado", message="Saiu {sorteio}! Ímpares somados: {soma}, pares: {pares}, n: {n}"),
        make("beep", sound="info"),
        make("label", label="fim"),
        make("stop_macro"),
        make("function", name="relatorio"),
        make("set_var", name="resumo", value="\"Soma dos ímpares (sem o 7): \" + soma"),
        make("end_function"),
    ]
    return m


def smart_click() -> Macro:
    m = Macro(name="Smart Click: clicar no alvo", images={"alvo": target_png()},
              settings=RunSettings(repeat_mode="once"),
              description="Abre smartclick-teste.html no navegador e clica 5 vezes no botão ALVO, que muda de lugar "
                          "a cada clique. Mostra Smart Click, Aguardar imagem, If com imagem e variáveis com coordenadas.")
    m.commands = [
        make("comment", text="Mantenha o zoom do navegador em 100%. A página mostra o alvo em tamanho real."),
        named(make("open_file", path="smartclick-teste.html"), "Abrir a página de teste"),
        named(make("wait_image", image="alvo", threshold=85, timeout_ms=20000, interval_ms=200, on_found="none",
                   on_not_found="stop", multiscale=True), "Esperar a página carregar"),
        make("loop", count="5", counter="clique"),
        named(make("smart_click", image="alvo", threshold=85, timeout_ms=5000, multiscale=True, on_found="left",
                   on_not_found="stop"), "Clicar no alvo", delay=450),
        make("end_loop"),
        named(make("find_image", image="alvo", threshold=85, on_found="store", var="alvo", timeout_ms=2000, multiscale=True),
              "Guardar a posição final"),
        make("if", cond="image_found", image="alvo", threshold=85, multiscale=True),
        make("mouse_move", x="alvo_x", y="alvo_y + 70", duration_ms=400),
        make("notify", title="Smart Click", message="5 cliques feitos. O alvo está em ({alvo_x}, {alvo_y})."),
        make("else"),
        make("notify", title="Smart Click", message="O alvo sumiu da tela."),
        make("end_if"),
    ]
    return m


def chain() -> Macro:
    m = Macro(name="Executar outra macro", description="Chama 02-variaveis-e-condicoes.shiftmacro duas vezes.")
    m.commands = [
        make("loop", count="2", counter="vez"),
        make("run_macro", path="02-variaveis-e-condicoes.shiftmacro"),
        make("delay", ms=500),
        make("end_loop"),
        make("notify", title="Shift Macro", message="A outra macro rodou duas vezes."),
    ]
    return m


HTML = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>Shift Macro · teste do Smart Click</title>
<style>
  html,body{margin:0;height:100%;background:#16181B;color:#E4E6E9;font:15px "Segoe UI",sans-serif;overflow:hidden}
  header{padding:18px 24px;border-bottom:1px solid #32373E;display:flex;gap:24px;align-items:baseline}
  h1{font-size:17px;margin:0;font-weight:600}
  #n{color:#F2A93B;font-weight:700}
  #alvo{position:absolute;cursor:pointer;user-select:none}
  p{color:#959CA6;margin:0}
</style></head>
<body>
<header><h1>Teste do Smart Click</h1><p>Cliques no alvo: <span id="n">0</span></p><p>O alvo muda de lugar a cada clique.</p></header>
<img id="alvo" src="alvo.png" alt="alvo" draggable="false">
<script>
  const img = document.getElementById('alvo'), n = document.getElementById('n');
  let count = 0;
  function place(){
    // tamanho real em pixels físicos, qualquer que seja a escala do Windows
    img.style.width = (img.naturalWidth / devicePixelRatio) + 'px';
    const w = img.getBoundingClientRect().width, h = img.getBoundingClientRect().height;
    img.style.left = (40 + Math.random() * (innerWidth - w - 80)) + 'px';
    img.style.top = (90 + Math.random() * (innerHeight - h - 130)) + 'px';
  }
  img.addEventListener('click', () => { n.textContent = ++count; place(); });
  img.complete ? place() : img.addEventListener('load', place);
  addEventListener('resize', place);
</script>
</body></html>
"""


def main():
    OUT.mkdir(exist_ok=True)
    save_macro(notepad(), OUT / "01-bloco-de-notas.shiftmacro")
    save_macro(logic(), OUT / "02-variaveis-e-condicoes.shiftmacro")
    sc = smart_click()
    save_macro(sc, OUT / "03-smart-click.shiftmacro")
    save_macro(chain(), OUT / "04-executar-outra-macro.shiftmacro")
    (OUT / "alvo.png").write_bytes(sc.images["alvo"])
    (OUT / "smartclick-teste.html").write_text(HTML, encoding="utf-8")
    print("Exemplos gerados em", OUT)


if __name__ == "__main__":
    main()
