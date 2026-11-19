from csv_reader import read_rows


def test_header_keys_rows():
    assert read_rows("a,b\n1,2\n3,4\n") == [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]


def test_quoted_comma_and_newline():
    assert read_rows('a,b\n"x,y","l1\nl2"\n') == [{"a": "x,y", "b": "l1\nl2"}]
