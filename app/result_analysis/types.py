from dataclasses import dataclass, field
from typing import Any, Optional


SCHEMA_VERSION = '1'
MAX_FINDINGS = 50
MAX_EVIDENCE_LENGTH = 1000
CANONICAL_TYPES = (
    'Identity',
    'Purity',
    'Mass',
    'Net Content',
    'Endotoxin',
    'Sterility',
    'Bioburden',
    'Residual Solvents',
    'Water/Moisture',
    'pH',
    'Appearance',
    'Unknown',
)


EXTRACTION_JSON_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['compound', 'metadata', 'findings', 'warnings'],
    'properties': {
        'compound': {'type': ['string', 'null'], 'maxLength': 200},
        'metadata': {
            'type': 'object',
            'additionalProperties': False,
            'required': ['laboratory', 'batch_lot', 'report_date', 'sample_id', 'methods'],
            'properties': {
                'laboratory': {'type': ['string', 'null'], 'maxLength': 200},
                'batch_lot': {'type': ['string', 'null'], 'maxLength': 200},
                'report_date': {'type': ['string', 'null'], 'maxLength': 80},
                'sample_id': {'type': ['string', 'null'], 'maxLength': 200},
                'methods': {
                    'type': 'array',
                    'maxItems': 20,
                    'items': {'type': 'string', 'maxLength': 200},
                },
            },
        },
        'findings': {
            'type': 'array',
            'maxItems': MAX_FINDINGS,
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'required': [
                    'source_label', 'canonical_type', 'reported_value', 'evidence',
                    'page_number', 'confidence', 'is_reported_aggregate', 'vial_identifier',
                ],
                'properties': {
                    'source_label': {'type': 'string', 'maxLength': 200},
                    'canonical_type': {'type': 'string', 'enum': list(CANONICAL_TYPES)},
                    'reported_value': {'type': 'string', 'maxLength': 500},
                    'evidence': {'type': 'string', 'maxLength': MAX_EVIDENCE_LENGTH},
                    'page_number': {'type': ['integer', 'null'], 'minimum': 1},
                    'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1},
                    'is_reported_aggregate': {'type': 'boolean'},
                    'vial_identifier': {'type': ['string', 'null'], 'maxLength': 120},
                },
            },
        },
        'warnings': {
            'type': 'array',
            'maxItems': 20,
            'items': {'type': 'string', 'maxLength': 200},
        },
    },
}


@dataclass(frozen=True)
class AnalysisPage:
    number: int
    image_bytes: bytes
    media_type: str


@dataclass(frozen=True)
class AnalysisDocument:
    content_type: str
    raw_bytes: bytes
    sha256: str
    source_text: str = ''
    pages: tuple[AnalysisPage, ...] = ()


@dataclass(frozen=True)
class AnalysisContext:
    title: str
    compound: Optional[str]
    existing_test_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderCapabilities:
    direct_pdf: bool
    image_media_types: tuple[str, ...]


@dataclass(frozen=True)
class ProviderHealth:
    ok: bool
    message: str


@dataclass(frozen=True)
class AnalysisExtraction:
    data: dict[str, Any]
    provider_model: str
    request_id: Optional[str] = None
    usage: dict[str, Any] = field(default_factory=dict)
    provider_metadata: dict[str, Any] = field(default_factory=dict)


def _bounded_text(value, field_name, limit, allow_none=True):
    if value is None and allow_none:
        return None
    if not isinstance(value, str):
        raise ValueError(f'{field_name} must be text.')
    value = value.strip()
    if not value and not allow_none:
        raise ValueError(f'{field_name} is required.')
    if len(value) > limit:
        raise ValueError(f'{field_name} is too long.')
    return value or None


def validate_extraction(payload):
    """Validate and normalize provider output independently of provider guarantees."""
    if not isinstance(payload, dict):
        raise ValueError('Provider output must be an object.')
    if set(payload) != {'compound', 'metadata', 'findings', 'warnings'}:
        raise ValueError('Provider output contains missing or unexpected fields.')

    metadata = payload.get('metadata')
    if not isinstance(metadata, dict) or set(metadata) != {'laboratory', 'batch_lot', 'report_date', 'sample_id', 'methods'}:
        raise ValueError('Provider metadata is invalid.')
    methods = metadata.get('methods')
    if not isinstance(methods, list) or len(methods) > 20:
        raise ValueError('Provider methods are invalid.')

    normalized = {
        'compound': _bounded_text(payload.get('compound'), 'compound', 200),
        'metadata': {
            'laboratory': _bounded_text(metadata.get('laboratory'), 'laboratory', 200),
            'batch_lot': _bounded_text(metadata.get('batch_lot'), 'batch_lot', 200),
            'report_date': _bounded_text(metadata.get('report_date'), 'report_date', 80),
            'sample_id': _bounded_text(metadata.get('sample_id'), 'sample_id', 200),
            'methods': [_bounded_text(item, 'method', 200, allow_none=False) for item in methods],
        },
        'findings': [],
        'warnings': [],
    }

    findings = payload.get('findings')
    if not isinstance(findings, list) or len(findings) > MAX_FINDINGS:
        raise ValueError('Provider findings are invalid.')
    required_finding = {
        'source_label', 'canonical_type', 'reported_value', 'evidence', 'page_number',
        'confidence', 'is_reported_aggregate', 'vial_identifier',
    }
    for item in findings:
        if not isinstance(item, dict) or set(item) != required_finding:
            raise ValueError('A provider finding is malformed.')
        canonical_type = item.get('canonical_type')
        if canonical_type not in CANONICAL_TYPES:
            raise ValueError('A provider finding has an unsupported canonical type.')
        try:
            confidence = float(item.get('confidence'))
        except (TypeError, ValueError) as exc:
            raise ValueError('A provider finding has invalid confidence.') from exc
        if not 0 <= confidence <= 1:
            raise ValueError('A provider finding has out-of-range confidence.')
        page_number = item.get('page_number')
        if page_number is not None and (not isinstance(page_number, int) or page_number < 1):
            raise ValueError('A provider finding has an invalid page number.')
        if not isinstance(item.get('is_reported_aggregate'), bool):
            raise ValueError('A provider finding has an invalid aggregate flag.')
        normalized['findings'].append({
            'source_label': _bounded_text(item.get('source_label'), 'source label', 200, allow_none=False),
            'canonical_type': canonical_type,
            'reported_value': _bounded_text(item.get('reported_value'), 'reported value', 500, allow_none=False),
            'evidence': _bounded_text(item.get('evidence'), 'evidence', MAX_EVIDENCE_LENGTH, allow_none=False),
            'page_number': page_number,
            'confidence': confidence,
            'is_reported_aggregate': item['is_reported_aggregate'],
            'vial_identifier': _bounded_text(item.get('vial_identifier'), 'vial identifier', 120),
        })

    warnings = payload.get('warnings')
    if not isinstance(warnings, list) or len(warnings) > 20:
        raise ValueError('Provider warnings are invalid.')
    normalized['warnings'] = [_bounded_text(item, 'warning', 200, allow_none=False) for item in warnings]
    return normalized
