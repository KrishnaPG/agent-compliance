from packaging.version import Version


def newer(a, b):
    return Version(a) > Version(b)
