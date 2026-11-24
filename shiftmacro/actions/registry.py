"""Registro de tipos de comando.

Cada tipo declara: rótulo, categoria, campos editáveis (usados para gerar os
formulários da interface), como se descreve na tabela e como executa. O motor
só conhece este registro, então um comando novo é um CommandSpec a mais.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# Natureza do comando: define cor e ícone na tabela.
KINDS = ("mouse", "keyboard", "image", "condition", "loop", "flow", "variable", "system", "comment", "delay")


@dataclass
class Field:
    key: str
    label: str
    kind: str = "text"  # int float text multiline bool choice key hotkey image point region color file folder label function var expr window macro
    default: Any = None
    options: list[tuple[Any, str]] = field(default_factory=list)
    min: float | None = None
    max: float | None = None
    help: str = ""
    keys: tuple[str, ...] = ()  # campos compostos (point: x,y; region: lista)
    show_if: tuple[str, tuple[Any, ...]] | None = None  # (campo, valores) para exibir

    def visible(self, params: dict[str, Any]) -> bool:
        return _visible(self.show_if, params)


def _visible(rule, params: dict[str, Any]) -> bool:
    if not rule:
        return True
    k, values = rule
    if k == "__all__":  # várias regras ao mesmo tempo
        return all(_visible(r, params) for r in values)
    return params.get(k) in values


@dataclass
class Flow:
    """Instrução de fluxo devolvida por um comando."""

    goto: str | None = None  # rótulo ou número da etapa
    stop: bool = False
    pause: bool = False
    branch: bool | None = None  # para comandos que abrem bloco (Smart Click com bloco)
    retry: bool = False


@dataclass
class CommandSpec:
    type: str
    label: str
    category: str
    kind: str
    fields: list[Field] = field(default_factory=list)
    describe: Callable[[dict[str, Any]], str] = lambda p: ""
    run: Optional[Callable[[Any, Any], Optional[Flow]]] = None
    # estrutura de blocos: open (abre), mid (else/elseif), close (fecha)
    block: str | None = None
    block_family: str | None = None  # if | loop | while | function
    opens_block_when: Callable[[dict[str, Any]], bool] | None = None
    help: str = ""

    def defaults(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for f in self.fields:
            if f.kind == "point":
                kx, ky = f.keys
                d = f.default or (0, 0)
                out[kx], out[ky] = d[0], d[1]
            else:
                out[f.key] = f.default
        return out

    def is_opener(self, params: dict[str, Any]) -> bool:
        if self.block == "open":
            return True
        return bool(self.opens_block_when and self.opens_block_when(params))


REGISTRY: dict[str, CommandSpec] = {}
CATEGORIES: list[str] = []


def register(spec: CommandSpec) -> CommandSpec:
    if spec.kind not in KINDS:
        raise ValueError(f"kind inválido: {spec.kind}")
    REGISTRY[spec.type] = spec
    if spec.category not in CATEGORIES:
        CATEGORIES.append(spec.category)
    return spec


def _ensure_loaded() -> None:
    if not REGISTRY:
        from . import commands  # noqa: F401  (registra o catálogo)


def get(type_: str) -> CommandSpec:
    _ensure_loaded()
    try:
        return REGISTRY[type_]
    except KeyError:
        raise KeyError(f"Comando desconhecido: {type_}") from None


def by_category() -> dict[str, list[CommandSpec]]:
    _ensure_loaded()
    out: dict[str, list[CommandSpec]] = {c: [] for c in CATEGORIES}
    for s in REGISTRY.values():
        out[s.category].append(s)
    return out


def make(type_: str, **params: Any):
    """Cria um Command com os valores padrão do tipo, sobrescritos por params."""
    from ..core.model import Command

    spec = get(type_)
    p = spec.defaults()
    p.update(params)
    return Command(type=type_, params=p)
