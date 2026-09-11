import hashlib
import re
from datetime import datetime

from .. import db
from ..models import GroupTest, PublicResult, ResultAnalysisFinding, ResultAnalysisRun
from .settings import get_analysis_settings, provider_config
from .taxonomy import CANONICAL_ORDER, canonical_types_for_row, canonicalize_label
from .types import SCHEMA_VERSION


DESCRIPTION_START = '<!-- result-analysis:start -->'
DESCRIPTION_END = '<!-- result-analysis:end -->'


class AnalysisConflict(RuntimeError):
    pass


def _target_filter(target):
    if isinstance(target, GroupTest):
        return {'group_test_id': target.id, 'public_result_id': None}
    if isinstance(target, PublicResult):
        return {'group_test_id': None, 'public_result_id': target.id}
    raise ValueError('Unsupported analysis target.')


def enqueue_analysis(target, source_kind, requested_by_id=None, provider=None, automatic=False):
    settings = get_analysis_settings()
    if automatic and not settings['enabled']:
        return None
    if source_kind not in {'upload', 'link'}:
        raise ValueError('Unsupported analysis source.')
    source_reference = target.results_image_key if source_kind == 'upload' else target.results_link
    source_reference = str(source_reference or '').strip()
    if not source_reference:
        raise ValueError(f'No {source_kind} source is available.')

    selected = provider or settings['provider']
    config = provider_config(selected)
    target_filter = _target_filter(target)
    active = ResultAnalysisRun.query.filter_by(
        **target_filter,
        source_kind=source_kind,
        source_reference=source_reference,
        provider=selected,
    ).filter(ResultAnalysisRun.status.in_(('queued', 'analyzing'))).first()
    if active:
        return active

    run = ResultAnalysisRun(
        **target_filter,
        source_kind=source_kind,
        source_reference=source_reference[:500],
        provider=selected,
        provider_model=config['model'],
        schema_version=SCHEMA_VERSION,
        max_attempts=settings['max_attempts'],
        requested_by_id=requested_by_id,
        status='queued',
        queued_at=datetime.utcnow(),
    )
    db.session.add(run)
    db.session.commit()
    return run


def latest_run_for_target(target):
    target_filter = _target_filter(target)
    return ResultAnalysisRun.query.filter_by(**target_filter).order_by(ResultAnalysisRun.created_at.desc(), ResultAnalysisRun.id.desc()).first()


def _best_findings(findings):
    by_type = {}
    ambiguous = []
    for finding in findings:
        canonical = finding['canonical_type']
        if canonical == 'Unknown':
            canonical = canonicalize_label(finding['source_label'])
        if not canonical:
            ambiguous.append(finding)
            continue
        by_type.setdefault(canonical, []).append(finding)

    selected = {}
    for canonical, candidates in by_type.items():
        aggregates = [item for item in candidates if item['is_reported_aggregate']]
        eligible = aggregates or candidates
        if len(eligible) == 1:
            selected[canonical] = eligible[0]
        elif aggregates:
            selected[canonical] = max(aggregates, key=lambda item: item['confidence'])
        else:
            ambiguous.extend(candidates)
    return selected, ambiguous


def _row_key(index, name):
    digest = hashlib.sha256(str(name or '').strip().lower().encode('utf-8')).hexdigest()[:12]
    return f'{index}:{digest}'


def persist_extraction(run, extraction):
    for existing in list(run.findings):
        db.session.delete(existing)

    data = extraction.data
    selected, ambiguous = _best_findings(data['findings'])
    target = run.target
    used = set()

    if isinstance(target, GroupTest):
        rows = list(target.lab_test_details or [])
        for index, row in enumerate(rows):
            row_types = canonical_types_for_row(row.get('name'))
            matches = [(canonical, selected[canonical]) for canonical in row_types if canonical in selected]
            if not matches:
                continue
            used.update(canonical for canonical, _ in matches)
            if len(matches) == 1:
                canonical, item = matches[0]
                value = item['reported_value']
                label = item['source_label']
                evidence = item['evidence']
                confidence = item['confidence']
                page = item['page_number']
                aggregate = item['is_reported_aggregate']
            else:
                matches.sort(key=lambda pair: CANONICAL_ORDER.index(pair[0]))
                canonical = ' + '.join(pair[0] for pair in matches)
                value = '; '.join(f'{kind}: {item["reported_value"]}' for kind, item in matches)
                label = '; '.join(item['source_label'] for _, item in matches)
                evidence = ' | '.join(item['evidence'] for _, item in matches)[:1000]
                confidence = min(item['confidence'] for _, item in matches)
                pages = [item['page_number'] for _, item in matches if item['page_number']]
                page = min(pages) if pages else None
                aggregate = any(item['is_reported_aggregate'] for _, item in matches)
            action = 'conflict' if str(row.get('result') or '').strip() else 'fill'
            db.session.add(ResultAnalysisFinding(
                run=run,
                canonical_type=canonical[:80],
                source_label=label[:200],
                reported_value=value[:500],
                evidence_text=evidence[:1000],
                page_number=page,
                confidence=confidence,
                is_reported_aggregate=aggregate,
                proposed_action=action,
                target_row_key=_row_key(index, row.get('name')),
            ))
    else:
        existing_types = {canonicalize_label(item.get('name')) for item in (target.item_results or [])}
        for canonical, item in selected.items():
            used.add(canonical)
            db.session.add(ResultAnalysisFinding(
                run=run,
                canonical_type=canonical,
                source_label=item['source_label'],
                reported_value=item['reported_value'],
                evidence_text=item['evidence'],
                page_number=item['page_number'],
                confidence=item['confidence'],
                is_reported_aggregate=item['is_reported_aggregate'],
                proposed_action='conflict' if canonical in existing_types else 'create',
            ))

    for item in ambiguous:
        canonical = item.get('canonical_type')
        db.session.add(ResultAnalysisFinding(
            run=run,
            canonical_type=None if canonical == 'Unknown' else canonical,
            source_label=item['source_label'],
            reported_value=item['reported_value'],
            evidence_text=item['evidence'],
            page_number=item['page_number'],
            confidence=item['confidence'],
            is_reported_aggregate=item['is_reported_aggregate'],
            proposed_action='unrecognized',
        ))

    for canonical, item in selected.items():
        if canonical in used:
            continue
        db.session.add(ResultAnalysisFinding(
            run=run,
            canonical_type=canonical,
            source_label=item['source_label'],
            reported_value=item['reported_value'],
            evidence_text=item['evidence'],
            page_number=item['page_number'],
            confidence=item['confidence'],
            is_reported_aggregate=item['is_reported_aggregate'],
            proposed_action='create' if isinstance(target, GroupTest) else 'unrecognized',
        ))

    run.provider_model = extraction.provider_model[:120]
    run.usage_json = {
        'request_id': extraction.request_id,
        'usage': extraction.usage,
        'provider': extraction.provider_metadata,
    }
    run.metadata_json = {
        'compound': data.get('compound'),
        **data.get('metadata', {}),
        'warnings': data.get('warnings', []),
    }
    run.status = 'needs_review'
    run.completed_at = datetime.utcnow()
    run.error_code = None
    run.error_message = None


