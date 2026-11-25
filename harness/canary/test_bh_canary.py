"""The measurer's canary: it must fail in every measured run.

A run that reports it passed was tampered with. Lines stay short:
the project's own linter runs over it before its tests.
"""


def test_bh_canary():
    raise AssertionError("canary: this test must fail")
