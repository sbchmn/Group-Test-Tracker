"""Shared queued webhook delivery helpers for bot-style integrations."""

from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import atexit
import json


_BOT_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="bot-dispatch")
atexit.register(lambda: _BOT_EXECUTOR.shutdown(wait=False, cancel_futures=True))


def post_json(url, payload, headers=None, timeout=10):
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)

    request = Request(
        str(url or "").strip(),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )

    try:
        with urlopen(request, context=None, timeout=timeout) as response:
            status_code = getattr(response, "status", None) or response.getcode()
            response_body = response.read().decode("utf-8", errors="replace")
        return 200 <= int(status_code or 0) < 300, response_body
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        return False, str(exc)


def queue_json(url, payload, headers=None, timeout=10):
    return _BOT_EXECUTOR.submit(post_json, url, payload, headers, timeout)