from .base import SYSTEM_PROMPT, classify_sdk_error, context_prompt, data_url, parse_json_text
from ..types import AnalysisExtraction, ProviderCapabilities, ProviderHealth, EXTRACTION_JSON_SCHEMA, validate_extraction


class XAIResultAnalysisProvider:
    capabilities = ProviderCapabilities(direct_pdf=False, image_media_types=('image/jpeg', 'image/png'))

    def __init__(self, api_key, model):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError('OpenAI-compatible SDK is not installed.') from exc
        self.client = OpenAI(api_key=api_key, base_url='https://api.x.ai/v1', timeout=60.0, max_retries=0)
        self.model = model

    def test_connection(self):
        try:
            self.client.chat.completions.create(model=self.model, max_tokens=8, messages=[{'role': 'user', 'content': 'Reply OK.'}])
            return ProviderHealth(True, 'Connection successful.')
        except Exception as exc:
            raise classify_sdk_error(exc) from exc

    def analyze(self, document, context):
        content = []
        if document.source_text:
            content.append({'type': 'text', 'text': document.source_text})
        pages = document.pages
        if not pages and document.content_type in self.capabilities.image_media_types:
            content.append({'type': 'image_url', 'image_url': {'url': data_url(document.content_type, document.raw_bytes)}})
        else:
            for page in pages:
                content.append({'type': 'image_url', 'image_url': {'url': data_url(page.media_type, page.image_bytes)}})
        content.append({'type': 'text', 'text': context_prompt(context)})
        try:
            raw_response = self.client.chat.completions.with_raw_response.create(
                model=self.model,
                max_tokens=5000,
                messages=[
                    {'role': 'system', 'content': SYSTEM_PROMPT},
                    {'role': 'user', 'content': content},
                ],
                response_format={
                    'type': 'json_schema',
                    'json_schema': {
                        'name': 'laboratory_result_extraction',
                        'strict': True,
                        'schema': EXTRACTION_JSON_SCHEMA,
                    },
                },
            )
            response = raw_response.parse()
            choice = response.choices[0].message.content
            payload = validate_extraction(parse_json_text(choice))
            usage = getattr(response, 'usage', None)
            usage_data = usage.model_dump() if hasattr(usage, 'model_dump') else {}
            headers = raw_response.headers
            zdr = headers.get('x-zero-data-retention') if hasattr(headers, 'get') else None
            return AnalysisExtraction(
                data=payload,
                provider_model=str(getattr(response, 'model', None) or self.model),
                request_id=str(getattr(response, 'id', '') or '') or None,
                usage=usage_data,
                provider_metadata={'zero_data_retention': zdr == 'true'} if zdr in ('true', 'false') else {},
            )
        except ValueError:
            raise
        except Exception as exc:
            from .base import ProviderError
            if isinstance(exc, ProviderError):
                raise
            raise classify_sdk_error(exc) from exc
