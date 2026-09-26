import unittest

from csv_type_inferrer import infer_column_types, ColumnStats


class TestHappyPath(unittest.TestCase):
    def test_mixed_columns(self):
        csv_text = "id,name,score,active,created\n"
        csv_text += "1,Alice,3.5,yes,2020-01-15\n"
        csv_text += "2,Bob,4.0,no,2020/02/20\n"
        csv_text += "3,Carol,5,true,2020-03-30\n"
        results = infer_column_types(csv_text)
        self.assertEqual(len(results), 5)
        self.assertEqual(results[0].name, "id")
        self.assertEqual(results[0].inferred_type, "int")
        self.assertEqual(results[1].inferred_type, "string")
        self.assertEqual(results[2].inferred_type, "float")
        self.assertEqual(results[3].inferred_type, "boolean")
        self.assertEqual(results[4].inferred_type, "date")


class TestTypeRules(unittest.TestCase):
    def test_int_with_signs(self):
        csv_text = "v\n+1\n-2\n3\n"
        r = infer_column_types(csv_text)[0]
        self.assertEqual(r.inferred_type, "int")
        self.assertEqual(r.non_null_count, 3)
        self.assertEqual(r.null_count, 0)

    def test_float_variants(self):
        csv_text = "v\n1.5\n.5\n1.\n-3.2\n1e10\n1.2E-3\n+0.0\n"
        r = infer_column_types(csv_text)[0]
        self.assertEqual(r.inferred_type, "float")

    def test_float_mixed_with_int_stays_float(self):
        csv_text = "v\n1\n2.5\n"
        r = infer_column_types(csv_text)[0]
        self.assertEqual(r.inferred_type, "float")

    def test_boolean_set(self):
        csv_text = "v\ntrue\nfalse\nyes\nno\ny\nn\nt\nf\n0\n1\n"
        r = infer_column_types(csv_text)[0]
        self.assertEqual(r.inferred_type, "boolean")

    def test_boolean_takes_precedence_over_int(self):
        # "0" and "1" are in the boolean set. If a column is ONLY those,
        # it is classified as boolean, not int. This is the chosen rule and is tested here.
        csv_text = "v\n0\n1\n1\n0\n"
        r = infer_column_types(csv_text)[0]
        self.assertEqual(r.inferred_type, "boolean")

    def test_int_takes_precedence_over_float(self):
        csv_text = "v\n1\n2\n3\n"
        r = infer_column_types(csv_text)[0]
        self.assertEqual(r.inferred_type, "int")

    def test_date_iso_and_slash(self):
        csv_text = "v\n2020-01-15\n2020/02/20\n"
        r = infer_column_types(csv_text)[0]
        self.assertEqual(r.inferred_type, "date")

    def test_date_rejects_invalid_month(self):
        csv_text = "v\n2020-13-01\n"
        r = infer_column_types(csv_text)[0]
        self.assertEqual(r.inferred_type, "string")

    def test_date_rejects_ambiguous_md_format(self):
        # MM/DD/YYYY is deliberately NOT supported.
        csv_text = "v\n01/02/2020\n"
        r = infer_column_types(csv_text)[0]
        self.assertEqual(r.inferred_type, "string")

    def test_garbage_is_string(self):
        csv_text = "v\nhello\nworld\n"
        r = infer_column_types(csv_text)[0]
        self.assertEqual(r.inferred_type, "string")

    def test_mixed_types_fall_to_string(self):
        csv_text = "v\n1\n2.5\n2020-01-01\nfoo\n"
        r = infer_column_types(csv_text)[0]
        self.assertEqual(r.inferred_type, "string")

    def test_int_with_letter_is_string(self):
        csv_text = "v\n123abc\n"
        r = infer_column_types(csv_text)[0]
        self.assertEqual(r.inferred_type, "string")

    def test_huge_int_is_still_int(self):
        # Python ints are arbitrary precision; textual match is enough, no overflow.
        big = "9" * 100
        csv_text = f"v\n{big}\n"
        r = infer_column_types(csv_text)[0]
        self.assertEqual(r.inferred_type, "int")


class TestNulls(unittest.TestCase):
    def test_empty_and_null_token_are_nulls(self):
        csv_text = "v\n1\n2\n\nNULL\n"
        r = infer_column_types(csv_text)[0]
        self.assertEqual(r.inferred_type, "int")
        self.assertEqual(r.non_null_count, 2)
        self.assertEqual(r.null_count, 2)
        self.assertEqual(r.total_count, 4)

    def test_all_null_is_string(self):
        csv_text = "v\n\n\nNULL\n"
        r = infer_column_types(csv_text)[0]
        self.assertEqual(r.inferred_type, "string")
        self.assertEqual(r.non_null_count, 0)
        self.assertEqual(r.null_count, 3)

    def test_null_token_case_insensitive(self):
        csv_text = "v\nnull\nNull\n5\n"
        r = infer_column_types(csv_text)[0]
        self.assertEqual(r.inferred_type, "int")
        self.assertEqual(r.null_count, 2)

    def test_whitespace_only_is_null(self):
        csv_text = "v\n  \n5\n"
        r = infer_column_types(csv_text)[0]
        self.assertEqual(r.inferred_type, "int")
        self.assertEqual(r.null_count, 1)

    def test_na_is_not_null(self):
        # "NA" is NOT a null token by deliberate choice.
        csv_text = "v\n1\nNA\n"
        r = infer_column_types(csv_text)[0]
        self.assertEqual(r.inferred_type, "string")
        self.assertEqual(r.non_null_count, 2)
        self.assertEqual(r.null_count, 0)


