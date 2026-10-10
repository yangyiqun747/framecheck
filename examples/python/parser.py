"""Replace this factory with a wrapper around your real streaming parser."""

from framecheck.protocol import DemoParser


def create_parser():
    return DemoParser()
