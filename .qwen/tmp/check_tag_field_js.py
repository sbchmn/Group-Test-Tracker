"""Syntax sanity check for the new app/static/js/tag-field.js.

No JS engine (node/deno) exists on this machine, so this is a lexer-level
check only: it walks the file skipping comments, string literals and regex
literals, and reports unbalanced () {} [], unterminated strings/comments,
and any leftover template-literal markers.
"""
import io
import sys

PATH = r"C:\Users\sbachman\OneDrive - First Dallas Media, Inc\Documents\GitHub\Group-Test-Tracker\app\static\js\tag-field.js"
src = io.open(PATH, encoding="utf-8").read()

PAIRS = {")": "(", "]": "[", "}": "{"}
# tokens after which a '/' starts a regex literal rather than a division
BEFORE_REGEX = set("(,=:[!&|?{};+-*%<>~^") 

i = 0
n = len(src)
stack = []
line = 1
problems = []
last_significant = ""

def ctx(pos):
    return "line %d" % (src.count("\n", 0, pos) + 1)

while i < n:
    ch = src[i]
    if ch == "\n":
        line += 1
        i += 1
        continue
    # comments
    if src.startswith("//", i):
        j = src.find("\n", i)
        i = n if j == -1 else j
        continue
    if src.startswith("/*", i):
        j = src.find("*/", i + 2)
        if j == -1:
            problems.append(("unterminated block comment", ctx(i)))
            break
        line += src.count("\n", i, j)
        i = j + 2
        continue
    # strings
    if ch in ("'", '"', "`"):
        quote = ch
        j = i + 1
        while j < n:
            if src[j] == "\\":
                j += 2
                continue
            if src[j] == quote:
                break
            if src[j] == "\n":
                problems.append(("newline inside %s string" % quote, ctx(i)))
                break
            j += 1
        else:
            problems.append(("unterminated %s string" % quote, ctx(i)))
        if quote == "`":
            problems.append(("template literal found (ES2020 plain strings only)", ctx(i)))
        i = j + 1
        last_significant = "str"
        continue
    # regex literal
    if ch == "/" and (not last_significant or last_significant[-1] in BEFORE_REGEX):
        j = i + 1
        in_class = False
        closed = False
        while j < n and src[j] != "\n":
            if src[j] == "\\":
                j += 2
                continue
            if src[j] == "[":
                in_class = True
            elif src[j] == "]":
                in_class = False
            elif src[j] == "/" and not in_class:
                closed = True
                break
            j += 1
        if not closed:
            problems.append(("unterminated regex literal", ctx(i)))
            i = j
            continue
        j += 1
        while j < n and src[j].isalpha():
            j += 1  # flags
        i = j
        last_significant = "re"
        continue
    if ch in "([{":
        stack.append((ch, i))
    elif ch in ")]}":
        if not stack:
            problems.append(("unmatched closing %r" % ch, ctx(i)))
        else:
            opener, pos = stack.pop()
            if opener != PAIRS[ch]:
                problems.append(("mismatched %r closed by %r" % (opener, ch), ctx(pos)))
    if not ch.isspace():
        last_significant = ch

for opener, pos in stack:
    problems.append(("unclosed %r" % opener, ctx(pos)))

print("chars:", n, "lines:", src.count("\n") + 1)
print("innerHTML uses:", src.count("innerHTML"))
print("insertAdjacentHTML uses:", src.count("insertAdjacentHTML"))
print("document.write uses:", src.count("document.write"))
print("eval/new Function:", src.count("eval(") + src.count("new Function"))
if problems:
    print("PROBLEMS:")
    for message, where in problems:
        print("  %s: %s" % (where, message))
    sys.exit(1)
print("lex/balance check: clean")
