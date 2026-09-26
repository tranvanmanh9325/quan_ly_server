"""
app/services/calculator_service.py — Safe Calculator, Database Analytics & Unit Conversion Service (R4).

Engineered for AI Agent Tieu Bao Bao:
- calculate: High-security AST visitor evaluation for mathematical expressions,
  statistical computations (mean, median, stdev), and financial math (compound interest).
  Strictly forbids raw eval(), dunder access, imports, and arbitrary execution.
- query_database: Read-only SQL executor on PostgreSQL via DatabasePoolManager.
  Strictly forbids DML/DDL mutations and query chaining (;).
  Formats query results into clean monospace ASCII tables optimized for Telegram limits (<50 rows).
- convert_units: Multi-category unit conversion (Temperature, Mass, Length, Speed, Data Size, Currency)
  with canonical normalization and localized aliases.
"""

import ast
import asyncio
from datetime import datetime, timezone
import logging
import math
import re
import statistics
from typing import Any, Dict, List, Optional, Tuple, Union

from app.core.db import get_db_dict_cursor

logger = logging.getLogger(__name__)

# Maximum recursion depth and exponent cap to prevent CPU exhaustion attacks
MAX_EXPR_LENGTH = 1000
MAX_EXPONENT = 10000
MAX_RESULT_ABS = 1e300
MAX_FACTORIAL_INPUT = 100
MAX_TELEGRAM_ROWS = 50

# ──────────────────────────────────────────────────────────────────────────────
# 1. AST Visitor Evaluation for Safe Math
# ──────────────────────────────────────────────────────────────────────────────

def _compound_interest(principal: float, rate: float, times_per_year: float = 1.0, years: float = 1.0) -> float:
    """
    Computes compound interest total future amount:
    A = P * (1 + r/n)**(n*t)
    where rate 'r' can be given as a decimal (e.g. 0.07) or percentage (>1, e.g. 7).
    """
    if rate > 1.0 and rate <= 100.0:
        # User passed rate as percentage (e.g. 7.5% -> 0.075)
        rate = rate / 100.0
    if times_per_year <= 0:
        times_per_year = 1.0
    if years < 0 or principal < 0:
        raise ValueError("Principal và số năm tính lãi kép phải không âm")
    exponent = times_per_year * years
    if exponent > MAX_EXPONENT:
        raise OverflowError("Số kỳ tính lãi kép vượt quá giới hạn an toàn")
    return float(principal * ((1.0 + (rate / times_per_year)) ** exponent))


def _safe_pow(base: Any, exp: Any, mod: Any = None) -> Any:
    """
    Safely computes base ** exp (or pow(base, exp, mod)) with strict guardrails
    against exponential CPU/memory exhaustion attacks.
    """
    if isinstance(base, bool) or isinstance(exp, bool):
        raise TypeError("Kiểu boolean không hợp lệ cho phép lũy thừa")
    if not isinstance(base, (int, float)) or not isinstance(exp, (int, float)):
        raise TypeError("Cơ số và số mũ phải là kiểu số (int/float)")

    # Exponent bounds check
    if abs(exp) > MAX_EXPONENT:
        raise OverflowError(f"Số mũ {exp} vượt quá giới hạn an toàn ({MAX_EXPONENT})")

    if abs(base) > 1 and exp > 1000:
        raise OverflowError("Số mũ vượt quá giới hạn an toàn khi cơ số > 1")

    # Base bounds check
    if abs(base) > 1e10 and exp > 2:
        raise OverflowError("Cơ số và số mũ quá lớn có nguy cơ làm treo hệ thống")

    # Modulo ternary pow handling
    if mod is not None:
        if isinstance(mod, bool) or not isinstance(mod, int):
            raise TypeError("Tham số mod trong pow(base, exp, mod) phải là số nguyên")
        if mod == 0:
            raise ZeroDivisionError("Tham số mod không được bằng 0 trong phép chia lấy dư")
        if not isinstance(base, int) or not isinstance(exp, int) or exp < 0:
            raise ValueError("pow(base, exp, mod) yêu cầu base và exp là số nguyên không âm")
        return pow(base, exp, mod)

    # Perform calculation safely
    try:
        res = base ** exp
    except OverflowError:
        raise OverflowError("Kết quả lũy thừa vượt quá giới hạn biểu diễn")

    if isinstance(res, complex):
        raise ValueError("Không hỗ trợ số phức trong biểu thức số thực")

    if abs(res) > MAX_RESULT_ABS:
        raise OverflowError("Kết quả lũy thừa vượt quá giới hạn biểu diễn")

    return res


