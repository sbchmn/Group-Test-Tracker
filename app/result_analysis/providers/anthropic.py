import base64

from .base import SYSTEM_PROMPT, classify_sdk_error, context_prompt, parse_json_text
from ..types import AnalysisExtraction, ProviderCapabilities, ProviderHealth, EXTRACTION_JSON_SCHEMA, validate_extraction


class AnthropicResultAnalysisProvider:
    capabilities = ProviderCapabilities(
        direct_pdf=True,
        image_media_types=('image/jpeg', 'image/png', 'image/gif', 'image/webp'),
    )

    def __init__(self, api_key, model):
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError('Anthropic SDK is not installed.') from exc
        self.client = anthropic.Anthropic(api_key=api_key, timeout=60.0, max_retries=0)
        self.model = model

    @staticmethod
    def _source(media_type, payload):
        return {'type': 'base64', 'media_type': media_type, 'data': base64.b64encode(payload).decode('ascii')}

    def test_connection(self):
        try:
            self.client.messages.create(model=self.model, max_tokens=8, messages=[{'role': 'user', 'content': 'Reply OK.'}])
            return ProviderHealth(True, 'Connection successful.')
        except Exception as exc:
            raise classify_sdk_error(exc) from exc

    def analyze(self, document, context):
        content = []
        if document.content_type == 'application/pdf':
            content.append({'type': 'document', 'source': self._source('application/pdf', document.raw_bytes)})
        elif document.content_type.startswith('image/'):
            content.append({'type': 'image', 'source': self._source(document.content_type, document.raw_bytes)})
        elif document.source_text:
            content.append({'type': 'text', 'text': document.source_text})
        content.append({'type': 'text', 'text': context_prompt(context)})
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=5000,
                system=SYSTEM_PROMPT,
                messages=[{'role': 'user', 'content': content}],
                output_config={'format': {'type': 'json_schema', 'schema': EXTRACTION_JSON_SCHEMA}},
            )
            text_blocks = [block.text for block in response.content if getattr(block, 'type', None) == 'text']
            payload = validate_extraction(parse_json_text(''.join(text_blocks)))
            usage = getattr(response, 'usage', None)
            usage_data = usage.model_dump() if hasattr(usage, 'model_dump') else {}
            return AnalysisExtraction(
                data=payload,
                provider_model=str(getattr(response, 'model', None) or self.model),
                request_id=str(getattr(response, 'id', '') or '') or None,
                usage=usage_data,
            )
        except ValueError:
            raise
        except Exception as exc:
            from .base import ProviderError
            if isinstance(exc, ProviderError):
                raise
            raise classify_sdk_error(exc) from exc
