import re


CANONICAL_ORDER = (
    'Identity', 'Purity', 'Mass', 'Net Content', 'Endotoxin', 'Sterility',
    'Bioburden', 'Residual Solvents', 'Water/Moisture', 'pH', 'Appearance',
)

_ALIASES = {
    'Identity': (
        r'\bidentity\b', r'\bidentification\b', r'\bid\b', r'\blc[\s-]*ms\b',
        r'\bmolecular identity\b', r'\bftir\b',
    ),
    'Purity': (r'\bpurity\b', r'\bhplc\b'),
    'Mass': (r'\bmass\b', r'\bpeptide content by weight\b'),
    'Net Content': (
        r'\bnet content\b', r'\bnet weight\b', r'\bbatch average\b', r'\bpotency\b',
        r'\bcontent assay\b',
    ),
    'Endotoxin': (
        r'\bendotoxins?\b', r'\bbacterial endotoxins?\b', r'\blal\b', r'\bbet\b',
        r'usp\s*[<\u3008]?\s*85\s*[>\u3009]?',
    ),
    'Sterility': (r'\bsterility\b', r'\bsterile\b', r'usp\s*[<\u3008]?\s*71\s*[>\u3009]?'),
    'Bioburden': (
        r'\bbioburden\b', r'\bmicrobial (?:count|enumeration)\b', r'\btamc\b', r'\btymc\b',
        r'usp\s*[<\u3008]?\s*(?:61|62)\s*[>\u3009]?',
    ),
    'Residual Solvents': (r'\bresidual solvents?\b',),
    'Water/Moisture': (r'\bwater\b', r'\bmoisture\b', r'\bkarl fischer\b'),
    'pH': (r'\bph\b',),
    'Appearance': (r'\bappearance\b', r'\bdescription\b'),
}


def canonicalize_label(label):
    value = re.sub(r'[_/,+]+', ' ', str(label or '').strip().lower())
    value = re.sub(r'\s+', ' ', value)
    for canonical in _ordered_types_for_value(value):
        if _matches_type(canonical, value):
            return canonical
    return None


def canonical_types_for_row(label):
    value = str(label or '')
    matches = []
    for canonical in _ordered_types_for_value(value):
        if _matches_type(canonical, value):
            matches.append(canonical)
    return [canonical for canonical in CANONICAL_ORDER if canonical in matches]


def _ordered_types_for_value(value):
    """Resolve explicit purity/potency wording before the broad legacy HPLC alias."""
    lowered = str(value or '').lower()
    if re.search(r'\bpurity\b', lowered):
        preferred = ('Purity', 'Net Content')
    elif re.search(r'\b(?:potency|content assay)\b', lowered):
        preferred = ('Net Content', 'Purity')
    else:
        preferred = ()
    return preferred + tuple(item for item in CANONICAL_ORDER if item not in preferred)


def _matches_type(canonical, value):
    patterns = _ALIASES[canonical]
    if (
        canonical == 'Purity'
        and not re.search(r'\bpurity\b', value, re.IGNORECASE)
        and re.search(r'\b(?:potency|content assay)\b', value, re.IGNORECASE)
    ):
        patterns = tuple(pattern for pattern in patterns if pattern != r'\bhplc\b')
    return any(re.search(pattern, value, re.IGNORECASE) for pattern in patterns)
