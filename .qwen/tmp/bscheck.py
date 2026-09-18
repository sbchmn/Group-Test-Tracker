import re

css = open(r"C:\Users\sbachman\OneDrive - First Dallas Media, Inc\Documents\GitHub\Group-Test-Tracker\.qwen\tmp\bs533.css", encoding="utf-8").read()
print("bytes:", len(css))

selectors = [
    ".position-relative", ".position-absolute", ".top-100", ".start-0", ".end-0",
    ".z-1000", ".overflow-auto", ".shadow", ".list-group", ".list-group-item",
    ".list-group-item-action", ".dropdown-menu", ".dropdown-item", ".btn-close",
    ".badge", ".rounded-pill", ".text-bg-light", ".form-select", ".input-group",
    ".d-none", ".d-flex", ".flex-wrap", ".gap-1", ".align-items-center", ".small",
    ".text-muted", ".border", ".fw-semibold", ".text-truncate", ".py-1", ".px-2",
    ".lh-sm", ".list-group-flush", ".rounded-3", ".bg-body", ".visible", ".w-100",
    ".text-nowrap", ".flex-grow-1", ".btn-link", ".link-opacity-75",
]
for s in selectors:
    # match the exact class token in a selector position
    pat = re.escape(s) + r"(?![\w-])"
    print(("OK   " if re.search(pat, css) else "MISS "), s)

print()
m = re.search(r"\.z-1000\{[^}]*\}", css)
print("z-1000 rule:", m.group(0) if m else None)
m = re.search(r"\.top-100\{[^}]*\}", css)
print("top-100 rule:", m.group(0) if m else None)
m = re.search(r"\.list-group-item\{[^}]*\}", css)
print("list-group-item rule:", (m.group(0)[:220] if m else None))
m = re.search(r"\.btn-close\{[^}]*\}", css)
print("btn-close rule:", (m.group(0)[:260] if m else None))
m = re.search(r"\.dropdown-menu\{[^}]*\}", css)
print("dropdown-menu rule:", (m.group(0)[:400] if m else None))
