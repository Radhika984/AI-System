"""Restricted arithmetic evaluator for model-generated expressions.

Never calls eval/exec. Parses with `ast` and walks a whitelist:
numbers, + - * / ** %, unary +/-, parentheses, whitelisted functions and
named constants. Guards against huge exponents, long inputs and deep trees.
"""
from __future__ import annotations

import ast
import math
import operator

MAX_LEN = 300
MAX_POW = 400
MAX_NODES = 200

_BIN = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}

FUNCS = {
    "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "log": math.log, "ln": math.log, "log10": math.log10, "log2": math.log2,
    "exp": math.exp, "abs": abs, "radians": math.radians, "degrees": math.degrees,
}
CONSTS = {
    "pi": math.pi, "e": math.e,
    "h": 6.626e-34, "c": 3e8, "me": 9.109e-31, "qe": 1.602e-19,
    "eps0": 8.854e-12, "k": 8.988e9, "g": 9.8,
}


class UnsafeExpression(ValueError):
    pass


def safe_eval(expr: str) -> float:
    if not isinstance(expr, str) or not expr.strip():
        raise UnsafeExpression("empty expression")
    if len(expr) > MAX_LEN:
        raise UnsafeExpression("expression too long")
    src = expr.replace("^", "**").replace("×", "*").replace("÷", "/").replace("−", "-")
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError as e:
        raise UnsafeExpression(f"syntax error: {e.msg}") from None
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise UnsafeExpression("expression too complex")
    return float(_ev(tree.body))


def _ev(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise UnsafeExpression(f"literal {node.value!r} not allowed")
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        left, right = _ev(node.left), _ev(node.right)
        if isinstance(node.op, ast.Pow) and (abs(right) > MAX_POW or abs(left) > 1e100):
            raise UnsafeExpression("exponent too large")
        try:
            return _BIN[type(node.op)](left, right)
        except (ZeroDivisionError, OverflowError) as e:
            raise UnsafeExpression(str(e)) from None
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_ev(node.operand))
    if isinstance(node, ast.Name):
        if node.id in CONSTS:
            return CONSTS[node.id]
        raise UnsafeExpression(f"name {node.id!r} not allowed")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCS:
            raise UnsafeExpression("function not allowed")
        if node.keywords or len(node.args) not in (1, 2):
            raise UnsafeExpression("bad call signature")
        try:
            return FUNCS[node.func.id](*[_ev(a) for a in node.args])
        except (ValueError, OverflowError) as e:
            raise UnsafeExpression(str(e)) from None
    raise UnsafeExpression(f"node {type(node).__name__} not allowed")


def close(a: float, b: float, rel: float = 0.02, abs_tol: float = 1e-9) -> bool:
    return math.isclose(a, b, rel_tol=rel, abs_tol=abs_tol)


_NUM = __import__("re").compile(r"-?\d+(?:\.\d+)?(?:[eE]-?\d+)?")


def first_number(text: str) -> float | None:
    m = _NUM.search((text or "").replace("−", "-").replace(" ", ""))
    return float(m.group()) if m else None
