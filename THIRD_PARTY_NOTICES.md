# Third-Party Notices

Group Test Manager does not currently bundle or vendor a separate repository. It
uses the direct Python dependencies declared in `requirements.txt`.

The current direct-dependency attribution inventory is:

| Dependency | License family |
| --- | --- |
| Flask, Flask-SQLAlchemy, Flask-WTF, WTForms, Werkzeug | BSD-3-Clause |
| Flask-Login, Flask-Limiter, Flask-Migrate, Alembic, Gunicorn | MIT |
| python-dotenv | BSD-3-Clause |
| psycopg2 | LGPL-3.0-or-later with exception |
| PyMySQL, openpyxl, email-validator | MIT |
| boto3 | Apache-2.0 |
| Pillow | HPND |
| discord.py | MIT |
| OpenAI Python SDK | Apache-2.0 |
| Anthropic Python SDK | MIT |
| pypdf | BSD-3-Clause |
| PyMuPDF | AGPL-3.0-or-later or commercial license |

This inventory is based on the declared direct dependencies and is not a
substitute for an exact notice bundle generated from a locked production
environment. Dependency versions and transitive dependencies must be reviewed
before distributing a copy of the application. In particular, PyMuPDF requires
choosing and complying with either its AGPL terms or an appropriate commercial
license.

The project license is documented in `LICENSE` and is a proprietary commercial
license. Third-Party Components remain governed by their own licenses; this
project license does not override those terms.