SAFE_MATH_FUNCTIONS: Dict[str, Any] = {
    # Basic math
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "pow": _safe_pow,
    # Trigonometry & Exponential
    "sqrt": math.sqrt,
    "cbrt": math.cbrt if hasattr(math, "cbrt") else (lambda x: math.pow(x, 1 / 3.0)),
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,
    "degrees": math.degrees,
    "radians": math.radians,
    "exp": math.exp,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "ceil": math.ceil,
    "floor": math.floor,
    "factorial": lambda n: math.factorial(int(n)) if int(n) <= MAX_FACTORIAL_INPUT else (_ for _ in ()).throw(ValueError("Giai thừa n <= 100")),
    "gcd": math.gcd,
    "lcm": math.lcm if hasattr(math, "lcm") else (lambda a, b: abs(a * b) // math.gcd(a, b)),
    # Statistics
    "mean": statistics.mean,
    "median": statistics.median,
    "stdev": statistics.stdev,
    "variance": statistics.variance,
    # Financial
    "compound_interest": _compound_interest,
    "lai_kep": _compound_interest,
}

SAFE_CONSTANTS: Dict[str, float] = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau if hasattr(math, "tau") else 2.0 * math.pi,
    "inf": math.inf,
}


class SafeMathEvaluator(ast.NodeVisitor):
    """
    Evaluates arithmetic and mathematical expressions using AST walking.
    Strictly forbids unsafe nodes, attribute lookups, loops, assignments, and imports.
    """

    def visit(self, node: ast.AST) -> Any:
        method_name = f"visit_{node.__class__.__name__}"
        visitor = getattr(self, method_name, self.generic_visit)
        return visitor(node)

    def generic_visit(self, node: ast.AST) -> Any:
        raise ValueError(f"Toán tử hoặc cấu trúc không được phép: {node.__class__.__name__}")

    def visit_Expression(self, node: ast.Expression) -> Any:
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> Union[int, float, str, bool]:
        if isinstance(node.value, (int, float, str, bool)):
            return node.value
        raise ValueError(f"Kiểu dữ liệu hằng số không được phép: {type(node.value).__name__}")

    def visit_Num(self, node: ast.Num) -> Union[int, float]:  # For Python < 3.8 compatibility
        return node.n

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Union[int, float]:
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.UAdd):
            return +operand
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.Not):
            return not operand
        raise ValueError(f"Toán tử một ngôi không được hỗ trợ: {node.op.__class__.__name__}")

    def visit_BinOp(self, node: ast.BinOp) -> Union[int, float]:
        left = self.visit(node.left)
        right = self.visit(node.right)

        # Type sanity check
        if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
            raise TypeError("Phép toán số học chỉ áp dụng cho số (int/float)")

        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            res = left * right
            if abs(res) > MAX_RESULT_ABS:
                raise OverflowError("Kết quả vượt quá ngưỡng biểu diễn an toàn")
            return res
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise ZeroDivisionError("Lỗi chia cho số 0")
            return left / right
        if isinstance(node.op, ast.FloorDiv):
            if right == 0:
                raise ZeroDivisionError("Lỗi chia cho số 0")
            return left // right
        if isinstance(node.op, ast.Mod):
            if right == 0:
                raise ZeroDivisionError("Lỗi chia cho số 0 trong phép chia lấy dư (%)")
            return left % right
        if isinstance(node.op, ast.Pow):
            # Strict protection against exponential bomb attacks
            if right > MAX_EXPONENT or right < -MAX_EXPONENT:
                raise OverflowError(f"Số mũ {right} vượt quá giới hạn an toàn ({MAX_EXPONENT})")
            if abs(left) > 1 and right > 1000:
                raise OverflowError("Phép lũy thừa quá lớn có nguy cơ làm treo hệ thống")
            res = left ** right
            if isinstance(res, complex):
                raise ValueError("Không hỗ trợ số phức trong biểu thức số thực")
            if abs(res) > MAX_RESULT_ABS:
                raise OverflowError("Kết quả lũy thừa vượt quá giới hạn biểu diễn")
            return res

        raise ValueError(f"Toán tử nhị phân không được hỗ trợ: {node.op.__class__.__name__}")

    def visit_Name(self, node: ast.Name) -> Any:
        identifier = node.id
        if identifier in SAFE_CONSTANTS:
            return SAFE_CONSTANTS[identifier]
        if identifier in SAFE_MATH_FUNCTIONS:
            return SAFE_MATH_FUNCTIONS[identifier]
        raise ValueError(f"Tên hoặc biến không xác định: '{identifier}'")

    def visit_Call(self, node: ast.Call) -> Any:
        if not isinstance(node.func, ast.Name):
            raise ValueError("Cấu trúc không được phép: chỉ hỗ trợ gọi hàm toán học trực tiếp (không hỗ trợ method invocation)")

        func_name = node.func.id
        if func_name not in SAFE_MATH_FUNCTIONS:
            raise ValueError(f"Hàm toán học không nằm trong danh sách an toàn (không được phép): '{func_name}'")

        func = SAFE_MATH_FUNCTIONS[func_name]
        args = [self.visit(arg) for arg in node.args]

        # Handle kwargs if passed
        kwargs = {kw.arg: self.visit(kw.value) for kw in node.keywords if kw.arg}

        try:
            return func(*args, **kwargs)
        except (OverflowError, ZeroDivisionError):
            raise
        except Exception as exc:
            raise ValueError(f"Lỗi khi thực thi hàm {func_name}(): {str(exc)}") from exc

    def visit_List(self, node: ast.List) -> List[Any]:
        return [self.visit(elt) for elt in node.elts]

    def visit_Tuple(self, node: ast.Tuple) -> Tuple[Any, ...]:
        return tuple(self.visit(elt) for elt in node.elts)


