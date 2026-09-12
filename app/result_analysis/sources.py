import hashlib
import io
import ipaddress
import socket
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ..storage import get_storage_settings, read_result_file
from .types import AnalysisDocument, AnalysisPage


MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
MAX_IMAGE_PIXELS = 50_000_000
MAX_RENDERED_PDF_BYTES = 40 * 1024 * 1024
SUPPORTED_MIME_BY_FORMAT = {
    'JPEG': 'image/jpeg',
    'PNG': 'image/png',
    'WEBP': 'image/webp',
    'GIF': 'image/gif',
    'PDF': 'application/pdf',
}


class SourceError(RuntimeError):
    code = 'source_error'
    transient = False

    def __init__(self, safe_message):
        super().__init__(safe_message)
        self.safe_message = safe_message


class TransientSourceError(SourceError):
    code = 'source_transient'
    transient = True


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.assets = []
        self._ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'noscript', 'svg'}:
            self._ignored += 1
        attrs = dict(attrs)
        if tag == 'a' and attrs.get('href'):
            self.assets.append(attrs['href'])
        if tag == 'img' and attrs.get('src'):
            self.assets.append(attrs['src'])

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'noscript', 'svg'} and self._ignored:
            self._ignored -= 1

    def handle_data(self, data):
        if not self._ignored:
            value = ' '.join(data.split())
            if value:
                self.parts.append(value)


def _max_source_bytes(settings):
    storage_limit = int(get_storage_settings()['max_upload_size_mb'] * 1024 * 1024)
    analysis_limit = int(settings['max_document_mb'] * 1024 * 1024)
    return min(storage_limit, analysis_limit)


def _safe_public_url(value):
    try:
        parsed = urlsplit(str(value or '').strip())
    except ValueError as exc:
        raise SourceError('The result link is invalid.') from exc
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        raise SourceError('Only public HTTP or HTTPS result links are supported.')
    if parsed.port and parsed.port not in {80, 443}:
        raise SourceError('The result link uses an unsupported port.')
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise TransientSourceError('The result host could not be resolved.') from exc
    if not addresses:
        raise TransientSourceError('The result host could not be resolved.')
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise SourceError('The result link does not resolve to a public address.')
    return parsed


def _assert_public_peer(response):
    """Recheck the connected peer to close the DNS-check/DNS-connect rebinding gap."""
    raw = getattr(getattr(response, 'fp', None), 'raw', None)
    sock = getattr(raw, '_sock', None)
    try:
        peer = ipaddress.ip_address(sock.getpeername()[0])
    except Exception as exc:
        raise SourceError('The result source network address could not be verified.') from exc
    if not peer.is_global:
        raise SourceError('The result source connected to a non-public address.')


def _fetch_url(url, max_bytes, timeout):
    opener = build_opener(_NoRedirect())
    current = str(url).strip()
    for redirect_count in range(MAX_REDIRECTS + 1):
        _safe_public_url(current)
        request = Request(current, headers={'User-Agent': 'GroupTestTracker-ResultAnalysis/1.0', 'Accept': 'text/html,application/pdf,image/*'})
        try:
            response = opener.open(request, timeout=timeout)
        except HTTPError as exc:
            _assert_public_peer(exc)
            if exc.code in {301, 302, 303, 307, 308}:
                if redirect_count >= MAX_REDIRECTS:
                    raise SourceError('The result link redirected too many times.')
                location = exc.headers.get('Location')
                if not location:
                    raise SourceError('The result link returned an invalid redirect.')
                current = urljoin(current, location)
                continue
            if exc.code in {408, 425, 429} or exc.code >= 500:
                raise TransientSourceError('The result page is temporarily unavailable.') from exc
            raise SourceError('The result page could not be downloaded.') from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise TransientSourceError('The result page is temporarily unavailable.') from exc

        _assert_public_peer(response)
        declared = response.headers.get('Content-Length')
        if declared:
            try:
                if int(declared) > max_bytes:
                    raise SourceError('The result source exceeds the analysis size limit.')
            except ValueError:
                pass
        payload = response.read(max_bytes + 1)
        if len(payload) > max_bytes:
            raise SourceError('The result source exceeds the analysis size limit.')
        return payload, str(response.headers.get_content_type() or ''), response.geturl()
    raise SourceError('The result link redirected too many times.')


