import re

css = open(r"C:\Users\sbachman\OneDrive - First Dallas Media, Inc\Documents\GitHub\Group-Test-Tracker\.qwen\tmp\bs533.css", encoding="utf-8").read()

print("== all .z-* helper selectors ==")
print(sorted(set(re.findall(r"\.z-[0-9nN][0-9\w-]*", css))))

print("\n== dropdown-menu full rule ==")
for m in re.finditer(r"^[^{}]*\.dropdown-menu[^{}]*\{[^}]*\}", css):
    print(m.group(0)[:900], "\n---")

print("\n== .show rule(s) ==")
for m in re.finditer(r"^[^{}]*\.show[^{}]*\{[^}]*\}", css):
    txt = m.group(0)
    if "dropdown" in txt or txt.startswith(".show"):
        print(txt[:300], "\n---")

print("\n== standalone .btn-close rule ==")
for m in re.finditer(r"(^|[,}])\s*\.btn-close\{[^}]*\}", css):
    print(m.group(0)[:400], "\n---")

print("\n== .badge / .rounded-pill / .text-bg-light ==")
for sel in (".badge{", ".rounded-pill{", ".text-bg-light{", ".list-group-item-action{"):
    i = css.find(sel)
    print(sel, "->", css[i:i+260] if i >= 0 else "NOT FOUND", "\n---")
