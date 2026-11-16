class Obj:
    pass


def compute(a, b, keyword=None, *args, **kwargs):
    return a


x = 1
y = "two"
z = [1, 2, 3]
cfg = {"a": 1, "b": 2}
point = (1, 2)
args = [1, 2]
obj = Obj()
result = compute(x, y, *args, keyword=z, **cfg)
obj.attr = result
print(result)
