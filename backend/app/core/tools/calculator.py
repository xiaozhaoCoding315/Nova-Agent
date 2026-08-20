"""Calculator skill — safe AST-based arithmetic evaluation (no eval)."""
import ast
import math
from typing import Any

from app.core.tools.base import Tool

_ALLOWED_FUNCS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "log": math.log,
    "log2": math.log2,
    "log10": math.log10,
    "exp": math.exp,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "floor": math.floor,
    "ceil": math.ceil,
    "pow": pow,
}

_ALLOWED_BINOPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a ** b,
}

_ALLOWED_UNARY = {ast.UAdd: lambda v: +v, ast.USub: lambda v: -v}

_MAX_LEN = 200
_MAX_DEPTH = 30
_MAX_RESULT = 10 ** 100


def safe_eval(expression: str) -> Any:
    """Evaluate an arithmetic expression via whitelisted AST nodes only."""
    if not expression or len(expression) > _MAX_LEN:
        raise ValueError("expression is empty or longer than 200 characters")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"invalid expression syntax: {exc}") from exc

    def _eval(node: ast.AST, depth: int = 0) -> Any:
        if depth > _MAX_DEPTH:
            raise ValueError("expression nested too deeply")
        if isinstance(node, ast.Expression):
            return _eval(node.body, depth)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                return node.value
            raise ValueError(f"unsupported constant: {node.value!r}")
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
            left = _eval(node.left, depth + 1)
            right = _eval(node.right, depth + 1)
            value = _ALLOWED_BINOPS[type(node.op)](left, right)
            if isinstance(value, (int, float)) and abs(value) > _MAX_RESULT:
                raise ValueError("result magnitude out of allowed range")
            return value
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
            return _ALLOWED_UNARY[type(node.op)](_eval(node.operand, depth + 1))
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
                raise ValueError("function is not in the allowlist")
            if node.keywords:
                raise ValueError("keyword arguments are not supported")
            args = [_eval(a, depth + 1) for a in node.args]
            if len(args) > 8:
                raise ValueError("too many function arguments")
            return _ALLOWED_FUNCS[node.func.id](*args)
        if isinstance(node, ast.Name):
            if node.id == "pi":
                return math.pi
            if node.id == "e":
                return math.e
            raise ValueError(f"unknown identifier: {node.id}")
        raise ValueError(f"unsupported syntax node: {type(node).__name__}")

    return _eval(tree)


async def calculate(expression: str) -> dict:
    """Tool handler: evaluate the expression, returning a structured result."""
    value = safe_eval(expression)
    return {"expression": expression, "result": value}


calculator_tool = Tool(
    name="calculator",
    description=(
        "数学表达式计算器。支持加减乘除、幂、整除、取模，以及函数 "
        "sqrt/log/log2/log10/exp/sin/cos/tan/floor/ceil/pow/min/max/abs/round，"
        "常量 pi 和 e。当用户需要精确数值计算时调用。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "要计算的数学表达式，例如 (1+2)*3.5 或 sqrt(2)+log(100)",
            },
        },
        "required": ["expression"],
    },
    handler=calculate,
)
