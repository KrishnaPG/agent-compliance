"""Mutation: the guard that keeps unmet candidates and protected paths out of HEAD is removed."""
import bhcore


def _no_guard(*args, **kwargs):
    return None


for _name in ("_restore_guarded",):
    if hasattr(bhcore, _name):
        setattr(bhcore, _name, _no_guard)
