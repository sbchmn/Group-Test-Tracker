"""One database-paginated action list across independent GTM workloads."""
from types import SimpleNamespace

from flask_sqlalchemy.pagination import QueryPagination
from sqlalchemy import literal, case, func, or_, and_, cast, String

from . import db
from .models import Participation, GroupTest, PublicResult, ResultAnalysisRun, BSTVendor, BSTTopic


def build_queue(status, search, page, item_type='all'):
    from .routes import _build_pending_queue_query
    queries = []
    if item_type in {'all', 'join', 'payment'}:
        query = _build_pending_queue_query(status, search)
        if item_type != 'all':
            query = query.filter(Participation.approved.is_(item_type == 'payment'))
        queries.append(query.with_entities(
            case((Participation.approved.is_(True), 'payment'), else_='join').label('kind'),
            Participation.id.label('id'),
            case((Participation.approved.is_(True), Participation.payment_claimed_at), else_=Participation.requested_at).label('queued_at')))
    if item_type in {'all', 'analysis'}:
        query = db.session.query(literal('analysis').label('kind'), ResultAnalysisRun.id.label('id'),
                                  func.coalesce(ResultAnalysisRun.completed_at, ResultAnalysisRun.created_at).label('queued_at')).filter(or_(
            ResultAnalysisRun.status == 'needs_review', and_(ResultAnalysisRun.status == 'failed', ResultAnalysisRun.reviewed_at.is_(None))))
        if search:
            query = query.outerjoin(GroupTest, ResultAnalysisRun.group_test_id == GroupTest.id).outerjoin(
                PublicResult, ResultAnalysisRun.public_result_id == PublicResult.id).filter(or_(
                GroupTest.title.ilike(f'%{search}%'), PublicResult.title.ilike(f'%{search}%'), ResultAnalysisRun.error_message.ilike(f'%{search}%')))
        queries.append(query)
    if item_type in {'all', 'bst'}:
        query = db.session.query(literal('bst').label('kind'), BSTVendor.id.label('id'),
                                  BSTVendor.submitted_at.label('queued_at')).join(BSTTopic).filter(BSTVendor.status == 'pending')
        if search:
            query = query.filter(or_(BSTTopic.name.ilike(f'%{search}%'), BSTVendor.telegram_user_id.ilike(f'%{search}%'),
                                     cast(BSTVendor.draft, String).ilike(f'%{search}%')))
        queries.append(query)
    combined = queries[0].union_all(*queries[1:]).subquery() if len(queries) > 1 else queries[0].subquery()
    query = db.session.query(combined).order_by(combined.c.queued_at.asc(), combined.c.kind, combined.c.id)
    pagination = QueryPagination(query=query, page=page, per_page=25, error_out=False)
    records = {}
    for model, kinds in ((Participation, {'join', 'payment'}), (ResultAnalysisRun, {'analysis'}), (BSTVendor, {'bst'})):
        ids = [row.id for row in pagination.items if row.kind in kinds]
        records.update({(kind, record.id): record for record in model.query.filter(model.id.in_(ids)).all() for kind in kinds})
    items = [SimpleNamespace(kind=row.kind, target=records[(row.kind, row.id)], queued_at=row.queued_at) for row in pagination.items]
    return pagination, items
