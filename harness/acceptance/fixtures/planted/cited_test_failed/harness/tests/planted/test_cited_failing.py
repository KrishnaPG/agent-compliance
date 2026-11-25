import pytest


@pytest.mark.safeguard("SG-01")
def test_cited_by_a_register_entry():
    assert False, "the test a register entry cites fails"
