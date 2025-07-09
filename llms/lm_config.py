"""Config for language models."""

from __future__ import annotations

import argparse
import dataclasses
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LMConfig:
    """A config for a language model.

    Attributes:
        provider: The name of the API provider.
        model: The name of the model.
        model_cls: The Python class corresponding to the model, mostly for
             Hugging Face transformers.
        tokenizer_cls: The Python class corresponding to the tokenizer, mostly
            for Hugging Face transformers.
        mode: The mode of the API calls, e.g., "chat" or "generation".
        base_url: The base URL for the API provider.
    """

    provider: str
    model: str
    model_cls: type | None = None
    tokenizer_cls: type | None = None
    mode: str | None = None
    gen_config: dict[str, Any] = dataclasses.field(default_factory=dict)
    base_url: str | None = None


def construct_llm_config(args: argparse.Namespace) -> LMConfig:
    # provider
    provider = args.provider
    model = args.model
    mode = args.mode

    # generation config
    gen_config: dict[str, Any] = {
        "temperature": args.temperature,
        "top_p": args.top_p,
        "context_length": args.context_length,
        "max_tokens": args.max_tokens,
        "stop_token": args.stop_token,
        "max_obs_length": args.max_obs_length,
        "max_retry": args.max_retry
    }

    # url can be the model for some providers
    base_url = None
    if provider == "openai":
        if model.startswith("http"):
            base_url = model
            model = getattr(args, 'vllm_model_name', 'vllm')
    elif provider == "huggingface":
        gen_config["max_new_tokens"] = args.max_tokens
        gen_config["stop_sequences"] = (
            [args.stop_token] if args.stop_token else None
        )
        gen_config["model_endpoint"] = args.model_endpoint
    else:
        raise NotImplementedError(f"provider {provider} not implemented")

    return LMConfig(
        provider=provider, model=model, mode=mode, gen_config=gen_config, base_url=base_url
    )