def evaluate_expression_safely(expression: str) -> float:
    """
    Parses and evaluates a math expression string using SafeMathEvaluator.
    """
    clean_expr = expression.strip()
    if not clean_expr:
        raise ValueError("Biểu thức tính toán không được để trống")

    if len(clean_expr) > MAX_EXPR_LENGTH:
        raise ValueError(f"Biểu thức quá dài ({len(clean_expr)} ký tự > {MAX_EXPR_LENGTH})")

    # Replace carets with power operator if used as exponent (e.g. 2^10 -> 2**10)
    # But only if not part of a bitwise operation intended by user
    if "^" in clean_expr and "**" not in clean_expr:
        clean_expr = clean_expr.replace("^", "**")

    try:
        parsed_tree = ast.parse(clean_expr, mode="eval")
    except SyntaxError as syn_err:
        raise ValueError(f"Cú pháp biểu thức toán học không hợp lệ: {syn_err.msg}") from syn_err

    evaluator = SafeMathEvaluator()
    result = evaluator.visit(parsed_tree)

    if isinstance(result, (int, float)):
        return result
    raise ValueError(f"Kết quả tính toán phải là số thực hoặc nguyên, nhận được {type(result).__name__}")


# ──────────────────────────────────────────────────────────────────────────────
# 2. Database Read-Only Query Service
# ──────────────────────────────────────────────────────────────────────────────

FORBIDDEN_SQL_KEYWORDS = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "TRUNCATE",
    "ALTER",
    "CREATE",
    "GRANT",
    "REVOKE",
    "RENAME",
    "EXEC",
    "EXECUTE",
    "CALL",
    "COPY",
    "VACUUM",
    "REINDEX",
    "LOCK",
    "DO",
    "INTO",
    "SET",
    "PREPARE",
    "DEALLOCATE",
    "DISCARD",
    "TRANSACTION",
    "COMMIT",
    "ROLLBACK",
    "PG_SLEEP",
}

# Regex to detect multiple statements or SQL chaining attempts
CHAINING_REGEX = re.compile(r";")
# Regex to detect SQL block or inline comment tricks used in injection bypasses
COMMENT_REGEX = re.compile(r"(--|/\*|\*/)")
# Regex to detect pg_sleep DoS attempts
PG_SLEEP_REGEX = re.compile(r"\bpg_sleep\b", re.IGNORECASE)