def _sniff(payload, declared_type=''):
    if payload.startswith(b'%PDF-'):
        return 'application/pdf', 'PDF'
    try:
        from PIL import Image, UnidentifiedImageError
        with Image.open(io.BytesIO(payload)) as image:
            image_format = str(image.format or '').upper()
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise SourceError('The result image dimensions are invalid or too large.')
            if image_format in SUPPORTED_MIME_BY_FORMAT:
                return SUPPORTED_MIME_BY_FORMAT[image_format], image_format
    except SourceError:
        raise
    except (UnidentifiedImageError, OSError):
        pass
    if declared_type.split(';', 1)[0].strip().lower() == 'text/html' or payload.lstrip().lower().startswith((b'<!doctype html', b'<html')):
        return 'text/html', 'HTML'
    raise SourceError('The result source is not a supported PDF, image, or HTML page.')


def _html_asset_candidates(base_url, payload):
    parser = _TextExtractor()
    parser.feed(payload.decode('utf-8', errors='replace'))
    base_host = urlsplit(base_url).hostname
    candidates = []
    for raw in parser.assets[:100]:
        candidate = urljoin(base_url, raw)
        try:
            parsed = urlsplit(candidate)
        except ValueError:
            continue
        if parsed.scheme not in {'http', 'https'} or parsed.hostname != base_host:
            continue
        path = parsed.path.lower()
        if path.endswith(('.pdf', '.png', '.jpg', '.jpeg', '.webp', '.gif')) and candidate not in candidates:
            candidates.append(candidate)
    candidates.sort(key=lambda value: (0 if urlsplit(value).path.lower().endswith('.pdf') else 1, value))
    return candidates[:5]


def _validate_allowed_format(image_format):
    if image_format == 'HTML':
        return
    allowed = get_storage_settings()['allowed_formats']
    if image_format not in allowed:
        raise SourceError(f'The result format {image_format} is not enabled in Storage settings.')


def _pdf_page_count(payload):
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(payload), strict=False)
        if reader.is_encrypted:
            raise SourceError('Encrypted PDF reports are not supported.')
        extracted = []
        for page in reader.pages:
            try:
                extracted.append(page.extract_text() or '')
            except Exception:
                extracted.append('')
        return len(reader.pages), '\n'.join(extracted)
    except SourceError:
        raise
    except ImportError as exc:
        raise SourceError('PDF analysis dependencies are not installed.') from exc
    except Exception:
        try:
            import pymupdf
            document = pymupdf.open(stream=payload, filetype='pdf')
            if document.needs_pass:
                document.close()
                raise SourceError('Encrypted PDF reports are not supported.')
            extracted = []
            for page in document:
                try:
                    extracted.append(page.get_text() or '')
                except Exception:
                    extracted.append('')
            page_count = document.page_count
            document.close()
            return page_count, '\n'.join(extracted)
        except SourceError:
            raise
        except Exception as fallback_exc:
            raise SourceError('The PDF report is invalid or unreadable.') from fallback_exc


def _render_pdf_pages(payload, max_pages):
    try:
        import pymupdf
    except ImportError as exc:
        raise SourceError('PDF rendering dependencies are not installed.') from exc
    pages = []
    rendered_total = 0
    try:
        document = pymupdf.open(stream=payload, filetype='pdf')
        for index in range(min(document.page_count, max_pages)):
            pixmap = document.load_page(index).get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
            image_bytes = pixmap.tobytes('png')
            if len(image_bytes) > 20 * 1024 * 1024:
                raise SourceError('A rendered PDF page exceeds the provider image limit.')
            rendered_total += len(image_bytes)
            if rendered_total > MAX_RENDERED_PDF_BYTES:
                raise SourceError('The rendered PDF exceeds the analysis image budget.')
            pages.append(AnalysisPage(index + 1, image_bytes, 'image/png'))
        document.close()
    except SourceError:
        raise
    except Exception as exc:
        raise SourceError('The PDF report could not be rendered safely.') from exc
    return tuple(pages)


