import math

import pytest

from app.safe_eval import UnsafeExpression, safe_eval


@pytest.mark.parametrize("expr,val", [
    ("1/3*9e-2*400**2", 4800.0),
    ("sqrt(40^2+(60-30)^2)", 50.0),
    ("3/ln(8)", 3 / math.log(8)),
    ("6*7.203**2", 311.299254),
    ("(7e6/1.4e11)*(0.1)**3*1e9", 50.0),
    ("-2+3*(4-1)", 7.0),
    ("2*pi*50*95.5e-3", 2 * math.pi * 50 * 95.5e-3),
])
def test_valid(expr, val):
    assert safe_eval(expr) == pytest.approx(val, rel=1e-6)


@pytest.mark.parametrize("expr", [
    "__import__('os').system('echo hi')",
    "().__class__.__bases__",
    "open('x')",
    "lambda: 1",
    "[1,2,3]",
    "x+1",
    "9**9**9",
    "10**1000",
    "'a'*3",
    "sqrt(4, y=2)",
    "1 if 1 else 2",
    "",
    "1" * 400,
])
def test_rejected(expr):
    with pytest.raises(UnsafeExpression):
        safe_eval(expr)
