#!/usr/bin/env python3
"""Evaluate a simple arithmetic expression safely."""

from __future__ import annotations

import ast
import operator
import sys

OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in OPS:
        return OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in OPS:
        return OPS[type(node.op)](_eval(node.operand))
    raise ValueError("unsupported expression")


def main() -> None:
    if len(sys.argv) < 2:
        print('usage: calc.py "<expression>"', file=sys.stderr)
        sys.exit(2)
    expr = sys.argv[1]
    try:
        tree = ast.parse(expr, mode="eval")
        result = _eval(tree)
    except Exception as exc:  # noqa: BLE001 - CLI surface
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    if result.is_integer():
        print(int(result))
    else:
        print(result)


if __name__ == "__main__":
    main()
