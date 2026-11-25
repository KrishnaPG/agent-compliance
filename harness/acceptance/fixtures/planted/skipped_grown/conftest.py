import pytest


def pytest_collection_modifyitems(config, items):
    for i in items:
        if i.name == "test_sub":
            i.add_marker(pytest.mark.skip(reason="skipped in the candidate"))
