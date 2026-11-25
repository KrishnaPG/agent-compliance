import os


def test_writes_outside():
    with open(os.path.join(os.environ["ATDD_OUTSIDE"], "escaped.txt"), "w") as f:
        f.write("escaped\n")