def validate_read_only_sql(sql_query: str) -> str:
    """
    Validates that a SQL query is strictly read-only:
    1. Blocks multiple statements / query chaining via semicolon (;).
    2. Blocks SQL comment injection tricks.
    3. Blocks pg_sleep DoS attacks.
    4. Enforces that query starts with SELECT, EXPLAIN, WITH (ending in SELECT), or SHOW.
    5. Blocks any forbidden DML/DDL keyword across the entire query text.
    """
    clean_sql = sql_query.strip()
    if not clean_sql:
        raise ValueError("Câu truy vấn SQL không được để trống")

    if CHAINING_REGEX.search(clean_sql):
        raise ValueError("Chặn dấu chấm phẩy (;): Không được phép thực thi đa truy vấn (query chaining)")

    if COMMENT_REGEX.search(clean_sql):
        raise ValueError("Chặn comment SQL (-- hoặc /* */) để phòng tránh kỹ thuật vượt rào")

    if PG_SLEEP_REGEX.search(clean_sql):
        raise ValueError("Chặn hàm pg_sleep: Không được phép làm chậm tiến trình hoặc giữ connection pool")

    # Match initial keyword
    tokens = clean_sql.split()
    first_token = tokens[0].upper()

    allowed_starts = {"SELECT", "EXPLAIN", "WITH", "SHOW"}
    if first_token not in allowed_starts:
        raise ValueError(
            f"Chỉ cho phép các câu truy vấn đọc dữ liệu (SELECT, EXPLAIN, SHOW, WITH). "
            f"Lệnh '{first_token}' bị từ chối."
        )

    # If starts with WITH (CTE), ensure it contains a SELECT and no DML
    if first_token == "WITH":
        upper_query = clean_sql.upper()
        if "SELECT" not in upper_query:
            raise ValueError("Common Table Expression (WITH) phải kết thúc bằng lệnh SELECT")

    # Check for forbidden keywords using regex with word boundaries
    for kw in FORBIDDEN_SQL_KEYWORDS:
        pattern = rf"\b{kw}\b"
        if re.search(pattern, clean_sql, re.IGNORECASE):
            raise ValueError(f"Phát hiện từ khóa nguy hiểm bị cấm trong truy vấn đọc: '{kw}'")

    return clean_sql


def format_table_for_telegram(columns: List[str], rows: List[Dict[str, Any]]) -> str:
    """
    Formats tabular data into a clean monospace ASCII table suitable for Telegram messages.
    Clamps maximum rows to 50 and handles column width padding cleanly.
    """
    if not columns or not rows:
        return "(Không có dữ liệu trả về)"

    # Format values to strings
    display_rows: List[List[str]] = []
    for r in rows[:MAX_TELEGRAM_ROWS]:
        row_str = [str(r.get(col, "")) if r.get(col) is not None else "NULL" for col in columns]
        display_rows.append(row_str)

    # Compute column widths
    col_widths = [len(col) for col in columns]
    for row in display_rows:
        for idx, val in enumerate(row):
            col_widths[idx] = max(col_widths[idx], min(len(val), 30))  # Max cell width 30 chars

    # Build border and header
    sep_line = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"
    header_line = "| " + " | ".join(col.ljust(col_widths[idx]) for idx, col in enumerate(columns)) + " |"

    lines = [sep_line, header_line, sep_line]
    for row in display_rows:
        row_line = "| " + " | ".join(val[:30].ljust(col_widths[idx]) for idx, val in enumerate(row)) + " |"
        lines.append(row_line)
    lines.append(sep_line)

    if len(rows) > MAX_TELEGRAM_ROWS:
        lines.append(f"... (Đã giới hạn hiển thị {MAX_TELEGRAM_ROWS}/{len(rows)} dòng dữ liệu)")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# 3. Comprehensive Unit Conversion Service
# ──────────────────────────────────────────────────────────────────────────────

# Canonical Category Definitions & Conversion Rates
# All units in a category convert to a canonical Base Unit:
# - Temperature: Kelvin (K)
# - Mass: Gram (g)
# - Length: Meter (m)
# - Speed: Meter per Second (m/s)
# - Data Size: Byte (B) - binary 1024 base
# - Currency: USD ($) - estimated reference exchange rates

