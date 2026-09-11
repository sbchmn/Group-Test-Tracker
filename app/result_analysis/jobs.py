import secrets
from datetime import datetime, timedelta

from flask import current_app
from sqlalchemy import or_

from .. import db
from ..models import ResultAnalysisRun
from .providers import build_provider
from .providers.base import ProviderError
from .diagnostics import append_provider_diagnostic
from .service import persist_extraction
from .settings import get_analysis_settings, provider_config
from .sources import SourceError, acquire_run_source
from .types import AnalysisContext


def claim_next_run():
    now = datetime.utcnow()
    candidate = ResultAnalysisRun.query.filter(
        or_(
            (ResultAnalysisRun.status == 'queued') & or_(ResultAnalysisRun.next_attempt_at.is_(None), ResultAnalysisRun.next_attempt_at <= now),
            (ResultAnalysisRun.status == 'analyzing') & (ResultAnalysisRun.lease_expires_at < now),
        )
    ).order_by(ResultAnalysisRun.queued_at, ResultAnalysisRun.id).first()
    if not candidate:
        # End the read transaction so the next poll receives a fresh snapshot.
        # This is required for databases such as MySQL that default to
        # REPEATABLE READ isolation.
        db.session.rollback()
        return None
    token = secrets.token_hex(24)
    settings = get_analysis_settings()
    updated = ResultAnalysisRun.query.filter(
        ResultAnalysisRun.id == candidate.id,
        or_(
            (ResultAnalysisRun.status == 'queued') & or_(ResultAnalysisRun.next_attempt_at.is_(None), ResultAnalysisRun.next_attempt_at <= now),
            (ResultAnalysisRun.status == 'analyzing') & (ResultAnalysisRun.lease_expires_at < now),
        ),
    ).update({
        ResultAnalysisRun.status: 'analyzing',
        ResultAnalysisRun.lease_token: token,
        ResultAnalysisRun.lease_expires_at: now + timedelta(seconds=settings['lease_seconds']),
        ResultAnalysisRun.started_at: now,
        ResultAnalysisRun.attempt_count: ResultAnalysisRun.attempt_count + 1,
    }, synchronize_session=False)
    db.session.commit()
    if not updated:
        return None
    return ResultAnalysisRun.query.filter_by(id=candidate.id, lease_token=token).first()


def _target_context(run):
    target = run.target
    names = tuple(item.get('name', '') for item in (getattr(target, 'lab_test_details', None) or []))
    return AnalysisContext(
        title=target.title,
        compound=getattr(target, 'compound', None),
        existing_test_names=names,
    )


def _fail_run(run, code, message, transient=False):
    run.error_code = str(code or 'analysis_failed')[:60]
    run.error_message = str(message or 'Analysis failed.')[:500]
    run.lease_token = None
    run.lease_expires_at = None
    if transient and run.attempt_count < run.max_attempts:
        run.status = 'queued'
        run.next_attempt_at = datetime.utcnow() + timedelta(seconds=min(300, 15 * (2 ** max(0, run.attempt_count - 1))))
    else:
        run.status = 'failed'
        run.completed_at = datetime.utcnow()
    db.session.commit()


def process_run(run):
    try:
        config = provider_config(run.provider)
        if config['model'] != run.provider_model:
            config['model'] = run.provider_model
        provider = build_provider(config)
        settings = get_analysis_settings()
        document = acquire_run_source(run, provider.capabilities, settings)
        run.source_sha256 = document.sha256
        run.source_content_type = document.content_type
        run.source_size_bytes = len(document.raw_bytes)
        if not run.bypass_duplicate_check:
            duplicate_query = ResultAnalysisRun.query.filter(
                ResultAnalysisRun.id != run.id,
                ResultAnalysisRun.source_sha256 == document.sha256,
                ResultAnalysisRun.provider == run.provider,
                ResultAnalysisRun.schema_version == run.schema_version,
                ResultAnalysisRun.status.in_(('needs_review', 'applied')),
            )
            if run.group_test_id is not None:
                duplicate_query = duplicate_query.filter(ResultAnalysisRun.group_test_id == run.group_test_id)
            else:
                duplicate_query = duplicate_query.filter(ResultAnalysisRun.public_result_id == run.public_result_id)
            duplicate = duplicate_query.first()
            if duplicate:
                run.status = 'superseded'
                run.completed_at = datetime.utcnow()
                run.error_code = 'duplicate_source'
                run.error_message = f'An equivalent analysis already exists as run {duplicate.id}.'
                run.lease_token = None
                run.lease_expires_at = None
                db.session.commit()
                return run
        extraction = provider.analyze(document, _target_context(run))
        persist_extraction(run, extraction)
        run.lease_token = None
        run.lease_expires_at = None
        db.session.commit()
    except SourceError as exc:
        _fail_run(run, exc.code, exc.safe_message, transient=exc.transient)
    except ProviderError as exc:
        append_provider_diagnostic(
            run.provider, 'report_analysis', run.provider_model, 'failed', exception=exc, run_id=run.id,
        )
        _fail_run(run, exc.code, exc.safe_message, transient=exc.transient)
    except ValueError as exc:
        append_provider_diagnostic(
            run.provider, 'report_analysis', run.provider_model, 'failed', exception=exc, run_id=run.id,
        )
        _fail_run(run, 'invalid_provider_response', 'The provider returned an invalid structured response.')
    except Exception as exc:
        append_provider_diagnostic(
            run.provider, 'report_analysis', run.provider_model, 'failed', exception=exc, run_id=run.id,
            include_detail=False,
        )
        current_app.logger.warning('Result analysis run %s failed with %s', run.id, exc.__class__.__name__)
        _fail_run(run, 'analysis_internal_error', 'The analysis worker encountered an internal error.')
    return run


def process_next_run():
    run = claim_next_run()
    return process_run(run) if run else None
