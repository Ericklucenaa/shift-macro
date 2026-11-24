"""Análise da estrutura de blocos de uma lista plana de comandos.

Liga cada If/Else If/Else ao seu End If, cada Loop/While ao seu fim, cada
Função ao seu fim, e indexa rótulos e funções. Também calcula a profundidade
de cada linha (recuo na tabela) e lista problemas legíveis.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..actions import registry

CLOSERS = {"if": "end_if", "loop": "end_loop", "while": "end_while", "function": "end_function"}
CLOSER_LABEL = {"end_if": "End If", "end_loop": "End Loop", "end_while": "End While", "end_function": "Fim da função"}


@dataclass
class Structure:
    end_of: dict[int, int] = field(default_factory=dict)  # abertura -> fechamento
    start_of: dict[int, int] = field(default_factory=dict)  # fechamento -> abertura
    next_branch: dict[int, int] = field(default_factory=dict)  # if/else_if -> próximo else_if/else
    owner: dict[int, int] = field(default_factory=dict)  # else/else_if -> abertura do If
    labels: dict[str, int] = field(default_factory=dict)
    functions: dict[str, int] = field(default_factory=dict)
    depth: list[int] = field(default_factory=list)
    errors: list[tuple[int, str]] = field(default_factory=list)  # (linha, mensagem)

    @property
    def ok(self) -> bool:
        return not self.errors

    def enclosing_loops(self, index: int) -> list[int]:
        """Aberturas de loop/while que contêm a linha, da mais externa à mais interna."""
        return [s for s, e in sorted(self.end_of.items()) if s < index <= e and self._family(s) in ("loop", "while")]

    _families: dict[int, str] = field(default_factory=dict)

    def _family(self, i: int) -> str:
        return self._families.get(i, "")


def family_of(cmd) -> str | None:
    try:
        spec = registry.get(cmd.type)
    except KeyError:
        return None
    if spec.block == "open":
        return spec.block_family
    if spec.is_opener(cmd.params):
        return "if"  # Smart Click com bloco se comporta como um If
    return None


def analyze(commands) -> Structure:
    st = Structure()
    stack: list[tuple[int, str]] = []  # (índice, família)
    last_branch: dict[int, int] = {}  # abertura do if -> último ramo visto
    has_else: set[int] = set()
    for i, cmd in enumerate(commands):
        try:
            spec = registry.get(cmd.type)
        except KeyError:
            st.errors.append((i, f"Comando desconhecido: {cmd.type}"))
            st.depth.append(len(stack))
            continue
        fam = family_of(cmd)
        if fam:
            st.depth.append(len(stack))
            stack.append((i, fam))
            st._families[i] = fam
            last_branch[i] = i
            if fam == "function":
                name = str(cmd.params.get("name") or "").strip()
                if not name:
                    st.errors.append((i, "Função sem nome"))
                elif name in st.functions:
                    st.errors.append((i, f"Função '{name}' definida duas vezes"))
                else:
                    st.functions[name] = i
                if len(stack) > 1:
                    st.errors.append((i, "Funções não podem ficar dentro de outro bloco"))
            continue
        if spec.block == "mid":
            if not stack or stack[-1][1] != "if":
                st.errors.append((i, f"{spec.label} sem If correspondente"))
                st.depth.append(len(stack))
                continue
            opener = stack[-1][0]
            if opener in has_else:
                st.errors.append((i, f"{spec.label} depois do Else"))
            if cmd.type == "else":
                has_else.add(opener)
            st.next_branch[last_branch[opener]] = i
            last_branch[opener] = i
            st.owner[i] = opener
            st.depth.append(len(stack) - 1)
            continue
        if spec.block == "close":
            want_family = spec.block_family
            if not stack:
                st.errors.append((i, f"{spec.label} sem abertura correspondente"))
                st.depth.append(0)
                continue
            opener, fam_open = stack[-1]
            if fam_open != want_family:
                exp = CLOSER_LABEL[CLOSERS[fam_open]]
                st.errors.append((i, f"{spec.label} encontrado, mas falta fechar o bloco da etapa {opener + 1} com {exp}"))
                st.depth.append(len(stack) - 1)
                continue
            stack.pop()
            st.end_of[opener] = i
            st.start_of[i] = opener
            st.depth.append(len(stack))
            continue
        st.depth.append(len(stack))
        if cmd.type == "label":
            name = str(cmd.params.get("label") or "").strip()
            if not name:
                st.errors.append((i, "Rótulo sem nome"))
            elif name in st.labels:
                st.errors.append((i, f"Rótulo '{name}' repetido"))
            else:
                st.labels[name] = i
    for opener, fam in stack:
        st.errors.append((opener, f"Bloco aberto na etapa {opener + 1} não foi fechado ({CLOSER_LABEL[CLOSERS[fam]]})"))
    # rótulos/funções referenciados que não existem
    for i, cmd in enumerate(commands):
        if cmd.type == "call_function":
            n = str(cmd.params.get("name") or "").strip()
            if n not in st.functions:
                st.errors.append((i, f"Função '{n}' não existe"))
        elif cmd.type in ("break", "continue") and not st.enclosing_loops(i):
            st.errors.append((i, f"{registry.get(cmd.type).label} fora de um loop"))
    return st


def resolve_target(st: Structure, target: str, count: int) -> int | None:
    """Rótulo ou número de etapa (1-based) -> índice."""
    t = (target or "").strip()
    if not t:
        return None
    if t in st.labels:
        return st.labels[t]
    if t.isdigit():
        n = int(t)
        if 1 <= n <= count:
            return n - 1
    return None
