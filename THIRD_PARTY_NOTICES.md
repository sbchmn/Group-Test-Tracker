# Third-Party Notices

Group Test Manager does not currently bundle or vendor a separate repository.
The following review was generated from the installed Python environment on
2026-09-17 with `pip-licenses 5.5.5`. The application requirements are range
based, so this snapshot applies only to that environment and is not a lockfile.

## Direct dependencies reviewed

| Package | Installed version | License reported |
| --- | ---: | --- |
| Flask | 3.1.2 | BSD-3-Clause |
| Flask-SQLAlchemy | 3.1.1 | BSD |
| Flask-WTF | 1.2.2 | BSD-3-Clause |
| Flask-Limiter | 4.1.1 | MIT |
| Flask-Migrate | 4.1.0 | MIT |
| Flask-Login | 0.6.3 | MIT |
| WTForms | 3.2.2 | BSD-3-Clause |
| Werkzeug | 3.1.8 | BSD-3-Clause |
| Gunicorn | 23.0.0 | MIT |
| python-dotenv | 1.2.2 | BSD-3-Clause |
| psycopg2-binary | 2.9.12 | LGPL with exceptions |
| PyMySQL | 1.1.2 | MIT |
| openpyxl | 3.1.5 | MIT |
| email-validator | 2.2.0 | Unlicense |
| boto3 | 1.43.95 | Apache-2.0 |
| Pillow | 12.3.0 | MIT-CMU |
| discord.py | 2.7.1 | MIT |
| OpenAI Python SDK | Not installed in reviewed environment | Declared requirement; review before distribution |
| Anthropic Python SDK | Not installed in reviewed environment | Declared requirement; review before distribution |
| pypdf | 6.19.0 | BSD-3-Clause |
| PyMuPDF | 1.28.2 | AGPL-3.0-or-later or Artifex commercial license |

## Transitive dependencies reviewed

| Package | Installed version | License reported |
| --- | ---: | --- |
| Deprecated | 1.3.1 | MIT |
| Jinja2 | 3.1.6 | BSD |
| Mako | 1.3.12 | MIT |
| MarkupSafe | 3.0.3 | BSD-3-Clause |
| PyYAML | 6.0.2 | MIT |
| Pygments | 2.20.0 | BSD-2-Clause |
| SQLAlchemy | 2.0.51 | MIT |
| aiohappyeyeballs | 2.7.1 | Python Software Foundation |
| aiohttp | 3.14.3 | Apache-2.0 and MIT |
| aiosignal | 1.4.0 | Apache-2.0 |
| Alembic | 1.18.5 | MIT |
| attrs | 26.1.0 | MIT |
| blinker | 1.9.0 | MIT |
| botocore | 1.43.95 | Apache-2.0 |
| certifi | 2026.7.22 | MPL-2.0 |
| cffi | 2.1.1 | MIT-0 |
| charset-normalizer | 3.5.1 | MIT |
| click | 8.4.2 | BSD-3-Clause |
| colorama | 0.4.6 | BSD |
| cryptography | 45.0.7 | Apache-2.0 or BSD-3-Clause |
| dnspython | 2.8.0 | ISC |
| et_xmlfile | 2.0.0 | MIT |
| frozenlist | 1.8.0 | Apache-2.0 |
| greenlet | 3.5.3 | MIT and PSF-2.0 |
| idna | 3.18 | BSD-3-Clause |
| iniconfig | 2.3.0 | MIT |
| itsdangerous | 2.2.0 | BSD |
| jmespath | 1.1.0 | MIT |
| limits | 5.8.0 | MIT |
| multidict | 6.8.0 | Apache-2.0 |
| ordered-set | 4.1.0 | MIT |
| packaging | 26.2 | Apache-2.0 or BSD-2-Clause |
| pluggy | 1.6.0 | MIT |
| propcache | 0.5.4 | Apache-2.0 |
| pytest | 9.1.1 | MIT |
| python-dateutil | 2.9.0.post0 | Apache-2.0 and BSD |
| requests | 2.32.5 | Apache-2.0 |
| s3transfer | 0.19.2 | Apache-2.0 |
| six | 1.17.0 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| urllib3 | 2.8.0 | MIT |
| wrapt | 2.4.1 | BSD-2-Clause |
| yarl | 1.25.1 | Apache-2.0 |

## Distribution review

- The direct and transitive packages above were reviewed by installed version
  and reported license metadata. The exact license text and copyright notices
  should be retained from each package when producing a binary or container
  notice bundle.
- `requirements.txt` uses version ranges. Create and retain a lockfile or
  frozen build manifest for each distributed build, then regenerate this review
  from that exact environment.
- PyMuPDF is a distribution blocker for a proprietary deployment until the
  project selects a compliant Artifex commercial license or accepts and follows
  the AGPL obligations. The proprietary project license cannot override it.
- The OpenAI and Anthropic SDKs are declared but were not installed in this
  environment. Review their exact versions and notices if either is included in
  a distributed build.
- Third-Party Components remain governed by their own licenses. The proprietary
  project license in `LICENSE` does not override those terms.
