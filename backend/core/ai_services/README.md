# AI Services Architecture

## Overview

The `core/ai_services/` module provides a unified, monitored interface for all LLM providers. Every AI call automatically tracks tokens, costs, and latency.

## Structure

```
core/ai_services/
├── __init__.py           # Public interface
├── base.py               # BaseLLMProvider (abstract)
├── factory.py            # get_provider() factory
└── providers/
    ├── __init__.py
    └── aws_bedrock.py    # AWS Bedrock implementation
```

## Key Components

### 1. BaseLLMProvider (Abstract Base Class)

All providers inherit from this and must implement:

```python
def invoke(text, prompt, temperature, max_tokens, **kwargs) -> Dict:
    """
    Returns standardized response:
    {
        'success': bool,
        'text': str,
        'input_tokens': int,
        'output_tokens': int,
        'estimated_cost_usd': Decimal,
        'actual_cost_usd': Decimal,
        'latency_ms': int,
        'model': str,
        'provider': str
    }
    """
```

Built-in methods:
- `estimate_cost()` - Estimate without API call
- `calculate_cost()` - Calculate actual cost from tokens
- `_standardize_response()` - Ensure consistent output format

### 2. AWSBedrockProvider

Supports:
- **Claude models** (Haiku, Sonnet, Opus)
- **Titan models**
- **Nova models**
- **Llama models**

Auto-detects model family and formats requests appropriately.

### 3. get_provider() Factory

```python
from core.ai_services import get_provider

# Create provider
provider = get_provider("AWS_BEDROCK", "anthropic.claude-3-haiku-20240307-v1:0")

# Estimate cost (no API call)
estimate = provider.estimate_cost(
    text="Long document...",
    prompt="Summarize this",
    custom_overhead=0.05,
    custom_output_ratio=0.20
)

# Actual invocation (with monitoring)
result = provider.invoke(
    text="Long document...",
    prompt="Summarize this",
    temperature=0.7,
    max_tokens=2048
)

# Access monitored data
print(f"Tokens: {result['input_tokens']} in, {result['output_tokens']} out")
print(f"Cost: ${result['actual_cost_usd']}")
print(f"Latency: {result['latency_ms']}ms")
print(f"Response: {result['text']}")
```

## Job Integration

Jobs now use the unified interface:

```python
# In process_item() method:
llm_provider = get_provider(provider, model)

if dry_run:
    result = llm_provider.estimate_cost(content, prompt)
else:
    result = llm_provider.invoke(content, prompt)

# Result automatically includes:
# - Token counts
# - Costs (estimated and actual)
# - Latency
# - Success/error status
```

## Benefits

[OK] **Unified Interface** - Same API for all providers
[OK] **Automatic Monitoring** - Every call tracked
[OK] **Cost Transparency** - Estimated vs actual costs
[OK] **Latency Tracking** - Performance metrics
[OK] **Error Handling** - Standardized error responses
[OK] **Easy Extension** - Add new providers by implementing BaseLLMProvider

## Future Providers

To add OpenAI, OpenRouter, etc.:

1. Create `providers/openai.py`
2. Extend `BaseLLMProvider`
3. Implement `invoke()` method
4. Add to `factory.py`

No changes needed to existing jobs!

## Migration Notes

**Old way:**
```python
from core.utils.bedrock_helper import invoke_bedrock_model

result = invoke_bedrock_model(
    text=content,
    model_id=model,
    prompt=prompt,
    track_cost=True
)
```

**New way:**
```python
from core.ai_services import get_provider

provider = get_provider("AWS_BEDROCK", model)
result = provider.invoke(text=content, prompt=prompt)
```

The old `invoke_bedrock_model()` function still exists for backward compatibility but internally uses `AWSBedrockProvider`.
