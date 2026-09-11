from .base import (
    SYSTEM_PROMPT, classify_sdk_error, context_prompt, data_url, parse_json_text,
)
from ..types import (
    AnalysisExtraction, ProviderCapabilities, ProviderHealth, EXTRACTION_JSON_SCHEMA,
    validate_extraction,
)


class OpenAIResultAnalysisProvider:
    capabilities = ProviderCapabilities(
        direct_pdf=True,
        image_media_types=('image/jpeg', 'image/png', 'image/webp', 'image/gif'),
    )

    def __init__(self, api_key, model):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError('OpenAI SDK is not installed.') from exc
        self.client = OpenAI(api_key=api_key, timeout=60.0, max_retries=0)
        self.model = model

    def _content(self, document, prompt):
        content = []
        if document.content_type == 'application/pdf':
            content.append({
                'type': 'input_file',
                'filename': 'lab-report.pdf',
                'file_data': data_url('application/pdf', document.raw_bytes),
            })
        elif document.content_type.startswith('image/'):
            content.append({'type': 'input_image', 'image_url': data_url(document.content_type, document.raw_bytes)})
        elif document.source_text:
            content.append({'type': 'input_text', 'text': document.source_text})
        content.append({'type': 'input_text', 'text': prompt})
        return content

    def _request(self, prompt, document=None):
        content = [{'type': 'input_text', 'text': prompt}] if document is None else self._content(document, prompt)
        return self.client.responses.create(
            model=self.model,
            store=False,
            max_output_tokens=5000,
            instructions=SYSTEM_PROMPT,
            input=[{'role': 'user', 'content': content}],
            text={
                'format': {
                    'type': 'json_schema',
                    'name': 'laboratory_result_extraction',
                    'strict': True,
                    'schema': EXTRACTION_JSON_SCHEMA,
                }
            },
        )

    def test_connection(self):
        try:
            self.client.responses.create(model=self.model, store=False, max_output_tokens=8, input='Reply OK.')
            return ProviderHealth(True, 'Connection successful.')
        except Exception as exc:
            raise classify_sdk_error(exc) from exc

    def analyze(self, document, context):
        try:
            response = self._request(context_prompt(context), document=document)
            payload = validate_extraction(parse_json_text(response.output_text))
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
