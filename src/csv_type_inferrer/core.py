import csv
import io
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Precompiled patterns. Kept strict on purpose: "123abc" must NOT be an int,
# and "1e5" IS a float. Compiling once avoids recompiling per-row in large files.

_INT_RE = re.compile(r"^[+-]?\d+$")

# Float: optional sign, digits with optional decimal, optional exponent.
# Accepts "1.5", ".5", "1.", "-3", "1e10", "1.2E-3", "+0.0".
# A bare "." is rejected by requiring at least one digit somewhere.
_FLOAT_RE = re.compile(
    r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$"
)

# Two date shapes only: ISO "YYYY-MM-DD" and a fixed "YYYY/MM/DD".
# We deliberately reject "MM/DD/YYYY" because it is ambiguous
# (01/02/2020 is Jan 2 in the US, Feb 1 in Europe). One interpretation, stated plainly.
_DATE_PATTERNS = ("%Y-%m-%d", "%Y/%m/%d")

_TRUE_STRINGS = {"true", "yes", "y", "t", "1"}
_FALSE_STRINGS = {"false", "no", "n", "f", "0"}


class ColumnStats:
    """Per-column inference result.

    Attributes:
        name: header name (or positional string when the CSV had no header).
        inferred_type: one of "int", "float", "date", "boolean", "string".
        null_count: how many values were empty or the literal "NULL".
        non_null_count: number of values considered non-null.
        total_count: null_count + non_null_count (i.e. number of rows seen).
    """

    __slots__ = (
        "name",
        "inferred_type",
        "null_count",
        "non_null_count",
        "total_count",
    )

    def __init__(self, name: str, inferred_type: str):
        self.name = name
        self.inferred_type = inferred_type
        self.null_count = 0
        self.non_null_count = 0
        self.total_count = 0

    def __repr__(self) -> str:
        return (
            f"ColumnStats(name={self.name!r}, inferred_type={self.inferred_type!r}, "
            f"null_count={self.null_count}, non_null_count={self.non_null_count}, "
            f"total_count={self.total_count})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ColumnStats):
            return NotImplemented
        return (
            self.name == other.name
            and self.inferred_type == other.inferred_type
            and self.null_count == other.null_count
            and self.non_null_count == other.non_null_count
            and self.total_count == other.total_count
        )

    def __hash__(self) -> int:
        return hash((
            self.name,
            self.inferred_type,
            self.null_count,
            self.non_null_count,
            self.total_count,
        ))


def _is_null(value: str) -> bool:
    # Treat truly empty (post-strip) values and the literal token "NULL" (case-insensitive)
    # as null. "NA" is NOT treated as null because it looks too much like data to assume.
    v = value.strip()
    return v == "" or v.upper() == "NULL"


def _is_int(value: str) -> bool:
    return bool(_INT_RE.match(value.strip()))


def _is_float(value: str) -> bool:
    # Reject a bare sign or bare ".". The pattern already requires a digit, but this guard
    # makes the intent explicit and defends against future regex edits.
    v = value.strip()
    if v in ("", "+", "-", "."):
        return False
    return bool(_FLOAT_RE.match(v))


def _is_boolean(value: str) -> bool:
    v = value.strip().lower()
    return v in _TRUE_STRINGS or v in _FALSE_STRINGS


def _is_date(value: str) -> bool:
    v = value.strip()
    for fmt in _DATE_PATTERNS:
        try:
            # strptime accepts values that match the format; we still parse to validate
            # (e.g. month=13 must fail).
            datetime.strptime(v, fmt)
            return True
        except ValueError:
            continue
    return False


# Order matters: we check the most specific types first. An int is also a valid float and
# a boolean "0"/"1" looks like an int, so we narrow-to-widen: boolean -> int -> float -> date.
_CANDIDATES: Tuple = (
    ("boolean", _is_boolean),
    ("int", _is_int),
    ("float", _is_float),
    ("date", _is_date),
)


def _infer_column(values: List[str]) -> str:
    """Return the inferred type for one column's non-null values.

    Returns "string" when no narrower type covers every non-null value, or when the
    column is entirely null (we cannot know the type of an all-null column).
    """
    non_null = [v for v in values if not _is_null(v)]
    if not non_null:
        return "string"

    for type_name, predicate in _CANDIDATES:
        if all(predicate(v) for v in non_null):
            return type_name
    return "string"


def _split_csv(
    data: str,
    delimiter: str,
    has_header: bool,
) -> Tuple[Optional[List[str]], List[List[str]]]:
    reader = csv.reader(io.StringIO(data), delimiter=delimiter)
    rows: List[List[str]] = list(reader)
    # csv.reader yields [] for a truly empty input and for a single trailing newline.
    # Treat those as "no rows" so callers see an empty header + no columns.
    if not rows:
        return None, []

    if has_header:
        header = rows[0]
        body = rows[1:]
    else:
        header = None
        body = rows
    return header, body


def _normalize_header(header: List[str], ncols: int) -> List[str]:
    """Ensure every column has a unique, non-empty name.

    Empty header cells become "column_<i>". Duplicates are suffixed with an index so
    callers can address each column unambiguously by name.
    """
    seen: Dict[str, int] = {}
    out: List[str] = []
    for i, cell in enumerate(header):
        base = cell.strip() if cell else ""
        if base == "":
            base = f"column_{i}"
        if base in seen:
            seen[base] += 1
            base = f"{base}_{seen[base]}"
        else:
            seen[base] = 0
        out.append(base)
    return out


def _transpose(body: List[List[str]], ncols: int) -> List[List[str]]:
    cols: List[List[str]] = [[] for _ in range(ncols)]
    for row in body:
        for i in range(ncols):
            cols[i].append(row[i] if i < len(row) else "")
    return cols


def infer_column_types(
    data: str,
    delimiter: str = ",",
    has_header: bool = True,
) -> List[ColumnStats]:
    """Infer per-column types from CSV text.

    Args:
        data: CSV text. May contain quoted fields, embedded commas, embedded newlines,
              and a trailing newline.
        delimiter: Single-character field separator passed to csv.reader. Defaults to ",".
        has_header: When True (default), the first row is treated as headers. When False,
                    columns are named "column_0", "column_1", ...

    Returns:
        A list of ColumnStats, one per column, in left-to-right order. The width is the
        width of the header row (or the first data row when has_header is False). Rows
        narrower than the width are padded with empty strings, which count as nulls.
        Rows wider than the width have their trailing extra cells dropped.

    A value is treated as null when it is empty after stripping whitespace or equals the
    literal token "NULL" (case-insensitive). Whitespace around values is ignored for the
    purposes of type matching.

    Type precedence (most specific first): boolean, int, float, date, string.
      - boolean: one of {true,false,yes,no,y,n,t,f,0,1} (case-insensitive).
      - int: optional sign followed by digits only.
      - float: optional sign, digits with optional decimal point, optional exponent.
      - date: YYYY-MM-DD or YYYY/MM/DD. Both fields of the month/day must be valid
              (e.g. 2020-13-01 is rejected).
      - string: anything else, or when the column is entirely null.

    Ints that overflow Python's int range are still classified as int: Python ints are
    arbitrary precision and the regex match is purely textual, so there is no overflow.
    """
    if not isinstance(data, str):
        raise TypeError("data must be str")
    if len(delimiter) != 1:
        raise ValueError("delimiter must be a single character")

    header, body = _split_csv(data, delimiter, has_header)

    if header is None:
        if not body:
            return []
        ncols = len(body[0])
        header = [f"column_{i}" for i in range(ncols)]
    else:
        ncols = len(header)
        header = _normalize_header(header, ncols)

    if ncols == 0:
        return []

    columns = _transpose(body, ncols)
    results: List[ColumnStats] = []
    for name, values in zip(header, columns):
        inferred = _infer_column(values)
        stats = ColumnStats(name=name, inferred_type=inferred)
        for v in values:
            stats.total_count += 1
            if _is_null(v):
                stats.null_count += 1
            else:
                stats.non_null_count += 1
        results.append(stats)
    return results