class TestParsing(unittest.TestCase):
    def test_quoted_field_with_comma(self):
        csv_text = 'id,name\n1,"Smith, Jr."\n2,"Jones"\n'
        results = infer_column_types(csv_text)
        self.assertEqual(results[0].inferred_type, "int")
        self.assertEqual(results[1].inferred_type, "string")

    def test_embedded_newline_in_quoted_field(self):
        csv_text = 'id,note\n1,"line1\nline2"\n2,"single"\n'
        results = infer_column_types(csv_text)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].inferred_type, "int")
        self.assertEqual(results[1].inferred_type, "string")

    def test_trailing_newline(self):
        csv_text = "id\n1\n2\n"
        r = infer_column_types(csv_text)[0]
        self.assertEqual(r.inferred_type, "int")
        self.assertEqual(r.total_count, 2)

    def test_no_header(self):
        csv_text = "1\n2\n3\n"
        results = infer_column_types(csv_text, has_header=False)
        self.assertEqual(results[0].name, "column_0")
        self.assertEqual(results[0].inferred_type, "int")

    def test_empty_header_cell_gets_name(self):
        csv_text = "a,,c\n1,2,3\n"
        results = infer_column_types(csv_text)
        self.assertEqual(results[0].name, "a")
        self.assertEqual(results[1].name, "column_1")
        self.assertEqual(results[2].name, "c")

    def test_duplicate_headers_get_suffix(self):
        csv_text = "v,v,v\n1,2,3\n"
        results = infer_column_types(csv_text)
        self.assertEqual([r.name for r in results], ["v", "v_1", "v_2"])

    def test_short_rows_padded_with_nulls(self):
        csv_text = "a,b\n1,\n2\n"
        results = infer_column_types(csv_text)
        self.assertEqual(results[0].inferred_type, "int")
        self.assertEqual(results[0].non_null_count, 2)
        self.assertEqual(results[1].inferred_type, "string")
        self.assertEqual(results[1].null_count, 2)

    def test_long_rows_truncated_to_header_width(self):
        csv_text = "a,b\n1,2,3,4\n5,6\n"
        results = infer_column_types(csv_text)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].non_null_count, 2)
        self.assertEqual(results[1].non_null_count, 2)

    def test_pipe_delimiter(self):
        csv_text = "a|b\n1|x\n2|y\n"
        results = infer_column_types(csv_text, delimiter="|")
        self.assertEqual(results[0].inferred_type, "int")
        self.assertEqual(results[1].inferred_type, "string")

    def test_empty_input(self):
        self.assertEqual(infer_column_types(""), [])

    def test_header_only(self):
        csv_text = "a,b,c\n"
        results = infer_column_types(csv_text)
        self.assertEqual(len(results), 3)
        for r in results:
            self.assertEqual(r.inferred_type, "string")
            self.assertEqual(r.total_count, 0)
            self.assertEqual(r.non_null_count, 0)

    def test_bad_delimiter_raises(self):
        with self.assertRaises(ValueError):
            infer_column_types("a,b\n1,2\n", delimiter=";;")

    def test_non_string_data_raises(self):
        with self.assertRaises(TypeError):
            infer_column_types(b"a,b\n1,2\n")


class TestStatsAndStruct(unittest.TestCase):
    def test_counts(self):
        csv_text = "v\n1\n2\n\n3\n"
        r = infer_column_types(csv_text)[0]
        self.assertEqual(r.total_count, 4)
        self.assertEqual(r.non_null_count, 3)
        self.assertEqual(r.null_count, 1)

    def test_repr(self):
        csv_text = "v\n1\n"
        r = infer_column_types(csv_text)[0]
        s = repr(r)
        self.assertIn("ColumnStats", s)
        self.assertIn(r.inferred_type, s)

    def test_equality(self):
        a = ColumnStats("x", "int")
        a.total_count = 1
        a.non_null_count = 1
        b = ColumnStats("x", "int")
        b.total_count = 1
        b.non_null_count = 1
        self.assertEqual(a, b)
        b.inferred_type = "string"
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, "not a stats")


if __name__ == "__main__":
    unittest.main()
