"""受限数学表达式的解析与求值。

学生输入是不可信的，所以这里是一个手写的递归下降解析器：只认数字、已声明的变量、
+ - * / ^、括号、sin / cos / tan / ln / sqrt、π 和角度符号。不认识的东西一律拒绝，
不把任何输入交给解释器执行。求值只用浮点数，溢出和无定义的情况抛 EvalError。

支持学生实际会敲的写法：全角字符、× · ÷ −、上标 ² ³、√、希腊字母，以及省略的乘号
（2x、g sinθ、2(x+1)）。数字只能写在字母或括号前面，"x2" 这类写法有歧义，按无法识别处理。
"""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Collection, Mapping
from typing import Any

MAX_LENGTH = 200
MAX_DEPTH = 32

Node = tuple[Any, ...]


class ParseError(ValueError):
    """输入不在受限语法之内。"""


class EvalError(ArithmeticError):
    """表达式在给定取值下没有定义（除以零、负数开方、溢出等）。"""


_FUNCTIONS = {
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "ln": math.log,
    "sqrt": math.sqrt,
}
_GREEK = {
    "θ": "theta",
    "α": "alpha",
    "β": "beta",
    "γ": "gamma",
    "μ": "mu",
    "ω": "omega",
    "φ": "phi",
    "λ": "lambda",
    "ρ": "rho",
}
_SUPERSCRIPTS = {
    "⁰": "0",
    "¹": "1",
    "²": "2",
    "³": "3",
    "⁴": "4",
    "⁵": "5",
    "⁶": "6",
    "⁷": "7",
    "⁸": "8",
    "⁹": "9",
    "⁻": "-",
}
_TRANSLATE = str.maketrans(
    {"×": "*", "·": "*", "∙": "*", "⋅": "*", "÷": "/", "−": "-", "–": "-", "—": "-"}
)
_OPERATORS = "+-*/^()"


def expand_superscripts(text: str) -> str:
    """把上标数字改写成 ^n（x² → x^2，s⁻¹ → s^-1）。必须在 NFKC 之前做，否则上标会被抹成普通数字。"""
    out: list[str] = []
    in_run = False
    for char in text:
        if char in _SUPERSCRIPTS:
            if not in_run:
                out.append("^")
                in_run = True
            out.append(_SUPERSCRIPTS[char])
        else:
            in_run = False
            out.append(char)
    return "".join(out)


def prepare(text: str) -> str:
    return unicodedata.normalize("NFKC", expand_superscripts(text)).translate(_TRANSLATE)


