"""Shared public-results browsing data for bot adapters."""

from sqlalchemy import func

from .models import PublicResult, Tag, public_result_tags

PAGE_SIZE = 10


def _page_number(value):
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1


def _page_window(total, page):
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(_page_number(page), total_pages)
    return page, total_pages


def public_result_tag_page(page=1):
    tags = (
        Tag.query
        .join(public_result_tags, public_result_tags.c.tag_id == Tag.id)
        .join(PublicResult, PublicResult.id == public_result_tags.c.public_result_id)
        .distinct()
        .order_by(func.lower(Tag.name).asc(), Tag.id.asc())
        .all()
    )
    total = len(tags)
    page, total_pages = _page_window(total, page)
    start = (page - 1) * PAGE_SIZE
    return tags[start:start + PAGE_SIZE], page, total_pages


def public_results_for_tag_page(tag_id, page=1):
    tag = Tag.query.get(tag_id)
    if tag is None:
        return None, [], 1, 1

    query = (
        PublicResult.query
        .join(public_result_tags, public_result_tags.c.public_result_id == PublicResult.id)
        .filter(public_result_tags.c.tag_id == tag.id)
        .order_by(PublicResult.created_at.desc(), PublicResult.id.desc())
    )
    total = query.count()
    page, total_pages = _page_window(total, page)
    results = query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()
    return tag, results, page, total_pages
