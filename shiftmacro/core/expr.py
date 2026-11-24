"""Avaliador seguro de expressões usadas em variáveis e condições.

Aceita números, textos entre aspas, variáveis, + - * / // % **, comparações,
and/or/not, parênteses e algumas funções (int, float, str, len, abs, min, max,
round, random). Também aceita texto livre com interpolação: "Volta {i}".
"""
from __future__ import annotations

import ast
import operator
import random
import re
from typing import Any, Mapping


class ExprError(ValueError):
    pass


_BIN = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_CMP = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}
_FUNCS = {
    "int": int,
    "float": float,
    "str": str,
    "len": len,
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "random": lambda a=0, b=1: random.randint(int(a), int(b)),
    "upper": lambda s: str(s).upper(),
    "lower": lambda s: str(s).lower(),
}


def _eval(node: ast.AST, vars: Mapping[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval(node.body, vars)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, str, bool)) or node.value is None:
            return node.value
        raise ExprError("valor não suportado")
    if isinstance(node, ast.Name):
        if node.id in vars:
            return vars[node.id]
        low = node.id.lower()
        if low in ("true", "verdadeiro"):
            return True
        if low in ("false", "falso"):
            return False
        raise ExprError(f"variável '{node.id}' não existe")
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        a, b = _eval(node.left, vars), _eval(node.right, vars)
        if isinstance(node.op, ast.Add) and (isinstance(a, str) or isinstance(b, str)):
            return f"{a}{b}"
        if isinstance(node.op, ast.Pow) and abs(b) > 100:
            raise ExprError("expoente grande demais")
        try:
            return _BIN[type(node.op)](a, b)
        except ZeroDivisionError as e:
            raise ExprError("divisão por zero") from e
        except TypeError as e:
            raise ExprError(f"operação inválida: {e}") from e
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, vars)
        if isinstance(node.op, ast.USub):
            return -v
        if isinstance(node.op, ast.UAdd):
            return +v
        if isinstance(node.op, ast.Not):
            return not v
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            res: Any = True
            for v in node.values:
                res = _eval(v, vars)
                if not res:
                    return res
            return res
        res = False
        for v in node.values:
            res = _eval(v, vars)
            if res:
                return res
        return res
    if isinstance(node, ast.Compare):
        left = _eval(node.left, vars)
        for op, comp in zip(node.ops, node.comparators):
            right = _eval(comp, vars)
            try:
                ok = _CMP[type(op)](left, right)
            except TypeError:
                ok = _CMP[type(op)](str(left), str(right))
            if not ok:
                return False
            left = right
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
        args = [_eval(a, vars) for a in node.args]
        try:
            return _FUNCS[node.func.id](*args)
        except (TypeError, ValueError) as e:
            raise ExprError(f"{node.func.id}(): {e}") from e
    if isinstance(node, ast.IfExp):
        return _eval(node.body, vars) if _eval(node.test, vars) else _eval(node.orelse, vars)
    raise ExprError("expressão não suportada")


def _prep(text: str) -> str:
    # aceita "e", "ou", "nao" e "=" isolado como comparação
    t = re.sub(r"\b(e)\b", " and ", text)
    t = re.sub(r"\b(ou)\b", " or ", t)
    t = re.sub(r"\b(n[aã]o)\b", " not ", t)
    t = re.sub(r"(?<![<>!=])=(?!=)", "==", t)
    return t.strip()


def evaluate(text: Any, vars: Mapping[str, Any]) -> Any:
    """Avalia uma expressão. Lança ExprError se for inválida."""
    if not isinstance(text, str):
        return text
    src = text.strip()
    if not src:
        return ""
    if len(src) > 2000:
        raise ExprError("expressão longa demais")
    first_error: ExprError | None = None
    prepped = _prep(src)
    for candidate in (src, prepped) if prepped != src else (src,):
        try:
            tree = ast.parse(candidate, mode="eval")
        except SyntaxError:
            continue
        try:
            return _eval(tree, vars)
        except ExprError as e:
            first_error = first_error or e
    raise first_error or ExprError(f"não entendi a expressão: {src}")


def value_of(text: Any, vars: Mapping[str, Any]) -> Any:
    """Valor de um campo que pode ser expressão ou texto comum.

    Tenta avaliar; se não for uma expressão válida, devolve o texto com
    {variáveis} substituídas.
    """
    if not isinstance(text, str):
        return text
    try:
        return evaluate(text, vars)
    except ExprError:
        return interpolate(text, vars)


_INTERP = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def interpolate(text: str, vars: Mapping[str, Any]) -> str:
    return _INTERP.sub(lambda m: str(vars.get(m.group(1), m.group(0))), str(text))


def number(text: Any, vars: Mapping[str, Any], default: float = 0) -> float:
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return text
    if text in (None, ""):
        return default
    v = evaluate(str(text), vars)
    try:
        return float(v) if not isinstance(v, int) else v
    except (TypeError, ValueError) as e:
        raise ExprError(f"'{text}' não é um número") from e


VAR_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
