def combine(a, b):
    return a


def add(a: int, b: int = 0) -> int:
    total = combine(a, b)
    return total


def collect(*args, **kwargs):
    pass