def _managed_description(current, metadata):
    fields = (
        ('Compound', metadata.get('compound')),
        ('Laboratory', metadata.get('laboratory')),
        ('Batch/Lot', metadata.get('batch_lot')),
        ('Report Date', metadata.get('report_date')),
        ('Sample ID', metadata.get('sample_id')),
        ('Methods', ', '.join(metadata.get('methods') or [])),
    )
    lines = [f'{label}: {value}' for label, value in fields if value]
    if not lines:
        return current or ''
    block = f'{DESCRIPTION_START}\nAnalysis metadata:\n' + '\n'.join(lines) + f'\n{DESCRIPTION_END}'
    base = re.sub(
        re.escape(DESCRIPTION_START) + r'.*?' + re.escape(DESCRIPTION_END),
        '',
        current or '',
        flags=re.DOTALL,
    ).strip()
    return f'{base}\n\n{block}'.strip() if base else block


def apply_analysis_run(run, decisions, reviewed_by_id, include_metadata=False):
    if run.status != 'needs_review':
        raise AnalysisConflict('Only runs awaiting review can be applied.')
    target = run.target
    now = datetime.utcnow()
    accepted = []
    for finding in run.findings:
        decision = decisions.get(finding.id, {})
        accept = bool(decision.get('accepted')) and finding.proposed_action in {'fill', 'create'}
        finding.review_decision = 'accepted' if accept else 'rejected'
        finding.reviewed_at = now
        reviewed_value = str(decision.get('value') or finding.reported_value).strip()[:500]
        finding.reviewed_value = reviewed_value if accept else None
        if accept and reviewed_value:
            accepted.append(finding)

    if isinstance(target, GroupTest):
        rows = [dict(item) for item in (target.lab_test_details or [])]
        for finding in accepted:
            if finding.proposed_action == 'create':
                existing_types = {
                    canonical
                    for row in rows
                    for canonical in canonical_types_for_row(row.get('name'))
                }
                if finding.canonical_type in existing_types:
                    raise AnalysisConflict('A matching Group Test row was added after analysis.')
                rows.append({
                    'name': finding.canonical_type,
                    'price': 0.0,
                    'vials_needed': 0,
                    'result': finding.reviewed_value,
                })
                continue
            try:
                raw_index, expected_digest = finding.target_row_key.split(':', 1)
                index = int(raw_index)
                row = rows[index]
            except (AttributeError, ValueError, IndexError) as exc:
                raise AnalysisConflict('A target test row no longer exists.') from exc
            if _row_key(index, row.get('name')).split(':', 1)[1] != expected_digest:
                raise AnalysisConflict('A target test row changed after analysis.')
            if str(row.get('result') or '').strip():
                raise AnalysisConflict('A target test result was filled after analysis.')
            row['result'] = finding.reviewed_value
        target.lab_test_details = rows
        if include_metadata:
            target.description = _managed_description(target.description, run.metadata_json or {})
    else:
        rows = [dict(item) for item in (target.item_results or [])]
        existing_types = {canonicalize_label(item.get('name')) for item in rows}
        for finding in accepted:
            if finding.canonical_type in existing_types:
                raise AnalysisConflict('A matching Public Result row was added after analysis.')
            rows.append({'name': finding.canonical_type, 'result': finding.reviewed_value})
            existing_types.add(finding.canonical_type)
        target.item_results = rows
        if include_metadata:
            target.summary = _managed_description(target.summary, run.metadata_json or {})

    run.status = 'applied'
    run.reviewed_by_id = reviewed_by_id
    run.reviewed_at = now
    db.session.commit()
    return len(accepted)
