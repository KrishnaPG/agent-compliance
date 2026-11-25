"""The measurer's canary: it must fail in every measured run; a run that reports it passed was tampered with."""


def test_bh_canary():
    raise AssertionError("canary: this test must fail")
