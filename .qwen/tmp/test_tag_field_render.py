"""TEMPORARY render smoke check for the tag-field refactor (delete after use).

Run with:  python -m pytest .qwen/tmp/test_tag_field_render.py -q -p no:warnings
"""
import re
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import create_app, db
from app.models import GroupTest, PublicResult, User

HOSTILE = "<script>alert(1)</script>"


def _build():
    temp_dir = tempfile.TemporaryDirectory()
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///" + str(Path(temp_dir.name) / "check.db"),
    })
    app.config["WTF_CSRF_ENABLED"] = False
    client = app.test_client()
    with app.app_context():
        db.create_all()
        admin = User(username="tf-admin", email="tf-admin@example.com", is_admin=True, is_active=True)
        admin.set_password("secret")
        db.session.add(admin)
        db.session.flush()
        db.session.add(PublicResult(title="A Result", results_link="https://example.test/r", created_by=admin.id))
        db.session.commit()
        result_id = PublicResult.query.filter_by(title="A Result").first().id

    client.post("/login", data={"username": "tf-admin", "password": "secret"}, follow_redirects=True)

    created = client.post(
        "/admin/create-test",
        data={
            "title": "Tagged Ticking Test",
            "status": "ready_for_payment",
            "total_lab_cost": "0",
            "shipping_cost": "0",
            "refund_per_donor": "0",
            "tag_text": "Alpha, %s, beta" % HOSTILE,
        },
        follow_redirects=True,
    )
    assert created.status_code == 200
    with app.app_context():
        test = GroupTest.query.filter_by(title="Tagged Ticking Test").first()
        assert test is not None, "create-test POST did not persist the test"
        test_id = test.id
        stored = [tag.name for tag in test.tags]
    assert sorted(stored) == sorted(["Alpha", HOSTILE, "beta"]), stored

    posted = client.post(
        "/admin/public-results",
        data={
            "title": "Another Result",
            "summary": "",
            "results_link": "https://example.test/r2",
            "tag_text": "Alpha, %s" % HOSTILE,
        },
        follow_redirects=True,
    )
    assert posted.status_code == 200
    return app, client, test_id, result_id


def _tag_input_value(html):
    match = re.search(r"<input[^>]*data-tag-input=\"true\"[^>]*>", html)
    assert match, "no tag_text input found"
    value = re.search(r'value="([^"]*)"', match.group(0))
    return value.group(1) if value else ""


def test_tag_pages_render_with_shared_tag_field():
    app, client, test_id, result_id = _build()
    pages = [
        ("create-test", "/admin/create-test", False),
        ("edit-test", "/admin/edit-test/%d" % test_id, True),
        ("public-results", "/admin/public-results", False),
        ("edit-public-result", "/admin/public-results/%d/edit" % result_id, True),
    ]
    for label, url, expect_value in pages:
        response = client.get(url)
        html = response.get_data(as_text=True)
        assert response.status_code == 200, (label, response.status_code)
        for marker in ("<!DOCTYPE html>", "function addLabTestRow(", "window.tagFieldSuggestions",
                       'src="/static/js/tag-field.js"'):
            print("COUNT %-40s %s -> %d" % (marker, label, html.count(marker)))
        footer = html.find("<footer")
        for index in [m.start() for m in re.finditer(re.escape('src="/static/js/tag-field.js"'), html)]:
            print("     tag-field.js src at %d (footer at %d) %s" % (
                index, footer, "INSIDE-CONTENT" if index < footer else "AT-BASE-SCRIPTS"))
        # the shared script is loaded once, after the suggestions it reads
        assert html.count('src="/static/js/tag-field.js"') == 1, (label, html.count('src="/static/js/tag-field.js"'))
        assert html.count("window.tagFieldSuggestions = [") == 1, label
        assert html.index("window.tagFieldSuggestions") < html.index('src="/static/js/tag-field.js"'), label
        # the no-JS fallback markup is still server-rendered
        assert 'data-tag-input="true"' in html, label
        assert 'data-tag-menu="true"' in html, label
        assert 'data-tag-add="true"' in html, label
        assert "Add tag" in html, label
        assert ">Alpha</option>" in html, label
        # the triplicated inline widget is gone, and nothing is injected raw
        assert "attachTagMenu" not in html, label
        assert "Create new tag" not in html, label
        assert HOSTILE not in html, label
        assert "\\u003cscript\\u003e" in html, label
        assert "Rename or merge tags" in html, label
        if expect_value:
            value = _tag_input_value(html)
            assert "Alpha" in value and "beta" in value, (label, value)
    with app.app_context():
        result = PublicResult.query.get(result_id)
        assert [tag.name for tag in result.tags] == ["Alpha"] or sorted(
            [tag.name for tag in result.tags]) == sorted(["Alpha", HOSTILE])
    with app.app_context():
        db.session.remove()
