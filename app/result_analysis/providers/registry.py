from .anthropic import AnthropicResultAnalysisProvider
from .openai import OpenAIResultAnalysisProvider
from .xai import XAIResultAnalysisProvider


def build_provider(config):
    provider = config['name']
    if provider == 'openai':
        return OpenAIResultAnalysisProvider(config['api_key'], config['model'])
    if provider == 'xai':
        return XAIResultAnalysisProvider(config['api_key'], config['model'])
    if provider == 'anthropic':
        return AnthropicResultAnalysisProvider(config['api_key'], config['model'])
    raise ValueError('Unsupported result analysis provider.')
