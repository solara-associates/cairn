class WidgetMeta(type):
    pass


class Base:
    pass


class Widget(Base, metaclass=WidgetMeta):
    """A widget."""

    kind: str = "generic"

    def __init__(self, name):
        self.name = name
        self.tags = ["default"]

    def describe(self):
        return self.name
