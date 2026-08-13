import datetime
from typing import Dict, Any

try:
    from sympy import sympify, N, SympifyError
    HAS_SYMPY = True
except ImportError:
    HAS_SYMPY = False


skill_info = {
    "name": "calculator",
    "description": "计算器技能，使用 sympy 提供数学计算功能，支持表达式求值",
    "functions": {
        "calculate": {
            "description": "计算数学表达式。支持加减乘除、幂运算、三角函数、对数、阶乘等。示例: '2+3*4', 'sqrt(16)', 'sin(pi/2)', 'log(100, 10)', 'factorial(5)'",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "数学表达式，如 '2+3*4' 或 'sin(pi/2)'"}
                },
                "required": ["expression"]
            }
        },
        "get_current_time": {
            "description": "获取当前时间",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }
}


def calculate(expression: str) -> Dict[str, Any]:
    if not HAS_SYMPY:
        return {
            "success": False,
            "error": "sympy is not installed, please run pip install sympy",
            "user_output": {"label": "Calculator", "parts": [{"text": expression}, {"text": "Error", "style": "red"}]}
        }

    try:
        expr = sympify(expression)
        sympy_result = N(expr)

        if sympy_result == int(sympy_result):
            result = int(sympy_result)
        else:
            result = float(sympy_result)

        return {
            "success": True,
            "expression": expression,
            "result": result,
            "user_output": {"label": "Calculator", "parts": [{"text": expression}, {"text": f"= {result}", "style": "green"}]}
        }
    except SympifyError:
        return {
            "success": False,
            "error": f"Unable to parse expression: {expression}",
            "user_output": {"label": "Calculator", "parts": [{"text": expression}, {"text": "Error", "style": "red"}]}
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Calculation failed: {str(e)}",
            "user_output": {"label": "Calculator", "parts": [{"text": expression}, {"text": "Error", "style": "red"}]}
        }


def get_current_time() -> Dict[str, Any]:
    time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "success": True,
        "time": time_str,
        "user_output": {"label": "Calculator", "parts": [{"text": "--time"}, {"text": time_str, "style": "gray"}]}
    }
