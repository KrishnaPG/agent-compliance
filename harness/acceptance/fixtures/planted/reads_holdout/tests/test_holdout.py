from pathlib import Path


def test_reads_holdout():
    assert Path("holdout_files/answers.json").read_text()
