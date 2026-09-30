# CSV Type Inferrer

A small Python library that scans CSV text and reports, per column, an inferred type: `int`, `float`, `date`, `boolean`, or `string`.

## Usage

```python
from csv_type_inferrer import infer_column_types, ColumnStats

csv_text = "id,name,score,active,created\n"
csv_text += "1,Alice,3.5,yes,2020-01-15\n"
csv_text += "2,Bob,4.0,no,2020/02/20\n"

columns: list[ColumnStats] = infer_column_types(csv_text)
for c in columns:
    print(c.name, c.inferred_type, c.null_count, c.non_null_count, c.total_count)
```

`infer_column_types(data: str, delimiter: str = ",", has_header: bool = True) -> list[ColumnStats]` is the only public function. `ColumnStats` exposes `name`, `inferred_type`, `null_count`, `non_null_count`, and `total_count`.

## Why this exists

The problem is mundane but recurring: given an arbitrary CSV, what are the column types so you can build a schema, route the data, or sanity-check it? Doing this with a full data frame library means pulling in NumPy or Pandas, which is a heavy dependency when all you need is a textual sniff. This library does the inference with the standard library only, at the cost of being a best-effort textual classifier rather than a real type system.

The trade-off is precision vs. weight. A value like `"007"` is reported as `int` because it matches the integer pattern, even though a human might read it as a zero-padded string ID. There is no per-column heuristic that says "this looks like an ID, keep it as a string"; that would require assumptions this library deliberately refuses to make.

## The awkward edge you will hit

A column of `0` and `1` is classified as `boolean`, not `int`, because `0` and `1` are in the boolean set and boolean is checked before int. This was a deliberate choice; if you need `0`/`1` to be an int, post-process the result: when `inferred_type == "boolean"` and the distinct non-null values are exactly `{"0", "1"}`, treat it as `int`. The library makes one decision and states it; it does not guess which you meant.

Date detection is restricted to `YYYY-MM-DD` and `YYYY/MM/DD`. `MM/DD/YYYY` is intentionally rejected because it is ambiguous across locales (`01/02/2020` is January 2 or February 1 depending on who is reading). Supporting it would mean guessing the locale, which this library refuses to do.

A value is treated as null when it is empty after stripping whitespace or equals the literal token `NULL` (case-insensitive). `NA` is not treated as null, because assuming so would silently swallow data that looks like data. Rows shorter than the header are padded with empty strings (counted as nulls); rows longer than the header have their trailing extra cells dropped.

Standard library only. No third-party dependencies. Runs under `python -m unittest discover -s tests` with `PYTHONPATH=src`.

## Performance

The window keeps a bounded buffer, so `push` is constant time and memory does not
grow with the length of the stream. `peak` and `trough` are linear in the window
size, which is the trade that keeps `push` cheap.

