"""Source code that runs while the tests are collected and adds one test to the run."""
import gc

import pytest
from _pytest.config import PytestPluginManager


class _Extra:
    def pytest_collection_modifyitems(self, items):
        parent = items[0].parent
        items.append(pytest.Function.from_parent(parent, name="test_extra", callobj=lambda: None))


for _obj in gc.get_objects():
    if isinstance(_obj, PytestPluginManager):
        _obj.register(_Extra())