UNIT_CATEGORIES: Dict[str, Dict[str, Any]] = {
    "temperature": {
        "canonical": "k",
        "units": {"c", "f", "k"},
    },
    "mass": {
        "canonical": "g",
        "to_base": {
            "g": 1.0,
            "kg": 1000.0,
            "mg": 0.001,
            "lb": 453.59237,
            "oz": 28.349523125,
            "ton": 1000000.0,
            "tan": 1000000.0,
        },
    },
    "length": {
        "canonical": "m",
        "to_base": {
            "m": 1.0,
            "km": 1000.0,
            "cm": 0.01,
            "mm": 0.001,
            "mi": 1609.344,
            "mile": 1609.344,
            "ft": 0.3048,
            "foot": 0.3048,
            "feet": 0.3048,
            "in": 0.0254,
            "inch": 0.0254,
            "yd": 0.9144,
            "yard": 0.9144,
        },
    },
    "speed": {
        "canonical": "m/s",
        "to_base": {
            "m/s": 1.0,
            "km/h": 1.0 / 3.6,
            "kph": 1.0 / 3.6,
            "mph": 0.44704,
            "knot": 0.51444444444,
            "kn": 0.51444444444,
        },
    },
    "data_size": {
        "canonical": "b",
        "to_base": {
            "b": 1.0,
            "byte": 1.0,
            "bytes": 1.0,
            "kb": 1024.0,
            "kib": 1024.0,
            "mb": 1024.0 ** 2,
            "mib": 1024.0 ** 2,
            "gb": 1024.0 ** 3,
            "gib": 1024.0 ** 3,
            "tb": 1024.0 ** 4,
            "tib": 1024.0 ** 4,
            "pb": 1024.0 ** 5,
            "pib": 1024.0 ** 5,
        },
    },
    "currency": {
        "canonical": "usd",
        "to_base": {
            "usd": 1.0,
            "vnd": 1.0 / 25400.0,
            "eur": 1.08,
            "jpy": 1.0 / 155.0,
            "gbp": 1.28,
            "cny": 1.0 / 7.25,
            "sgd": 1.0 / 1.35,
            "krw": 1.0 / 1380.0,
            "cad": 1.0 / 1.37,
            "aud": 1.0 / 1.52,
        },
    },
}

# Unit Alias Mapping for natural language flexibility
UNIT_ALIASES: Dict[str, str] = {
    # Temperature
    "c": "c",
    "celsius": "c",
    "độ c": "c",
    "do c": "c",
    "f": "f",
    "fahrenheit": "f",
    "độ f": "f",
    "do f": "f",
    "k": "k",
    "kelvin": "k",
    # Mass
    "g": "g",
    "gram": "g",
    "gam": "g",
    "kg": "kg",
    "kilogram": "kg",
    "kilo": "kg",
    "ký": "kg",
    "ky": "kg",
    "mg": "mg",
    "milligram": "mg",
    "lb": "lb",
    "lbs": "lb",
    "pound": "lb",
    "pounds": "lb",
    "oz": "oz",
    "ounce": "oz",
    "ton": "ton",
    "tấn": "ton",
    "tan": "ton",
    # Length
    "m": "m",
    "meter": "m",
    "mét": "m",
    "met": "m",
    "km": "km",
    "kilometer": "km",
    "cây số": "km",
    "cay so": "km",
    "cm": "cm",
    "centimeter": "cm",
    "mm": "mm",
    "millimeter": "mm",
    "mi": "mi",
    "mile": "mi",
    "miles": "mi",
    "dặm": "mi",
    "dam": "mi",
    "ft": "ft",
    "foot": "ft",
    "feet": "ft",
    "in": "in",
    "inch": "in",
    "inches": "in",
    "yd": "yd",
    "yard": "yd",
    "yards": "yd",
    # Speed
    "m/s": "m/s",
    "km/h": "km/h",
    "kph": "km/h",
    "kmh": "km/h",
    "mph": "mph",
    "knot": "knot",
    "knots": "knot",
    "kn": "knot",
    "hải lý/h": "knot",
    # Data size
    "b": "b",
    "byte": "b",
    "bytes": "b",
    "kb": "kb",
    "kib": "kb",
    "kilobyte": "kb",
    "mb": "mb",
    "mib": "mb",
    "megabyte": "mb",
    "gb": "gb",
    "gib": "gb",
    "gigabyte": "gb",
    "tb": "tb",
    "tib": "tb",
    "terabyte": "tb",
    "pb": "pb",
    "pib": "pb",
    "petabyte": "pb",
    # Currency
    "usd": "usd",
    "đô": "usd",
    "do": "usd",
    "đô la": "usd",
    "$": "usd",
    "vnd": "vnd",
    "vnđ": "vnd",
    "đồng": "vnd",
    "dong": "vnd",
    "đ": "vnd",
    "d": "vnd",
    "eur": "eur",
    "euro": "eur",
    "€": "eur",
    "jpy": "jpy",
    "yen": "jpy",
    "yên": "jpy",
    "¥": "jpy",
    "gbp": "gbp",
    "bảng": "gbp",
    "bang": "gbp",
    "£": "gbp",
    "cny": "cny",
    "tệ": "cny",
    "te": "cny",
    "sgd": "sgd",
    "krw": "krw",
    "won": "krw",
    "₩": "krw",
    "cad": "cad",
    "aud": "aud",
}