def _convert_image_to_png(payload):
    try:
        from PIL import Image
        with Image.open(io.BytesIO(payload)) as image:
            converted = image.convert('RGB')
            output = io.BytesIO()
            converted.save(output, format='PNG', optimize=True)
            return output.getvalue()
    except Exception as exc:
        raise SourceError('The result image could not be normalized for the selected provider.') from exc


def prepare_document(payload, declared_type, settings, render_pdf=False):
    content_type, image_format = _sniff(payload, declared_type)
    _validate_allowed_format(image_format)
    source_text = ''
    pages = ()
    if content_type == 'application/pdf':
        page_count, source_text = _pdf_page_count(payload)
        source_text = source_text[:200_000]
        if page_count < 1 or page_count > settings['max_pages']:
            raise SourceError(f'PDF reports must contain between 1 and {settings["max_pages"]} pages.')
        if render_pdf:
            pages = _render_pdf_pages(payload, settings['max_pages'])
    elif content_type == 'text/html':
        if len(payload) > MAX_HTML_BYTES:
            raise SourceError('The result webpage exceeds the HTML analysis limit.')
        parser = _TextExtractor()
        parser.feed(payload.decode('utf-8', errors='replace'))
        source_text = '\n'.join(parser.parts)[:200_000]
        if not source_text:
            raise SourceError('The result webpage did not contain readable report text.')
    elif content_type == 'image/gif':
        # Providers treat animation inconsistently; analyze only the first frame.
        from PIL import Image
        with Image.open(io.BytesIO(payload)) as image:
            first = image.convert('RGB')
            output = io.BytesIO()
            first.save(output, format='PNG', optimize=True)
            payload = output.getvalue()
            content_type = 'image/png'
    return AnalysisDocument(content_type, payload, hashlib.sha256(payload).hexdigest(), source_text, pages)


def acquire_run_source(run, provider_capabilities, analysis_settings):
    settings = {
        'max_document_mb': min(20, int(analysis_settings['max_document_mb'])),
        'max_pages': min(25, int(analysis_settings['max_pdf_pages'])),
    }
    max_bytes = _max_source_bytes(settings)
    if run.source_kind == 'upload':
        payload, declared = read_result_file(run.source_reference, max_bytes)
    else:
        payload, declared, final_url = _fetch_url(run.source_reference, max_bytes, analysis_settings['download_timeout_seconds'])
        try:
            fetched_type, _ = _sniff(payload, declared)
        except SourceError:
            fetched_type = ''
        if fetched_type == 'text/html':
            for asset_url in _html_asset_candidates(final_url, payload):
                try:
                    asset_payload, asset_type, _ = _fetch_url(
                        asset_url,
                        max_bytes,
                        analysis_settings['download_timeout_seconds'],
                    )
                    asset_content_type, _ = _sniff(asset_payload, asset_type)
                    if asset_content_type != 'text/html':
                        payload, declared = asset_payload, asset_type
                        break
                except SourceError:
                    continue
    document = prepare_document(payload, declared, settings, render_pdf=not provider_capabilities.direct_pdf)
    if document.content_type.startswith('image/') and document.content_type not in provider_capabilities.image_media_types:
        normalized = _convert_image_to_png(document.raw_bytes)
        document = AnalysisDocument(
            'image/png',
            normalized,
            hashlib.sha256(normalized).hexdigest(),
            document.source_text,
            document.pages,
        )
    return document
