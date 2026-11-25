import urllib.request


def test_reaches_the_network():
    assert urllib.request.urlopen("http://example.com", timeout=3).status == 200
