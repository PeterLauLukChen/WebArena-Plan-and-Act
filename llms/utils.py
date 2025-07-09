import argparse
from typing import Any

try:
    from vertexai.preview.generative_models import Image
    from llms import generate_from_gemini_completion
except:
    print('Google Cloud not set up, skipping import of vertexai.preview.generative_models.Image and llms.generate_from_gemini_completion')

from llms import (
    generate_from_huggingface_completion,
    generate_from_openai_chat_completion,
    generate_from_openai_completion,
    generate_with_api,
    lm_config,
)

APIInput = str | list[Any] | dict[str, Any]


def call_llm(
    lm_config: lm_config.LMConfig,
    prompt: APIInput,
    api_key = None,
    base_url = None
) -> str:
    response: str
    if lm_config.provider == "openai":
        # Force chat mode for Claude and DeepSeek models via OpenRouter
        is_openrouter_chat_model = (base_url and "openrouter.ai" in base_url and 
                                   ("claude" in lm_config.model.lower() or 
                                    "deepseek" in lm_config.model.lower()))
        
        if lm_config.mode == "chat" or is_openrouter_chat_model:
            # Convert completion prompt to chat format if needed
            if isinstance(prompt, str) and is_openrouter_chat_model:
                # Convert string prompt to chat format for OpenRouter chat models
                prompt = [{"role": "user", "content": prompt}]
            
            assert isinstance(prompt, list)
            # For DeepSeek models, don't limit max_tokens since they're free
            max_tokens_param = None if "deepseek" in lm_config.model.lower() else lm_config.gen_config["max_tokens"]
            
            response = generate_from_openai_chat_completion(
                messages=prompt,
                model=lm_config.model,
                temperature=lm_config.gen_config["temperature"],
                top_p=lm_config.gen_config["top_p"],
                context_length=lm_config.gen_config["context_length"],
                max_tokens=max_tokens_param,
                stop_token=None,
                api_key=api_key,
                base_url=base_url,
            )
        elif lm_config.mode == "completion":
            if isinstance(prompt, list):
                # Convert chat prompt to a single string using the Qwen template
                full_prompt = ""
                for message in prompt:
                    # Append role and content wrapped in the special tokens
                    full_prompt += f'<|im_start|>{message["role"]}\n{message["content"]}<|im_end|>\n'
                # Add the final prompt for the assistant to start generating
                full_prompt += "<|im_start|>assistant\n"
                prompt = full_prompt

            assert isinstance(prompt, str)
            response = generate_from_openai_completion(
                prompt=prompt,
                model=lm_config.model,
                temperature=lm_config.gen_config["temperature"],
                max_tokens=lm_config.gen_config["max_tokens"],
                top_p=lm_config.gen_config["top_p"],
                stop_token=lm_config.gen_config["stop_token"],
                api_key=api_key,
                base_url=base_url
            )
        else:
            raise ValueError(
                f"OpenAI models do not support mode {lm_config.mode}"
            )
    elif lm_config.provider == "huggingface":
        assert isinstance(prompt, str)
        response = generate_from_huggingface_completion(
            prompt=prompt,
            model_endpoint=lm_config.gen_config["model_endpoint"],
            temperature=lm_config.gen_config["temperature"],
            top_p=lm_config.gen_config["top_p"],
            stop_sequences=lm_config.gen_config["stop_sequences"],
            max_new_tokens=lm_config.gen_config["max_new_tokens"],
        )
    elif lm_config.provider == "google":
        assert isinstance(prompt, list)
        assert all(
            [isinstance(p, str) or isinstance(p, Image) for p in prompt]
        )
        response = generate_from_gemini_completion(
            prompt=prompt,
            engine=lm_config.model,
            temperature=lm_config.gen_config["temperature"],
            max_tokens=lm_config.gen_config["max_tokens"],
            top_p=lm_config.gen_config["top_p"],
        )
    elif lm_config.provider in ["api", "finetune"]:
        if isinstance(prompt, list):
            # Simple concatenation for chat history
            # NOTE: This is a simplified approach. For models that require
            # special tokens (e.g., [INST], <|im_start|>), a more
            # sophisticated application of the tokenizer's chat template
            # might be needed.
            full_prompt = ""
            for message in prompt:
                # Assuming message is a dict with 'role' and 'content'
                if "content" in message:
                    full_prompt += message["content"] + "\n"
            prompt = full_prompt.strip()

        assert isinstance(prompt, str)

        args = {
            "temperature": lm_config.gen_config["temperature"],   # openai, gemini, claude
            "max_tokens": lm_config.gen_config["max_tokens"],     # openai, gemini, claude
            "top_k": lm_config.gen_config["top_p"],               # qwen
        }
        response = generate_with_api(prompt, lm_config.model, args)

    else:
        raise NotImplementedError(
            f"Provider {lm_config.provider} not implemented"
        )

    return response
