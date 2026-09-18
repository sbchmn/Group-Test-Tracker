"""Render smoke check for the tag-field refactor (not part of the test suite).

GETs the three admin pages whose tag widget was replaced and asserts that:
  * each page still renders (HTTP 200),
  * the shared app/static/js/tag-field.js is referenced,
  * suggestions reach the client through the HTML-safe tojson global,
  * the server-rendered no-JS fallback markup is still present,
  * an existing tag value survives into the input,
  * a hostile tag name cannot escape into markup (autoescape + tojson).
"""
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

os.environ["SECRET_KEY"] = "tag-field-render-check"

from app import create_app, db
from app.models import GroupTest, PublicResult, User

HOSTILE = "<script>alert(1)</script>"

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
    db.session.add(GroupTest(title="Ticking Test", vendor="ACME Labs"))
    db.session.add(PublicResult(title="A Result", results_link="https://example.test/r", created_by=admin.id))
    db.session.commit()
    test_id = GroupTest.query.filter_by(title="Ticking Test").first().id
    result_id = PublicResult.query.filter_by(title="A Result").first().id

client.post("/login", data={"username": "tf-admin", "password": "secret"}, follow_redirects=True)

# Create tags through the real form contract, including the hostile name.
created = client.post(
    "/admin/create-test",
    data={
        "title": "Ticking Test",
        "status": "open",
        "total_lab_cost": "0",
        "shipping_cost": "0",
        "refund_per_donor": "0",
        "tag_text": "Alpha, %s, beta" % HOSTILE,
    },
    follow_redirects=True,
)
print("POST create-test ->", created.status_code)
posted_result = client.post(
    "/admin/public-results",
    data={
        "title": "A Result",
        "summary": "",
        "results_link": "https://example.test/r",
        "tag_text": "Alpha, %s" % HOSTILE,
    },
    follow_redirects=True,
)
print("POST public-results ->", posted_result.status_code)

pages = [
    ("create-test", "/admin/create-test"),
    ("edit-test", "/admin/edit-test/%d" % test_id),
    ("public-results", "/admin/public-results"),
    ("edit-public-result", "/admin/public-results/%d/edit" % result_id),
]

failures = []
for label, url in pages:
    response = client.get(url)
    html = response.get_data(as_text=True)
    checks = [
        ("status 200", response.status_code == 200),
        ("static js referenced", "static/js/tag-field.js" in html),
        ("tojson suggestions", "window.tagFieldSuggestions = [" in html),
        ("fallback input attr", 'data-tag-input="true"' in html),
        ("fallback select attr", 'data-tag-menu="true"' in html),
        ("fallback button attr", 'data-tag-add="true"' in html),
        ("fallback option rendered", "Alpha" in html),
        ("hostile name not raw in markup", "<script>alert(1)</script>" not in html),
        ("hostile name escaped in tojson", "\\u003cscript\\u003e" in html),
        ("attachTagMenu removed", "attachTagMenu" not in html),
    ]
    if label in ("edit-test", "edit-public-result"):
        checks.append(("existing value kept", 'value="Alpha,' in html))
    bad = [name for name, ok in checks if not ok]
    print("%-18s %s  http=%s" % (label, "FAIL " + ", ".join(bad) if bad else "OK", response.status_code))
    if bad:
        failures.append((label, bad))

with app.app_context():
    test = GroupTest.query.get(test_id)
    print("stored test tags:", [t.name for t in test.tags])
    result = PublicResult.query.get(result_id)
    print("stored result tags:", [t.name for t in result.tags])

snippet = client.get(pages[1][1]).get_data(as_text=True)
start = snippet.find("window.tagFieldSuggestions")
print("tojson line:", snippet[start:start + 160].splitlines()[0] if start != -1 else "MISSING")
print("RESULT:", "ALL OK" if not failures else "FAILURES: %s" % failures)
temp_dir.cleanup()
