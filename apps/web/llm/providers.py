import json
import os
import urllib.error
import urllib.parse
import urllib.request


PROVIDER_LABELS = {
    "template": "离线模板",
    "openai": "OpenAI",
    "deepseek": "DeepSeek",
    "doubao": "豆包/火山方舟",
    "anthropic": "Claude/Anthropic",
    "gemini": "Gemini",
    "xai": "Grok/xAI",
    "openai_compatible": "OpenAI-compatible",
}


def env_name(provider, suffix):
    return f"{provider.upper()}_{suffix}"


def first_value(*values):
    for value in values:
        if value:
            return value
    return None


def provider_from_request(request_llm):
    request_llm = request_llm or {}
    provider = request_llm.get("provider") or os.getenv("LLM_PROVIDER") or "openai"
    provider = provider.strip().lower()
    if provider in {"none", "off", "template"}:
        provider = "template"
    return provider


def api_key_for(provider, request_llm):
    request_llm = request_llm or {}
    byok = (request_llm.get("api_key") or "").strip()
    if byok:
        return byok, "byok"

    env_candidates = {
        "openai": ["OPENAI_API_KEY"],
        "deepseek": ["DEEPSEEK_API_KEY"],
        "doubao": ["ARK_API_KEY", "DOUBAO_API_KEY"],
        "anthropic": ["ANTHROPIC_API_KEY", "CLAUDE_API_KEY"],
        "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "xai": ["XAI_API_KEY", "GROK_API_KEY"],
        "openai_compatible": ["OPENAI_COMPATIBLE_API_KEY"],
    }.get(provider, [env_name(provider, "API_KEY")])
    for name in env_candidates:
        value = os.getenv(name)
        if value:
            return value, name
    return None, None


def default_model(provider):
    defaults = {
        "openai": "gpt-4.1-mini",
        "deepseek": "deepseek-chat",
        "doubao": "",
        "anthropic": "",
        "gemini": "",
        "xai": "",
        "openai_compatible": "",
    }
    return defaults.get(provider, "")


def model_for(provider, request_llm):
    request_llm = request_llm or {}
    return first_value(
        (request_llm.get("model") or "").strip(),
        os.getenv(env_name(provider, "MODEL")),
        os.getenv("LLM_MODEL"),
        default_model(provider),
    )


def base_url_for(provider, request_llm):
    request_llm = request_llm or {}
    explicit = (request_llm.get("base_url") or "").strip()
    if explicit:
        return explicit
    env_value = os.getenv(env_name(provider, "BASE_URL"))
    if env_value:
        return env_value
    if provider == "openai":
        return os.getenv("OPENAI_RESPONSES_URL", "https://api.openai.com/v1/responses")
    if provider == "deepseek":
        return "https://api.deepseek.com/chat/completions"
    if provider == "doubao":
        return "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
    if provider == "xai":
        return "https://api.x.ai/v1/chat/completions"
    if provider == "anthropic":
        return "https://api.anthropic.com/v1/messages"
    if provider == "gemini":
        return "https://generativelanguage.googleapis.com/v1beta"
    if provider == "openai_compatible":
        return os.getenv("OPENAI_COMPATIBLE_BASE_URL", "")
    return ""


def parse_openai_text(payload):
    if payload.get("output_text"):
        return payload["output_text"]
    if payload.get("choices"):
        message = payload["choices"][0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content
    chunks = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if text:
                chunks.append(text)
    return "\n".join(chunks).strip()


def parse_anthropic_text(payload):
    chunks = []
    for item in payload.get("content", []):
        if item.get("type") == "text" and item.get("text"):
            chunks.append(item["text"])
    return "\n".join(chunks).strip()


def parse_gemini_text(payload):
    chunks = []
    for candidate in payload.get("candidates", []):
        for part in (candidate.get("content") or {}).get("parts", []):
            if part.get("text"):
                chunks.append(part["text"])
    return "\n".join(chunks).strip()


def request_json(url, payload, headers):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM API error {error.code}: {detail}") from error


def synthesize(provider, request_llm, system_prompt, user_prompt):
    provider = provider_from_request({"provider": provider})
    if provider == "template":
        return None
    api_key, key_source = api_key_for(provider, request_llm)
    if not api_key:
        return None
    model = model_for(provider, request_llm)
    base_url = base_url_for(provider, request_llm)
    if not model:
        raise RuntimeError(f"{PROVIDER_LABELS.get(provider, provider)} requires a model")
    if not base_url:
        raise RuntimeError(f"{PROVIDER_LABELS.get(provider, provider)} requires a base_url")

    if provider == "openai":
        payload = {
            "model": model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        data = request_json(base_url, payload, {"Authorization": f"Bearer {api_key}"})
        text = parse_openai_text(data)
    elif provider in {"deepseek", "doubao", "xai", "openai_compatible"}:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        data = request_json(base_url, payload, {"Authorization": f"Bearer {api_key}"})
        text = parse_openai_text(data)
    elif provider == "anthropic":
        payload = {
            "model": model,
            "max_tokens": 1600,
            "temperature": 0.2,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        data = request_json(
            base_url,
            payload,
            {
                "x-api-key": api_key,
                "anthropic-version": os.getenv("ANTHROPIC_VERSION", "2023-06-01"),
            },
        )
        text = parse_anthropic_text(data)
    elif provider == "gemini":
        query = urllib.parse.urlencode({"key": api_key})
        url = f"{base_url.rstrip('/')}/models/{model}:generateContent?{query}"
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {"temperature": 0.2},
        }
        data = request_json(url, payload, {})
        text = parse_gemini_text(data)
    else:
        raise RuntimeError(f"Unsupported provider: {provider}")

    if not text:
        raise RuntimeError(f"{PROVIDER_LABELS.get(provider, provider)} returned no answer text")
    return {
        "text": text,
        "provider": provider,
        "provider_label": PROVIDER_LABELS.get(provider, provider),
        "model": model,
        "key_source": "byok" if key_source == "byok" else "server",
    }


def availability(request_llm=None):
    request_llm = request_llm or {}
    provider = provider_from_request(request_llm)
    api_key, key_source = api_key_for(provider, request_llm)
    model = model_for(provider, request_llm)
    return {
        "provider": provider,
        "provider_label": PROVIDER_LABELS.get(provider, provider),
        "available": provider != "template" and bool(api_key),
        "model": model or None,
        "key_source": "byok" if key_source == "byok" else ("server" if key_source else None),
    }
