"""受限数学表达式解析器。学生输入不可信，所以不使用 eval / exec / sympify。"""

from __future__ import annotations

import inspect
import math

import pytest

from tutor_api.services import mathparse
from tutor_api.services.mathparse import EvalError, ParseError, evaluate, parse


def value(text: str, **env: float) -> float:
    return evaluate(parse(text, variables=tuple(env)), env)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1+2*3", 7),
        ("(1+2)*3", 9),
        ("2^3", 8),
        ("-2^2", -4),
        ("2^-1", 0.5),
        ("2^3^2", 512),
        ("3/4", 0.75),
        ("10-4-3", 3),
        ("8/4/2", 1),
        (".5", 0.5),
        ("4.0", 4),
        ("+3", 3),
        ("--3", 3),
    ],
)
def test_arithmetic_and_precedence(text, expected):
    assert value(text) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("１＋２", 3),
        ("（１＋２）×３", 9),
        ("2×3", 6),
        ("2·3", 6),
        ("6÷4", 1.5),
        ("5−2", 3),
        ("3²", 9),
        ("2³", 8),
        ("√2", math.sqrt(2)),
        ("√(9)", 3),
        ("sqrt(16)", 4),
        ("√2/2", math.sqrt(2) / 2),
        ("2π", 2 * math.pi),
        ("pi/2", math.pi / 2),
        ("sin30°", 0.5),
        ("cos(60°)", 0.5),
        ("sin(π/6)", 0.5),
        ("tan(45°)", 1),
        ("ln(1)", 0),
    ],
)
def test_symbols_students_actually_type(text, expected):
    assert value(text) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("text", "env", "expected"),
    [
        ("2x", {"x": 3}, 6),
        ("x²", {"x": 3}, 9),
        ("2(x+1)", {"x": 3}, 8),
        ("(x+1)(x-1)", {"x": 3}, 8),
        ("2x^2", {"x": 3}, 18),
        ("xy", {"x": 2, "y": 5}, 10),
        ("g*sin(theta)", {"g": 10, "theta": math.pi / 6}, 5),
        ("gsinθ", {"g": 10, "theta": math.pi / 6}, 5),
        ("g sin θ", {"g": 10, "theta": math.pi / 6}, 5),
        ("sinθ g", {"g": 10, "theta": math.pi / 6}, 5),
        ("sinθ·g", {"g": 10, "theta": math.pi / 6}, 5),
        ("sin2θ", {"theta": math.pi / 12}, 0.5),
        ("mg sinθ/m", {"m": 7, "g": 10, "theta": math.pi / 6}, 5),
        ("μmg cosθ", {"mu": 0.5, "m": 2, "g": 10, "theta": 0}, 10),
    ],
)
def test_variables_and_implicit_multiplication(text, env, expected):
    assert value(text, **env) == pytest.approx(expected)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "2+",
        "(1+2",
        "1+2)",
        "2**3",
        "x.y",
        "a;b",
        "1,2",
        "__import__('os').system('whoami')",
        "().__class__",
        "lambda: 1",
        "open('x')",
        "x=1",
        "1e9",
        "0x10",
        "sin",
        "√",
        "3°°",
    ],
)
def test_anything_outside_the_grammar_is_rejected(text):
    with pytest.raises(ParseError):
        parse(text, variables=("x",))


def test_undeclared_symbols_are_rejected():
    with pytest.raises(ParseError, match="y"):
        parse("x+y", variables=("x",))


def test_overlong_or_deeply_nested_input_is_rejected():
    with pytest.raises(ParseError):
        parse("1+" * 200 + "1")
    with pytest.raises(ParseError):
        parse("(" * 80 + "1" + ")" * 80)


@pytest.mark.parametrize("text", ["1/0", "√(-1)", "ln(0)", "(-8)^(1/3)", "10^400", "tan(90°)^9^9"])
def test_undefined_values_raise_eval_error(text):
    with pytest.raises(EvalError):
        value(text)


def test_missing_variable_value_is_an_eval_error():
    with pytest.raises(EvalError):
        evaluate(parse("2x", variables=("x",)), {})


def test_parser_never_delegates_to_eval():
    source = inspect.getsource(mathparse)
    for forbidden in (
        "eval(",
        "exec(",
        "compile(",
        "sympify",
        "parse_expr",
        "__import__",
        "getattr(",
    ):
        assert forbidden not in source
