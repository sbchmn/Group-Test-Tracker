# Migration guidance

When adding or updating database migrations, preserve the existing Alembic revision chain.

Rules:
- Do not create a new migration that points to an unknown or missing `down_revision` unless that revision is intentionally being restored as a compatibility stub.
- If a historical revision ID is missing from the repository, add a compatibility migration rather than rewriting the chain in place.
- Prefer extending the current head revision chain instead of changing earlier revisions.
- If you need to adjust schema behavior, create a new migration on top of the current head.
