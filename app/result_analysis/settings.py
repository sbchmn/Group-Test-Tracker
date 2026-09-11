import os

from ..models import NotificationConfig


PROVIDERS = ('openai', 'xai', 'anthropic')
DEFAULT_MODELS = {
    'openai': 'gpt-5.4-mini',
    'xai': 'grok-4.6',
    'anthropic': 'claude-sonnet-5',
}
ENV_KEYS = {
    'openai': 'OPENAI_API_KEY',
    'xai': 'XAI_API_KEY',
    'anthropic': 'ANTHROPIC_API_KEY',
}


def _config_map():
    return {item.key: item.value for item in NotificationConfig.query.all()}


def _bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def _bounded_int(value, default, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def get_analysis_settings():
    configs = _config_map()
    provider = str(configs.get('result_analysis_provider') or 'openai').strip().lower()
    if provider not in PROVIDERS:
        provider = 'openai'
    providers = {}
    for name in PROVIDERS:
        providers[name] = {
            'enabled': _bool(configs.get(f'result_analysis_{name}_enabled'), default=name == 'openai'),
            'model': str(configs.get(f'result_analysis_{name}_model') or DEFAULT_MODELS[name]).strip(),
            'api_key': '',
        }
        providers[name]['api_key'] = str(
            os.environ.get(ENV_KEYS[name]) or configs.get(f'result_analysis_{name}_api_key') or ''
        ).strip()
    return {
        'enabled': _bool(configs.get('result_analysis_enabled'), default=False),
        'provider': provider,
        'providers': providers,
        'max_document_mb': _bounded_int(configs.get('result_analysis_max_document_mb'), 20, 1, 20),
        'max_pdf_pages': _bounded_int(configs.get('result_analysis_max_pdf_pages'), 25, 1, 25),
        'download_timeout_seconds': _bounded_int(configs.get('result_analysis_download_timeout_seconds'), 20, 3, 60),
        'max_attempts': _bounded_int(configs.get('result_analysis_max_attempts'), 3, 1, 5),
        'lease_seconds': _bounded_int(configs.get('result_analysis_lease_seconds'), 300, 30, 1800),
    }


def provider_config(provider=None):
    settings = get_analysis_settings()
    selected = provider or settings['provider']
    if selected not in PROVIDERS:
        raise ValueError('Unsupported result analysis provider.')
    config = dict(settings['providers'][selected])
    config['name'] = selected
    if not config['enabled']:
        raise ValueError(f'{selected} result analysis is disabled.')
    if not config['api_key']:
        raise ValueError(f'{selected} API credentials are not configured.')
    return config
