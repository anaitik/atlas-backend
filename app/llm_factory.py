"""
LLM Provider Factory.
Adapted from the POC llm_factory.py. Supports Gemini, Groq, and OpenAI.
"""

from __future__ import annotations

from typing import Optional

from langchain_core.language_models import BaseChatModel

from app.config import get_settings


def _require_api_key(provider: str, value: Optional[str], env_var: str) -> str:
    if value:
        return value
    raise ValueError(
        f"{provider} is selected but {env_var} is not configured. "
        f"Set {env_var} in Final Product/backend/.env and restart the backend."
    )


def create_llm(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: int = 4096,
) -> BaseChatModel:
    """
    Create a LangChain chat model from the specified provider.
    Falls back to config defaults if provider/model not specified.
    """
    settings = get_settings()
    provider = (provider or settings.DEFAULT_LLM_PROVIDER).lower()
    model = model or settings.DEFAULT_LLM_MODEL

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=_require_api_key("Gemini", settings.GOOGLE_API_KEY, "GOOGLE_API_KEY"),
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

    elif provider == "deepseek":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            api_key=_require_api_key("DeepSeek", settings.DEEPSEEK_API_KEY, "DEEPSEEK_API_KEY"),
            base_url=settings.DEEPSEEK_BASE_URL,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    elif provider == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=model,
            groq_api_key=_require_api_key("Groq", settings.GROQ_API_KEY, "GROQ_API_KEY"),
            temperature=temperature,
            max_tokens=max_tokens,
        )

    elif provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            api_key=_require_api_key("OpenAI", settings.OPENAI_API_KEY, "OPENAI_API_KEY"),
            temperature=temperature,
            max_tokens=max_tokens,
        )

    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")
