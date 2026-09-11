import re


CANONICAL_ORDER = (
    'Identity', 'Purity', 'Mass', 'Net Content', 'Endotoxin', 'Sterility',
    'Bioburden', 'Residual Solvents', 'Water/Moisture', 'pH', 'Appearance',
)

_ALIASES = {
    'Identity': (r'\bidentity\b', r'\bidentification\b', r'\bid\b', r'\blc[\s-]*ms\b', r'\bmolecular identity\b'),
    'Purity': (r'\bpurity\b', r'\bhplc\b'),
    'Mass': (r'\bmass\b', r'\bpeptide content by weight\b'),
    'Net Content': (r'\bnet content\b', r'\bnet weight\b', r'\bbatch average\b'),
    'Endotoxin': (r'\bendotoxin\b', r'\blal\b'),
    'Sterility': (r'\bsterility\b', r'\bsterile\b'),
    'Bioburden': (r'\bbioburden\b', r'\bmicrobial count\b'),
    'Residual Solvents': (r'\bresidual solvents?\b',),
    'Water/Moisture': (r'\bwater\b', r'\bmoisture\b', r'\bkarl fischer\b'),
    'pH': (r'\bph\b',),
    'Appearance': (r'\bappearance\b', r'\bdescription\b'),
}


def canonicalize_label(label):
    value = re.sub(r'[_/,+]+', ' ', str(label or '').strip().lower())
    value = re.sub(r'\s+', ' ', value)
    for canonical in CANONICAL_ORDER:
        if any(re.search(pattern, value, re.IGNORECASE) for pattern in _ALIASES[canonical]):
            return canonical
    return None


def canonical_types_for_row(label):
    value = str(label or '')
    matches = []
    for canonical in CANONICAL_ORDER:
        if any(re.search(pattern, value, re.IGNORECASE) for pattern in _ALIASES[canonical]):
            matches.append(canonical)
    return matches
