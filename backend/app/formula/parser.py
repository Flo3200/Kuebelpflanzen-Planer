"""Safe expression language for formulas (no eval, no Python code).

Grammar (precedence low -> high):
    expr        := or_expr
    or_expr     := and_expr ( ("or" | "||") and_expr )*
    and_expr    := not_expr ( ("and" | "&&") not_expr )*
    not_expr    := ("not" | "!") not_expr | comparison
    comparison  := additive ( ("<" | "<=" | ">" | ">=" | "==" | "!=") additive )?
    additive    := term ( ("+" | "-") term )*
    term        := unary ( ("*" | "/" | "%") unary )*
    unary       := ("-" | "+") unary | power
    power       := primary ( ("^" | "**") unary )?
    primary     := NUMBER | NAME | NAME "(" [expr ("," expr)*] ")" | "(" expr ")"

Functions: min, max, abs, sqrt, log, log10, exp, pow, round, floor, ceil, clamp(x, lo, hi),
if(cond, a, b) – case distinction, and aggregates over the plants of a stop:
sum_plants(e), max_plants(e), min_plants(e), avg_plants(e), count_plants(); sum_i / max_i /
min_i are short aliases. Booleans are 1 and 0.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

MAX_LENGTH = 4000
MAX_NODES = 600
MAX_DEPTH = 80


class FormulaError(Exception):
    def __init__(self, code: str, detail: str = "", pos: int | None = None, name: str | None = None) -> None:
        super().__init__(f"{code}: {detail} @{pos}")
        self.code = code
        self.detail = detail
        self.pos = pos
        self.name = name


# ------------------------------------------------------------------------------------- tokens

TOKEN_RE = re.compile(
    r"\s*(?:(?P<num>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\.\d+)|(?P<name>[A-Za-z_äöüÄÖÜß][A-Za-z0-9_äöüÄÖÜß]*)"
    r"|(?P<op>\*\*|<=|>=|==|!=|&&|\|\||[-+*/%^(),<>!]))"
)


@dataclass(frozen=True)
class Token:
    kind: str  # num | name | op | end
    value: str
    pos: int


def tokenize(src: str) -> list[Token]:
    if len(src) > MAX_LENGTH:
        raise FormulaError("too_long", f"max {MAX_LENGTH} characters")
    tokens: list[Token] = []
    pos = 0
    while pos < len(src):
        if src[pos:].strip() == "":
            break
        m = TOKEN_RE.match(src, pos)
        if not m or m.end() == pos:
            raise FormulaError("syntax", f"unerwartetes Zeichen „{src[pos].strip() or src[pos]}“", pos)
        start = m.start(m.lastgroup) if m.lastgroup else pos
        kind = m.lastgroup or "op"
        tokens.append(Token(kind, m.group(kind), start))
        pos = m.end()
    tokens.append(Token("end", "", len(src)))
    return tokens


# ------------------------------------------------------------------------------------- AST
# Nodes are tuples: ("num", value) | ("var", name, pos) | ("call", name, args, pos)
# | ("bin", op, left, right, pos) | ("un", op, operand, pos)

KEYWORDS = {"and", "or", "not"}
FUNCTIONS = {
    "min": (1, 99),
    "max": (1, 99),
    "abs": (1, 1),
    "sqrt": (1, 1),
    "log": (1, 2),
    "log10": (1, 1),
    "exp": (1, 1),
    "pow": (2, 2),
    "round": (1, 2),
    "floor": (1, 1),
    "ceil": (1, 1),
    "clamp": (3, 3),
    "if": (3, 3),
}
AGGREGATES = {
    "sum_plants": "sum",
    "max_plants": "max",
    "min_plants": "min",
    "avg_plants": "avg",
    "count_plants": "count",
    "sum_i": "sum",
    "max_i": "max",
    "min_i": "min",
}


class Parser:
    def __init__(self, src: str) -> None:
        self.src = src
        self.tokens = tokenize(src)
        self.i = 0
        self.nodes = 0
        self.depth = 0

    def peek(self) -> Token:
        return self.tokens[self.i]

    def next(self) -> Token:
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def accept(self, *values: str) -> Token | None:
        tok = self.peek()
        if (tok.kind == "op" and tok.value in values) or (tok.kind == "name" and tok.value in values):
            self.i += 1
            return tok
        return None

    def expect(self, value: str) -> Token:
        tok = self.accept(value)
        if tok is None:
            got = self.peek()
            raise FormulaError("syntax", f"„{value}“ erwartet, gefunden „{got.value or 'Ende'}“", got.pos)
        return tok

    def node(self, n: tuple) -> tuple:
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise FormulaError("too_complex", "Formel zu komplex")
        return n

    def parse(self) -> tuple:
        if not self.src.strip():
            raise FormulaError("syntax", "leere Formel", 0)
        tree = self.or_expr()
        if self.peek().kind != "end":
            tok = self.peek()
            raise FormulaError("syntax", f"unerwartetes „{tok.value}“", tok.pos)
        return tree

    def _enter(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise FormulaError("too_complex", "zu tief verschachtelt")

    def or_expr(self) -> tuple:
        left = self.and_expr()
        while (tok := self.accept("or", "||")) is not None:
            left = self.node(("bin", "or", left, self.and_expr(), tok.pos))
        return left

    def and_expr(self) -> tuple:
        left = self.not_expr()
        while (tok := self.accept("and", "&&")) is not None:
            left = self.node(("bin", "and", left, self.not_expr(), tok.pos))
        return left

    def not_expr(self) -> tuple:
        if (tok := self.accept("not", "!")) is not None:
            self._enter()
            operand = self.not_expr()
            self.depth -= 1
            return self.node(("un", "not", operand, tok.pos))
        return self.comparison()

    def comparison(self) -> tuple:
        left = self.additive()
        if (tok := self.accept("<", "<=", ">", ">=", "==", "!=")) is not None:
            return self.node(("bin", tok.value, left, self.additive(), tok.pos))
        return left

    def additive(self) -> tuple:
        left = self.term()
        while (tok := self.accept("+", "-")) is not None:
            left = self.node(("bin", tok.value, left, self.term(), tok.pos))
        return left

    def term(self) -> tuple:
        left = self.unary()
        while (tok := self.accept("*", "/", "%")) is not None:
            left = self.node(("bin", tok.value, left, self.unary(), tok.pos))
        return left

    def unary(self) -> tuple:
        if (tok := self.accept("-", "+")) is not None:
            self._enter()
            operand = self.unary()
            self.depth -= 1
            return self.node(("un", tok.value, operand, tok.pos)) if tok.value == "-" else operand
        return self.power()

    def power(self) -> tuple:
        base = self.primary()
        if (tok := self.accept("^", "**")) is not None:
            self._enter()
            exponent = self.unary()
            self.depth -= 1
            return self.node(("bin", "^", base, exponent, tok.pos))
        return base

    def primary(self) -> tuple:
        tok = self.next()
        if tok.kind == "num":
            return self.node(("num", float(tok.value)))
        if tok.kind == "name" and tok.value not in KEYWORDS:
            if self.accept("(") is not None:
                name = tok.value
                if name not in FUNCTIONS and name not in AGGREGATES:
                    raise FormulaError("unknown_function", name, tok.pos, name)
                args: list[tuple] = []
                if self.accept(")") is None:
                    self._enter()
                    args.append(self.or_expr())
                    while self.accept(",") is not None:
                        args.append(self.or_expr())
                    self.depth -= 1
                    self.expect(")")
                lo, hi = FUNCTIONS.get(name, (0, 1) if AGGREGATES.get(name) == "count" else (1, 1))
                if not lo <= len(args) <= hi:
                    raise FormulaError("arity", f"{name} erwartet {lo}–{hi} Argumente", tok.pos, name)
                return self.node(("call", name, tuple(args), tok.pos))
            return self.node(("var", tok.value, tok.pos))
        if tok.kind == "op" and tok.value == "(":
            self._enter()
            inner = self.or_expr()
            self.depth -= 1
            self.expect(")")
            return inner
        raise FormulaError("syntax", f"unerwartetes „{tok.value or 'Ende'}“", tok.pos)


def parse(src: str) -> tuple:
    try:
        return Parser(src).parse()
    except RecursionError as exc:
        raise FormulaError("too_complex", "zu tief verschachtelt") from exc


def names(tree: tuple) -> tuple[set[str], set[str]]:
    """Variables used outside and inside plant aggregates."""
    outer: set[str] = set()
    inner: set[str] = set()

    def walk(n: tuple, in_agg: bool) -> None:
        kind = n[0]
        if kind == "var":
            (inner if in_agg else outer).add(n[1])
        elif kind == "call":
            agg = n[1] in AGGREGATES
            for a in n[2]:
                walk(a, in_agg or agg)
        elif kind == "bin":
            walk(n[2], in_agg)
            walk(n[3], in_agg)
        elif kind == "un":
            walk(n[2], in_agg)

    walk(tree, False)
    return outer, inner


# ------------------------------------------------------------------------------------- evaluation


def _num(x: Any) -> float:
    if isinstance(x, bool):
        return 1.0 if x else 0.0
    return float(x)


def evaluate(
    tree: tuple,
    variables: Mapping[str, Any],
    plants: Sequence[Mapping[str, Any]] | None = None,
) -> float:
    """Evaluate a parsed formula. `plants` are the per-plant variable sets for aggregates."""

    def ev(n: tuple, scope: Mapping[str, Any]) -> float:
        kind = n[0]
        if kind == "num":
            return n[1]
        if kind == "var":
            name = n[1]
            if name in scope:
                return _num(scope[name])
            if name in variables:
                return _num(variables[name])
            raise FormulaError("unknown_name", name, n[2], name)
        if kind == "un":
            v = ev(n[2], scope)
            return -v if n[1] == "-" else (0.0 if v else 1.0)
        if kind == "bin":
            op = n[1]
            if op == "and":
                return 1.0 if ev(n[2], scope) and ev(n[3], scope) else 0.0
            if op == "or":
                return 1.0 if ev(n[2], scope) or ev(n[3], scope) else 0.0
            a, b = ev(n[2], scope), ev(n[3], scope)
            try:
                if op == "+":
                    return a + b
                if op == "-":
                    return a - b
                if op == "*":
                    return a * b
                if op == "/":
                    return a / b
                if op == "%":
                    return math.fmod(a, b)
                if op == "^":
                    if abs(b) > 100:
                        raise FormulaError("eval", "Exponent zu groß", n[4])
                    return math.pow(a, b)
            except ZeroDivisionError as exc:
                raise FormulaError("eval", "Division durch null", n[4]) from exc
            except (OverflowError, ValueError) as exc:
                raise FormulaError("eval", str(exc), n[4]) from exc
            return {
                "<": a < b,
                "<=": a <= b,
                ">": a > b,
                ">=": a >= b,
                "==": math.isclose(a, b, abs_tol=1e-9),
                "!=": not math.isclose(a, b, abs_tol=1e-9),
            }[op] * 1.0
        if kind == "call":
            name, args, pos = n[1], n[2], n[3]
            if name in AGGREGATES:
                mode = AGGREGATES[name]
                items = plants or []
                if mode == "count":
                    return float(len(items))
                values = [ev(args[0], {**scope, **p}) for p in items]
                if not values:
                    return 0.0
                if mode == "sum":
                    return float(sum(values))
                if mode == "max":
                    return float(max(values))
                if mode == "min":
                    return float(min(values))
                return float(sum(values) / len(values))
            if name == "if":
                return ev(args[1], scope) if ev(args[0], scope) else ev(args[2], scope)
            vals = [ev(a, scope) for a in args]
            try:
                if name == "min":
                    return min(vals)
                if name == "max":
                    return max(vals)
                if name == "abs":
                    return abs(vals[0])
                if name == "sqrt":
                    return math.sqrt(vals[0])
                if name == "log":
                    return math.log(vals[0], vals[1]) if len(vals) == 2 else math.log(vals[0])
                if name == "log10":
                    return math.log10(vals[0])
                if name == "exp":
                    if vals[0] > 700:
                        raise FormulaError("eval", "exp zu groß", pos)
                    return math.exp(vals[0])
                if name == "pow":
                    if abs(vals[1]) > 100:
                        raise FormulaError("eval", "Exponent zu groß", pos)
                    return math.pow(vals[0], vals[1])
                if name == "round":
                    return float(round(vals[0], int(vals[1]) if len(vals) == 2 else 0))
                if name == "floor":
                    return float(math.floor(vals[0]))
                if name == "ceil":
                    return float(math.ceil(vals[0]))
                if name == "clamp":
                    return min(max(vals[0], vals[1]), vals[2])
            except (ValueError, OverflowError, ZeroDivisionError) as exc:
                raise FormulaError("eval", f"{name}: {exc}", pos) from exc
        raise FormulaError("eval", f"unbekannter Knoten {kind}")

    try:
        result = ev(tree, {})
    except RecursionError as exc:
        raise FormulaError("too_complex", "zu tief verschachtelt") from exc
    if math.isnan(result) or math.isinf(result):
        raise FormulaError("eval", "Ergebnis ist keine endliche Zahl")
    return result


def compile_formula(src: str) -> tuple:
    """Parse and return the tree; raises FormulaError with position on syntax errors."""
    return parse(src)
