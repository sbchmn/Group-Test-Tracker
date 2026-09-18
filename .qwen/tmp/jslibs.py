import importlib.util

for name in ("pyjsparser", "esprima", "jsparser", "dukpy", "playwright", "selenium"):
    print(name, bool(importlib.util.find_spec(name)))
