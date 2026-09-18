import re

css = open(r"C:\Users\sbachman\OneDrive - First Dallas Media, Inc\Documents\GitHub\Group-Test-Tracker\.qwen\tmp\bs533.css", encoding="utf-8").read()

def show(pat, label, n=520):
    m = re.search(pat, css)
    print(f"== {label} ==")
    print(m.group(0)[:n] if m else "NOT FOUND")
    print()

show(r"[,}\s]\.list-group\{[^}]*\}", ".list-group base")
show(r"[,}\s]\.dropdown-menu\{[^}]*\}", ".dropdown-menu base", 1400)
show(r"[,}\s]\.dropdown-menu\.show\{[^}]*\}", ".dropdown-menu.show")
show(r"[,}\s]\.list-group-item-action:hover[^{]*\{[^}]*\}", ".list-group-item-action:hover")
show(r"[,}\s]\.visually-hidden\{[^}]*\}", ".visually-hidden")
show(r"[,}\s]\.vr\{[^}]*\}", ".vr")
show(r"[,}\s]\.btn-close\b[^{]{0,40}\{[^}]*width[^}]*\}", ".btn-close sized rule", 900)