def _resolve_unit(raw_unit: str) -> str:
    """Normalizes raw unit string via alias dictionary."""
    cleaned = raw_unit.strip().lower()
    return UNIT_ALIASES.get(cleaned, cleaned)


def _find_unit_category(unit: str) -> Optional[str]:
    """Finds the category of a given normalized unit."""
    for category, cat_data in UNIT_CATEGORIES.items():
        if category == "temperature":
            if unit in cat_data["units"]:
                return category
        else:
            if unit in cat_data["to_base"]:
                return category
    return None


def execute_unit_conversion(value: float, from_unit: str, to_unit: str) -> Dict[str, Any]:
    """
    Executes conversion logic across units and categories.
    """
    norm_from = _resolve_unit(from_unit)
    norm_to = _resolve_unit(to_unit)

    cat_from = _find_unit_category(norm_from)
    cat_to = _find_unit_category(norm_to)

    if not cat_from:
        raise ValueError(f"Đơn vị nguồn '{from_unit}' không được hỗ trợ hoặc không nhận diện được")
    if not cat_to:
        raise ValueError(f"Đơn vị đích '{to_unit}' không được hỗ trợ hoặc không nhận diện được")

    if cat_from != cat_to:
        raise ValueError(
            f"Không thể chuyển đổi giữa hai nhóm đơn vị khác nhau: "
            f"'{from_unit}' ({cat_from}) sang '{to_unit}' ({cat_to})"
        )

    category = cat_from

    # 1. Temperature conversion
    if category == "temperature":
        # Convert from origin to Kelvin
        if norm_from == "c":
            kelvin = value + 273.15
        elif norm_from == "f":
            kelvin = (value - 32.0) * 5.0 / 9.0 + 273.15
        elif norm_from == "k":
            kelvin = value
        else:
            raise ValueError(f"Đơn vị nhiệt độ không xác định: {norm_from}")

        # Convert Kelvin to target
        if norm_to == "c":
            res = kelvin - 273.15
        elif norm_to == "f":
            res = (kelvin - 273.15) * 9.0 / 5.0 + 32.0
        elif norm_to == "k":
            res = kelvin
        else:
            raise ValueError(f"Đơn vị nhiệt độ không xác định: {norm_to}")

    # 2. Linear ratio-based conversion (Mass, Length, Speed, Data Size, Currency)
    else:
        to_base_map = UNIT_CATEGORIES[category]["to_base"]
        rate_from = to_base_map[norm_from]
        rate_to = to_base_map[norm_to]

        # Convert to base unit then to target unit
        base_val = value * rate_from
        res = base_val / rate_to

    # Formatting helper
    if category == "currency":
        formatted = f"{res:,.2f} {norm_to.upper()}"
    elif abs(res) >= 1e6 or (0 < abs(res) < 1e-4):
        formatted = f"{res:.6e} {norm_to}"
    else:
        formatted = f"{round(res, 6):g} {norm_to}"

    return {
        "status": "success",
        "value": value,
        "from_unit": from_unit,
        "to_unit": to_unit,
        "normalized_from": norm_from,
        "normalized_to": norm_to,
        "result": res,
        "formatted": formatted,
        "category": category,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 4. Service Class & Interface Contracts
# ──────────────────────────────────────────────────────────────────────────────

class CalculatorService:
    """
    Sub-service for Calculator, Database Analytics, and Unit Conversion (R4).
    """

    async def calculate(self, expression: str) -> Dict[str, Any]:
        """
        Safely computes complex math expressions, statistical metrics, or compound interest.
        """
        if not expression or not expression.strip():
            return {
                "status": "error",
                "message": "Biểu thức tính toán không được để trống",
                "expression": expression,
            }

        try:
            # Run AST evaluation in thread pool to prevent CPU stall on large operations
            result = await asyncio.to_thread(evaluate_expression_safely, expression)
            formatted = f"{result:,.6f}".rstrip("0").rstrip(".") if isinstance(result, float) else f"{result:,}"
            return {
                "status": "success",
                "expression": expression,
                "result": result,
                "formatted": formatted,
            }
        except ZeroDivisionError:
            return {
                "status": "error",
                "message": "Lỗi chia cho số 0 trong biểu thức",
                "expression": expression,
            }
        except OverflowError as ofe:
            return {
                "status": "error",
                "message": f"Lỗi tràn số: {str(ofe)}",
                "expression": expression,
            }
        except Exception as exc:
            logger.warning("[CalculatorService] Expression evaluation failed: %s — %s", expression, exc)
            return {
                "status": "error",
                "message": f"Lỗi tính toán: {str(exc)}",
                "expression": expression,
            }

    async def query_database(self, sql_query: str, database: str = "postgres") -> Dict[str, Any]:
        """
        Executes a read-only SQL query on PostgreSQL and returns a formatted ASCII table.
        Strictly prevents DML/DDL operations and chaining.
        """
        try:
            valid_sql = validate_read_only_sql(sql_query)
        except ValueError as val_err:
            return {
                "status": "error",
                "message": f"Từ chối truy vấn bảo mật: {str(val_err)}",
                "query": sql_query,
            }

        start_time = datetime.now(timezone.utc)
        try:
            async with get_db_dict_cursor() as cur:
                await cur.execute(valid_sql)
                # Fetch up to MAX_TELEGRAM_ROWS + 1 to detect truncation
                rows = await cur.fetchmany(MAX_TELEGRAM_ROWS + 1)
                columns = [desc[0] for desc in cur.description] if cur.description else []

            total_fetched = len(rows)
            is_truncated = total_fetched > MAX_TELEGRAM_ROWS
            final_rows = rows[:MAX_TELEGRAM_ROWS]

            table_text = format_table_for_telegram(columns, final_rows)
            duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

            return {
                "status": "success",
                "database": database,
                "query": valid_sql,
                "row_count": len(final_rows),
                "total_rows_sampled": total_fetched,
                "truncated": is_truncated,
                "columns": columns,
                "rows": final_rows,
                "formatted_table": table_text,
                "duration_ms": round(duration_ms, 2),
            }
        except Exception as exc:
            logger.error("[CalculatorService] Database query error: %s", exc)
            return {
                "status": "error",
                "message": f"Lỗi thực thi truy vấn cơ sở dữ liệu: {str(exc)}",
                "query": sql_query,
            }

    async def convert_units(self, value: float, from_unit: str, to_unit: str) -> Dict[str, Any]:
        """
        Converts a numeric value from one unit to another across supported categories.
        """
        try:
            val_float = float(value)
        except (ValueError, TypeError):
            return {
                "status": "error",
                "message": f"Giá trị chuyển đổi không phải số hợp lệ: {value}",
            }

        try:
            res = execute_unit_conversion(val_float, from_unit, to_unit)
            return res
        except Exception as exc:
            return {
                "status": "error",
                "message": f"Lỗi chuyển đổi đơn vị: {str(exc)}",
                "value": value,
                "from_unit": from_unit,
                "to_unit": to_unit,
            }


# Module-level singletons and interface functions for direct dispatcher routing
calculator_service = CalculatorService()


async def calculate(expression: str) -> Dict[str, Any]:
    return await calculator_service.calculate(expression)


async def query_database(sql_query: str, database: str = "postgres") -> Dict[str, Any]:
    return await calculator_service.query_database(sql_query, database)


async def convert_units(value: float, from_unit: str, to_unit: str) -> Dict[str, Any]:
    return await calculator_service.convert_units(value, from_unit, to_unit)
