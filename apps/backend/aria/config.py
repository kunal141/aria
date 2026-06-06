"""
ARIA Config — LLM provider factory + LangSmith setup

Supported providers (set LLM_PROVIDER in .env):
  anthropic   Claude (Haiku / Sonnet / Opus)         — ANTHROPIC_API_KEY
  ollama      Llama / Gemma / Qwen local              — no key, runs on your machine
  groq        Llama / Gemma / Mixtral (free tier)     — GROQ_API_KEY
  google      Gemma 3/4, Gemini Flash/Pro             — GOOGLE_API_KEY
  openrouter  Any model via unified API               — OPENROUTER_API_KEY
  kimi        Moonshot AI (Kimi)                      — MOONSHOT_API_KEY
  qwen        Alibaba DashScope (Qwen-Max/Plus)       — DASHSCOPE_API_KEY
  openai      GPT-4o / GPT-4o-mini                   — OPENAI_API_KEY

Four routing tiers (Week 16+):
  get_fast_llm()     → FAST_LLM_PROVIDER / FAST_LLM_MODEL  (classification, routing, SLMs)
  get_smart_llm()    → SMART_LLM_PROVIDER / SMART_LLM_MODEL (PR review, KPI, normal tasks)
  get_frontier_llm() → FRONTIER_LLM_PROVIDER / FRONTIER_LLM_MODEL (leadership, complex, high-stakes)
  get_routed_llm()   → ModelRouter decides tier from task signals, returns right LLM
  get_llm()          → LLM_PROVIDER / LLM_MODEL             (general fallback)
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── LangSmith tracing (optional — only when API key present) ──────────────────
_langchain_key = os.getenv("LANGCHAIN_API_KEY") or os.getenv("LANGSMITH_API_KEY")
if _langchain_key:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = _langchain_key
    os.environ["LANGCHAIN_PROJECT"] = os.getenv("LANGCHAIN_PROJECT", os.getenv("LANGSMITH_PROJECT", "ARIA"))
else:
    os.environ["LANGCHAIN_TRACING_V2"] = "false"


# ── LLM factory ───────────────────────────────────────────────────────────────

def get_llm(
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0,
    **kwargs,
):
    """
    Return a LangChain chat model for the given provider.
    Falls back to env vars LLM_PROVIDER / LLM_MODEL if args not supplied.
    """
    provider = (provider or os.getenv("LLM_PROVIDER", "anthropic")).lower()

    # ── Anthropic (Claude) ────────────────────────────────────────────────────
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model or os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001"),
            temperature=temperature,
            **kwargs,
        )

    # ── Ollama (local — Llama, Gemma, Qwen, Mistral, etc.) ───────────────────
    if provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model=model or os.getenv("LLM_MODEL", "llama3.2"),
            temperature=temperature,
            **kwargs,
        )

    # ── Groq (cloud, generous free tier — Llama 3.3, Gemma 2, Mixtral) ───────
    if provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(
            model=model or os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"),
            temperature=temperature,
            **kwargs,
        )

    # ── Google AI (Gemma 3/4 via Google AI Studio, or Gemini Flash/Pro) ──────
    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model or os.getenv("LLM_MODEL", "gemma-3-27b-it"),
            temperature=temperature,
            **kwargs,
        )

    # ── OpenRouter (Qwen, Llama, Mistral, many others via unified API) ────────
    if provider == "openrouter":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model or os.getenv("LLM_MODEL", "qwen/qwen-2.5-72b-instruct"),
            temperature=temperature,
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
            **kwargs,
        )

    # ── Kimi / Moonshot AI (OpenAI-compatible API) ────────────────────────────
    if provider == "kimi":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model or os.getenv("LLM_MODEL", "moonshot-v1-8k"),
            temperature=temperature,
            base_url="https://api.moonshot.cn/v1",
            api_key=os.getenv("MOONSHOT_API_KEY"),
            **kwargs,
        )

    # ── Qwen / Alibaba DashScope (OpenAI-compatible API) ─────────────────────
    if provider == "qwen":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model or os.getenv("LLM_MODEL", "qwen-max"),
            temperature=temperature,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            **kwargs,
        )

    # ── OpenAI ────────────────────────────────────────────────────────────────
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model or os.getenv("LLM_MODEL", "gpt-4o-mini"),
            temperature=temperature,
            **kwargs,
        )

    raise ValueError(
        f"Unknown LLM provider: '{provider}'. "
        "Valid: anthropic, ollama, groq, google, openrouter, kimi, qwen, openai"
    )


def get_fast_llm(**kwargs):
    """
    Cheap/fast model for classification, routing, simple extraction.
    Set FAST_LLM_PROVIDER + FAST_LLM_MODEL in .env to override.

    Good defaults:
      anthropic → claude-haiku-4-5-20251001
      ollama    → llama3.2 (3B, instant)
      groq      → llama-3.1-8b-instant (free, ~500 tok/s)
      google    → gemma-3-4b-it
    """
    provider = os.getenv("FAST_LLM_PROVIDER") or os.getenv("LLM_PROVIDER", "anthropic")
    model    = os.getenv("FAST_LLM_MODEL") or None
    return get_llm(provider=provider, model=model, **kwargs)


def get_smart_llm(**kwargs):
    """
    Best available model for high-stakes tasks: PR review, KPI analysis, leadership summaries.
    Set SMART_LLM_PROVIDER + SMART_LLM_MODEL in .env to override.

    Good defaults:
      anthropic   → claude-sonnet-4-6
      ollama      → qwen2.5-coder:7b or llama3.1:8b
      groq        → llama-3.3-70b-versatile (free)
      google      → gemma-3-27b-it
      openrouter  → qwen/qwen-2.5-72b-instruct
      kimi        → moonshot-v1-32k (good for long PRs)
    """
    provider = os.getenv("SMART_LLM_PROVIDER") or os.getenv("LLM_PROVIDER", "anthropic")
    model    = os.getenv("SMART_LLM_MODEL") or None
    return get_llm(provider=provider, model=model, **kwargs)


def get_frontier_llm(**kwargs):
    """
    Highest-quality model for leadership briefs, complex reasoning, high-stakes decisions.
    Set FRONTIER_LLM_PROVIDER + FRONTIER_LLM_MODEL in .env to override.

    Good defaults:
      anthropic → claude-opus-4-7
      openrouter → anthropic/claude-opus-4-7
      google    → gemini-2.5-pro
    Falls back to smart_llm if no frontier config is set.
    """
    provider = os.getenv("FRONTIER_LLM_PROVIDER") or os.getenv("SMART_LLM_PROVIDER") or os.getenv("LLM_PROVIDER", "anthropic")
    model    = os.getenv("FRONTIER_LLM_MODEL") or os.getenv("SMART_LLM_MODEL") or None
    # Default frontier model per provider
    if not model:
        _frontier_defaults = {
            "anthropic":  "claude-opus-4-7",
            "openrouter": "anthropic/claude-opus-4-7",
            "google":     "gemini-2.5-pro",
            "openai":     "gpt-4o",
        }
        model = _frontier_defaults.get(provider)
    return get_llm(provider=provider, model=model, **kwargs)


# Providers that keep data on-premises; external providers are not valid local targets.
_LOCAL_PROVIDERS = frozenset(["ollama", "vllm"])


def get_routed_llm(
    task_type: str = None,
    data_sensitivity: str = None,
    audience: str = None,
    complexity: str = None,
    input_length: int = 0,
    **kwargs,
):
    """
    ModelRouter-driven LLM selection — Week 16+.
    Routes to fast / smart / frontier based on task signals.

    Privacy enforcement (runs BEFORE the broad routing try/except):
      confidential / restricted must use a local provider (ollama / vllm).
      External providers (anthropic, openai, etc.) are rejected with ValueError.
      Local provider init failures propagate — no silent external fallback.
      Week 25+: vLLM enforces this at the infrastructure layer.
    """
    # ── Privacy gate — intentionally outside the broad except below ───────────
    if data_sensitivity in ("confidential", "restricted"):
        local_provider = os.getenv("LOCAL_LLM_PROVIDER", "").lower()
        if local_provider:
            if local_provider not in _LOCAL_PROVIDERS:
                raise ValueError(
                    f"LOCAL_LLM_PROVIDER='{local_provider}' is not a local provider. "
                    f"Confidential/restricted data must use one of: {sorted(_LOCAL_PROVIDERS)}. "
                    "Set LOCAL_LLM_PROVIDER=ollama or LOCAL_LLM_PROVIDER=vllm."
                )
            # Allow init failures to propagate — do NOT silently route to external.
            return get_llm(provider=local_provider, **kwargs)
        if os.getenv("LLM_PROVIDER", "").lower() == "ollama":
            return get_fast_llm(**kwargs)
        import warnings
        warnings.warn(
            f"[ARIA] data_sensitivity='{data_sensitivity}' requires a local provider "
            "but LOCAL_LLM_PROVIDER is not set. Data will be sent to an external API. "
            "Set LOCAL_LLM_PROVIDER=ollama (Week 25+: use vLLM) to enforce privacy.",
            stacklevel=3,
        )
        # Fall through to normal routing (v1 limitation, vLLM enforces at Week 25).

    # ── Normal routing — broad except covers ModelRouter import / config errors ─
    try:
        from aria.routing.model_router import route
        decision = route(task_type, data_sensitivity, audience, complexity, input_length)
        if decision.tier == "fast":
            return get_fast_llm(**kwargs)
        if decision.tier == "frontier":
            return get_frontier_llm(**kwargs)
        return get_smart_llm(**kwargs)
    except Exception:
        return get_smart_llm(**kwargs)


def has_llm() -> bool:
    """
    True if the selected provider has the necessary credential / runtime available.
    Used by skills to decide whether to run real inference or return mock output.
    """
    provider = os.getenv("LLM_PROVIDER", "anthropic").lower()
    _checks = {
        "anthropic":  bool(os.getenv("ANTHROPIC_API_KEY")),
        "ollama":     True,   # local, no key needed
        "groq":       bool(os.getenv("GROQ_API_KEY")),
        "google":     bool(os.getenv("GOOGLE_API_KEY")),
        "openrouter": bool(os.getenv("OPENROUTER_API_KEY")),
        "kimi":       bool(os.getenv("MOONSHOT_API_KEY")),
        "qwen":       bool(os.getenv("DASHSCOPE_API_KEY")),
        "openai":     bool(os.getenv("OPENAI_API_KEY")),
    }
    return _checks.get(provider, False)
