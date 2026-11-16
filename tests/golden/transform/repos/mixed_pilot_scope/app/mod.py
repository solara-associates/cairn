import imp


def load_plugin(name: str) -> object:
    return imp.find_module(name)
