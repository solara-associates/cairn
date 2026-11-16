x = 1
y = "two"
z = [1, 2, 3]
cfg = {"a": 1, "b": 2}
point = (1, 2)
result = compute(x, y, keyword=z, *args, **cfg)
obj.attr.nested = result
print(result)