def _tokenize(text: str, variables: Collection[str]) -> list[tuple[str, Any]]:
    declared = sorted(variables, key=len, reverse=True)
    tokens: list[tuple[str, Any]] = []
    i = 0
    while i < len(text):
        char = text[i]
        if char.isspace():
            i += 1
        elif char.isdigit() or char == ".":
            j = i
            while j < len(text) and text[j].isdigit():
                j += 1
            if j < len(text) and text[j] == ".":
                k = j + 1
                while k < len(text) and text[k].isdigit():
                    k += 1
                if k == j + 1:
                    raise ParseError("小数点后面缺少数字")
                j = k
            tokens.append(("num", float(text[i:j])))
            i = j
        elif char in _OPERATORS:
            tokens.append(("op", char))
            i += 1
        elif char == "°":
            tokens.append(("deg", char))
            i += 1
        elif char == "√":
            tokens.append(("func", "sqrt"))
            i += 1
        elif char == "π":
            tokens.append(("const", math.pi))
            i += 1
        elif char in _GREEK:
            name = _GREEK[char]
            if name not in variables:
                raise ParseError(f"未知符号 {char}")
            tokens.append(("var", name))
            i += 1
        elif char.isascii() and char.isalpha():
            rest = text[i:]
            lowered = rest.lower()
            function = next((name for name in _FUNCTIONS if lowered.startswith(name)), None)
            if function is not None:
                tokens.append(("func", function))
                i += len(function)
            elif lowered.startswith("pi") and "p" not in variables:
                tokens.append(("const", math.pi))
                i += 2
            else:
                name = next((v for v in declared if rest.startswith(v)), None)
                if name is None:
                    raise ParseError(f"未知符号 {char}")
                tokens.append(("var", name))
                i += len(name)
        else:
            raise ParseError(f"无法识别的字符 {char}")
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, Any]]) -> None:
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> tuple[str, Any] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self) -> tuple[str, Any]:
        token = self.peek()
        if token is None:
            raise ParseError("表达式不完整")
        self.pos += 1
        return token

    def at_op(self, *ops: str) -> bool:
        token = self.peek()
        return token is not None and token[0] == "op" and token[1] in ops

    def expect(self, op: str) -> None:
        if not self.at_op(op):
            raise ParseError(f"缺少 {op}")
        self.pos += 1

    def expr(self, depth: int) -> Node:
        node = self.term(depth)
        while self.at_op("+", "-"):
            op = self.take()[1]
            node = (op, node, self.term(depth))
        return node

    def term(self, depth: int) -> Node:
        node = self.unary(depth)
        while True:
            token = self.peek()
            if self.at_op("*", "/"):
                op = self.take()[1]
                node = (op, node, self.unary(depth))
            elif token is not None and (token[0] in {"var", "const", "func"} or self.at_op("(")):
                node = ("*", node, self.power(depth))  # 省略的乘号
            elif token is not None and token[0] == "num":
                raise ParseError("数字应写在字母或括号的前面")
            else:
                return node

    def unary(self, depth: int) -> Node:
        if self.at_op("-"):
            self.pos += 1
            return ("neg", self.unary(depth))
        if self.at_op("+"):
            self.pos += 1
            return self.unary(depth)
        return self.power(depth)

    def power(self, depth: int) -> Node:
        base = self.atom(depth)
        if self.at_op("^"):
            self.pos += 1
            return ("^", base, self.unary(depth))
        return base

    def number(self, value: float) -> Node:
        token = self.peek()
        if token is not None and token[0] == "deg":
            self.pos += 1
            return ("num", value * math.pi / 180)
        return ("num", value)

    def group(self, depth: int) -> Node:
        if depth >= MAX_DEPTH:
            raise ParseError("表达式嵌套过深")
        node = self.expr(depth + 1)
        self.expect(")")
        return node

    def atom(self, depth: int) -> Node:
        kind, value = self.take()
        if kind == "num":
            return self.number(value)
        if kind == "var":
            return ("var", value)
        if kind == "const":
            return ("num", value)
        if kind == "func":
            return ("func", value, self.function_argument(value, depth))
        if kind == "op" and value == "(":
            return self.group(depth)
        raise ParseError("这里需要一个数、字母或括号")

    def function_argument(self, name: str, depth: int) -> Node:
        """函数的自变量：带括号的任意表达式；不带括号时只取紧跟的一个数或一个字母，
        三角函数允许"系数 + 字母"（sin2θ 读作 sin(2θ)）。"""
        if self.at_op("("):
            self.pos += 1
            return self.group(depth)
        token = self.peek()
        if token is None:
            raise ParseError(f"{name} 缺少自变量")
        kind, value = token
        if kind == "num":
            self.pos += 1
            argument = self.number(value)
            following = self.peek()
            if name != "sqrt" and following is not None and following[0] in {"var", "const"}:
                self.pos += 1
                operand: Node = (
                    ("var", following[1]) if following[0] == "var" else ("num", following[1])
                )
                return ("*", argument, operand)
            return argument
        if kind == "var":
            self.pos += 1
            return ("var", value)
        if kind == "const":
            self.pos += 1
            return ("num", value)
        raise ParseError(f"{name} 缺少自变量")


def parse(text: str, variables: Collection[str] = ()) -> Node:
    """解析成语法树。variables 是允许出现的变量名；其余字母一律拒绝。"""
    if len(text) > MAX_LENGTH:
        raise ParseError("表达式过长")
    tokens = _tokenize(prepare(text), variables)
    if not tokens:
        raise ParseError("表达式为空")
    parser = _Parser(tokens)
    node = parser.expr(0)
    if parser.pos != len(tokens):
        raise ParseError("表达式后面有多余的内容")
    return node


def _compute(node: Node, env: Mapping[str, float]) -> float:
    kind = node[0]
    if kind == "num":
        return float(node[1])
    if kind == "var":
        if node[1] not in env:
            raise EvalError(f"变量 {node[1]} 没有取值")
        return float(env[node[1]])
    if kind == "neg":
        return -_compute(node[1], env)
    if kind == "func":
        return float(_FUNCTIONS[node[1]](_compute(node[2], env)))
    left, right = _compute(node[1], env), _compute(node[2], env)
    if kind == "+":
        return left + right
    if kind == "-":
        return left - right
    if kind == "*":
        return left * right
    if kind == "/":
        return left / right
    if left < 0 and right != math.floor(right):
        raise EvalError("负数的非整数次幂没有实数值")
    return float(left**right)


def evaluate(node: Node, env: Mapping[str, float] | None = None) -> float:
    try:
        result = _compute(node, env or {})
    except (ZeroDivisionError, OverflowError, ValueError) as error:
        raise EvalError(str(error)) from error
    if not math.isfinite(result):
        raise EvalError("结果不是有限的实数")
    return result


def evaluate_number(text: str) -> float:
    """解析并计算一个不含变量的数值表达式。"""
    return evaluate(parse(text))
