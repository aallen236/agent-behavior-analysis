from text_utils import slugify


def test_basic():
    assert slugify("Hello World") == "hello-world"


def test_punctuation():
    assert slugify("Hello, World!") == "hello-world"


def test_multiple_spaces():
    assert slugify("a   b") == "a-b"


def test_strip_edges():
    assert slugify("  --Hi, there!--  ") == "hi-there"


def test_numbers():
    assert slugify("Python 3.12 Release") == "python-3-12-release"


def test_empty():
    assert slugify("") == ""


def test_only_symbols():
    assert slugify("!!!") == ""
