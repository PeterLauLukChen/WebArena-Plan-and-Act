import json
import re
from pathlib import Path
from typing import Any, TypedDict
from PIL import Image

from browser_env import Action, ActionParsingError, Trajectory
from browser_env.env_config import URL_MAPPINGS
from browser_env.utils import StateInfo, pil_to_b64, pil_to_vertex
from llms import lm_config
from llms.tokenizers import Tokenizer
from llms.utils import APIInput


class Instruction(TypedDict):
    """Instruction for constructing prompt"""

    intro: str
    examples: list[tuple[str, str]]
    template: str
    meta_data: dict[str, Any]


class PromptConstructor(object):
    def __init__(
        self,
        instruction_path: str | Path,
        lm_config: lm_config.LMConfig,
        tokenizer: Tokenizer,
    ):
        self.instruction_path = Path(instruction_path)
        self.obs_modality = "text"
        self.lm_config = lm_config
        instruction = json.load(open(self.instruction_path))
        instruction["examples"] = [tuple(e) for e in instruction["examples"]]
        self.instruction: Instruction = instruction
        self.tokenizer = tokenizer

    def get_lm_api_input(
        self, intro: str, examples: list[tuple[str, str]], current: str
    ) -> APIInput:

        """Return the require format for an API"""
        message: list[dict[str, str]] | str
        if "openai" in self.lm_config.provider:
            if self.lm_config.mode == "chat":
                message = [{"role": "system", "content": intro}]
                for (x, y) in examples:
                    message.append(
                        {
                            "role": "system",
                            "name": "example_user",
                            "content": x,
                        }
                    )
                    message.append(
                        {
                            "role": "system",
                            "name": "example_assistant",
                            "content": y,
                        }
                    )
                message.append({"role": "user", "content": current})
                return message
            elif self.lm_config.mode == "completion":
                message = f"{intro}\n\n"
                message += "Here are a few examples:\n"
                for example in examples:
                    message += f"Observation\n:{example[0]}\n\n"
                    message += f"Action: {example[1]}\n\n"
                message += "Now make prediction given the observation\n\n"
                message += f"Observation\n:{current}\n\n"
                message += "Action:"
                return message
            else:
                raise ValueError(
                    f"OpenAI models do not support mode {self.lm_config.mode}"
                )
        elif "huggingface" in self.lm_config.provider:
            # https://huggingface.co/blog/llama2#how-to-prompt-llama-2
            # https://github.com/facebookresearch/llama/blob/main/llama/generation.py#L320
            if "Llama-2" in self.lm_config.model:
                if self.lm_config.mode == "chat":
                    B_INST, E_INST = "]", "]"
                    B_SYS, E_SYS = "<<SYS>>\n", "\n<</SYS>>\n\n"
                    BOS, EOS = "", "]"
                    # adding the system message to be the starting of the first example
                    examples = [
                        (
                            B_SYS + intro + E_SYS + examples[0][0],
                            examples[0][1],
                        )
                    ] + examples[1:]
                    message = "".join(
                        [
                            f"{BOS}{B_INST} {x.strip()} {E_INST} {y.strip()} {EOS}"
                            for (x, y) in examples
                        ]
                    )
                    # add the current observation
                    message += f"{BOS}{B_INST} {current.strip()} {E_INST} {self.instruction['meta_data'].get('force_prefix', '')}"

                    return message
                else:
                    raise ValueError("Only chat mode is supported for Llama-2")
            else:
                raise ValueError(
                    f"Huggingface models do not support model_tag {self.lm_config.gen_config['model_tag']}"
                )
        else:
            raise NotImplementedError(
                f"Provider {self.lm_config.provider} not implemented"
            )

    def construct(
        self,
        trajectory: Trajectory,
        intent: str,
        meta_data: dict[str, Any] = {},
    ) -> APIInput:
        raise NotImplementedError

    def map_url_to_real(self, url: str) -> str:
        """Map the urls to their real world counterparts"""
        for i, j in URL_MAPPINGS.items():
            if i in url:
                url = url.replace(i, j)
        return url

    def map_url_to_local(self, url: str) -> str:
        """Map the urls to their local counterparts"""
        for i, j in URL_MAPPINGS.items():
            if j in url:
                url = url.replace(j, i)
            # https
            if j.replace("http", "https") in url:
                url = url.replace(j.replace("http", "https"), i)
        return url

    def _extract_action(self, response: str) -> str:
        raise NotImplementedError

    def extract_action(self, response: str) -> str:
        response = self._extract_action(response)
        response = self.map_url_to_local(response)
        return response


class DirectPromptConstructor(PromptConstructor):
    """The agent will direct predict the action"""

    def __init__(
        self,
        instruction_path: str | Path,
        lm_config: lm_config.LMConfig,
        tokenizer: Tokenizer,
    ):
        super().__init__(instruction_path, lm_config, tokenizer)

    def construct(
        self,
        trajectory: Trajectory,
        intent: str,
        meta_data: dict[str, Any] = {},
    ) -> APIInput:
        """Construct prompt given the trajectory"""
        intro = self.instruction["intro"]
        examples = self.instruction["examples"]
        template = self.instruction["template"]
        keywords = self.instruction["meta_data"]["keywords"]
        state_info: StateInfo = trajectory[-1]  # type: ignore[assignment]

        obs = state_info["observation"][self.obs_modality]
        max_obs_length = self.lm_config.gen_config["max_obs_length"]
        if max_obs_length:
            if self.lm_config.provider == "google":
                print("NOTE: This is a Gemini model, so we use characters instead of tokens for max_obs_length.")
                obs = obs[:max_obs_length]
            else:
                obs = self.tokenizer.decode(self.tokenizer.encode(obs)[:max_obs_length])  # type: ignore[arg-type]

        page = state_info["info"]["page"]
        url = page.url
        previous_action_str = meta_data["action_history"][-1]

        # input x
        current = template.format(
            objective=intent,
            url=self.map_url_to_real(url),
            observation=obs,
            previous_action=previous_action_str,
        )

        # make sure all keywords are replaced
        assert all([f"{{k}}" not in current for k in keywords])
        prompt = self.get_lm_api_input(intro, examples, current)
        return prompt

    def _extract_action(self, response: str) -> str:
        action_splitter = self.instruction["meta_data"]["action_splitter"]
        pattern = rf"{action_splitter}((.|\n)*?){action_splitter}"
        match = re.search(pattern, response)
        if match:
            return match.group(1).strip()
        else:
            raise ActionParsingError(
                f"Cannot parse action from response {response}"
            )


class CoTPromptConstructor(PromptConstructor):
    """The agent will perform step-by-step reasoning before the answer"""

    def __init__(
        self,
        instruction_path: str | Path,
        lm_config: lm_config.LMConfig,
        tokenizer: Tokenizer,
    ):
        super().__init__(instruction_path, lm_config, tokenizer)
        self.answer_phrase = self.instruction["meta_data"].get("answer_phrase", "")

    def construct(
        self,
        trajectory: Trajectory,
        intent: str,
        meta_data: dict[str, Any] = {},
    ) -> APIInput:
        intro = self.instruction["intro"]
        examples = self.instruction["examples"]
        template = self.instruction["template"]
        keywords = self.instruction["meta_data"]["keywords"]
        state_info: StateInfo = trajectory[-1]  # type: ignore[assignment]

        obs = state_info["observation"][self.obs_modality]
        max_obs_length = self.lm_config.gen_config["max_obs_length"]
        if max_obs_length:
            if self.lm_config.provider == "google":
                print("NOTE: This is a Gemini model, so we use characters instead of tokens for max_obs_length.")
                obs = obs[:max_obs_length]
            else:
                obs = self.tokenizer.decode(self.tokenizer.encode(obs)[:max_obs_length])  # type: ignore[arg-type]

        page = state_info["info"]["page"]
        url = page.url
        previous_action_str = (
            meta_data["action_history"][-1]
            if meta_data["action_history"]
            else "None"
        )
        current = template.format(
            objective=intent,
            url=self.map_url_to_real(url),
            observation=obs,
            previous_action=previous_action_str,
        )

        assert all([f"{{k}}" not in current for k in keywords])

        prompt = self.get_lm_api_input(intro, examples, current)
        return prompt

    def _extract_action(self, response: str) -> str:
        # find the first occurence of action
        action_splitter = self.instruction["meta_data"]["action_splitter"]
        pattern = rf"{action_splitter}((.|\n)*?){action_splitter}"
        match = re.search(pattern, response)
        if match:
            return match.group(1).strip()
        else:
            raise ActionParsingError(
                f'Cannot find the answer phrase "{self.answer_phrase}" in "{response}"'
            )


class MultimodalCoTPromptConstructor(CoTPromptConstructor):
    """The agent will perform step-by-step reasoning before the answer"""

    def __init__(
        self,
        instruction_path: str | Path,
        lm_config: lm_config.LMConfig,
        tokenizer: Tokenizer,
    ):
        super().__init__(instruction_path, lm_config, tokenizer)
        self.answer_phrase = self.instruction["meta_data"]["answer_phrase"]

    def construct(
        self,
        trajectory: Trajectory,
        intent: str,
        page_screenshot_img: Image.Image,
        images: list[Image.Image],
        meta_data: dict[str, Any] = {},
    ) -> APIInput:
        intro = self.instruction["intro"]
        examples = self.instruction["examples"]
        template = self.instruction["template"]
        keywords = self.instruction["meta_data"]["keywords"]
        state_info: StateInfo = trajectory[-1]  # type: ignore[assignment]

        obs = state_info["observation"][self.obs_modality]
        max_obs_length = self.lm_config.gen_config["max_obs_length"]
        if max_obs_length:
            if self.lm_config.provider in ["google", "api", "finetune"]:
                print("NOTE: This is a Gemini / API model, so we use characters instead of tokens for max_obs_length.")
                obs = obs[:max_obs_length]
            else:
                obs = self.tokenizer.decode(self.tokenizer.encode(obs)[:max_obs_length])  # type: ignore[arg-type]

        page = state_info["info"]["page"]
        url = page.url
        previous_action_str = meta_data["action_history"][-1]
        current = template.format(
            objective=intent,
            url=self.map_url_to_real(url),
            observation=obs,
            previous_action=previous_action_str,
        )

        assert all([f"{{k}}" not in current for k in keywords])

        # TODO: for your finetune model, you can config you prompt here
        if self.lm_config.provider == "finetune":
            current = ""
            traj = trajectory[1::2]
            for rnd, tra in enumerate(traj):
                tar = '** screenshot **' if rnd > 0 else intent
                raw = tra["raw_prediction"]
                current += f"Round {rnd}\n\n<|user|>\n\n** node_info **\n\n{tar}\n\n<|assistant|>\n{raw}\n\n"""
            
            current += f"Round {len(traj)}\n\n<|user|>\n\n{obs}\n\n{'** screenshot **' if len(traj) > 0 else intent}\n"
        
        prompt = self.get_lm_api_input(
            intro, examples, current, page_screenshot_img, images
        )
        return prompt

    def get_lm_api_input(
        self,
        intro: str,
        examples: list[tuple[str, str, str]],
        current: str,
        page_screenshot_img: Image.Image,
        images: list[Image.Image],
    ) -> APIInput:
        """Return the require format for an API"""
        message: list[dict[str, str]] | str | list[str | Image.Image]
        if "openai" in self.lm_config.provider:
            if self.lm_config.mode == "chat":
                message = [
                    {
                        "role": "system",
                        "content": [{"type": "text", "text": intro}],
                    }
                ]
                for (x, y, z) in examples:
                    example_img = Image.open(z)
                    message.append(
                        {
                            "role": "system",
                            "name": "example_user",
                            "content": [
                                {"type": "text", "text": x},
                                {
                                    "type": "text",
                                    "text": "IMAGES: (1) current page screenshot",
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": pil_to_b64(example_img)
                                    },
                                },
                            ],
                        }
                    )
                    message.append(
                        {
                            "role": "system",
                            "name": "example_assistant",
                            "content": [{"type": "text", "text": y}],
                        }
                    )

                # Encode images and page_screenshot_img as base64 strings.
                current_prompt = current
                content = [
                    {
                        "type": "text",
                        "text": "IMAGES: (1) current page screenshot",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": pil_to_b64(page_screenshot_img)},
                    },
                ]
                for image_i, image in enumerate(images):
                    content.extend(
                        [
                            {
                                "type": "text",
                                "text": f"({image_i+2}) input image {image_i+1}",
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": pil_to_b64(image)},
                            },
                        ]
                    )
                content = [{"type": "text", "text": current_prompt}] + content

                message.append({"role": "user", "content": content})
                return message
            else:
                raise ValueError(
                    f"GPT-4V models do not support mode {self.lm_config.mode}"
                )
        elif "google" in self.lm_config.provider:
            if self.lm_config.mode == "completion":
                message = [
                    intro,
                    "Here are a few examples:",
                ]
                for (x, y, z) in examples:
                    example_img = Image.open(z)
                    message.append(f"Observation\n:{x}\n")
                    message.extend(
                        [
                            "IMAGES:",
                            "(1) current page screenshot:",
                            pil_to_vertex(example_img),
                        ]
                    )
                    message.append(f"Action: {y}")
                message.append("Now make prediction given the observation")
                message.append(f"Observation\n:{current}\n")
                message.extend(
                    [
                        "IMAGES:",
                        "(1) current page screenshot:",
                        pil_to_vertex(page_screenshot_img),
                    ]
                )
                for image_i, image in enumerate(images):
                    message.extend(
                        [
                            f"({image_i+2}) input image {image_i+1}",
                            pil_to_vertex(image),
                        ]
                    )
                message.append("Action:")
                return message
            else:
                raise ValueError(
                    f"Gemini models do not support mode {self.lm_config.mode}"
                )
        elif self.lm_config.provider in ["api", "finetune"]:
            message = [
                {
                    "role": "system",
                    "content":  intro,
                }
            ]
            
            # we keep few-shot here, but remove the image corresponding to the current page.
            for (x, y, _) in examples:
                message.append({
                    "role": "user",
                    "content": [
                        { "type": "text", "text": x },
                        { "type": "text", "text": "IMAGES: (1) current page screenshot\n\n** Screenshot **\n" },
                    ],
                })
                message.append({
                    "role": "assistant",
                    "content": y,
                })
                    
            
            # TODO: Encode images and page_screenshot_img as base64 strings, we only keep screenshot of current page.
            current_prompt = current
            content = []
            
            if self.lm_config.provider != "finetune":
                content.append({
                    "type": "text",
                    "text": "IMAGES: (1) current page screenshot",
                })
            
            if "text" not in self.lm_config.model:    
                content.append({
                    "type": "image_url",
                    "image_url": {"url": pil_to_b64(page_screenshot_img)},
                })

            content = [{"type": "text", "text": current_prompt}] + content

            message.append({"role": "user", "content": content})
            return message
            
        else:
            raise NotImplementedError(
                f"Provider {self.lm_config.provider} not implemented"
            )

class WebRLPromptConstructor(PromptConstructor):
    """The agent will direct predict the action"""

    def __init__(
        self,
        instruction_path: str | Path,
        lm_config: lm_config.LMConfig,
        tokenizer: Tokenizer,
    ):
        super().__init__(instruction_path, lm_config, tokenizer)

    def construct(
        self,
        trajectory: Trajectory,
        intent: str,
        meta_data: dict[str, Any] = {},
    ) -> APIInput:
        """Construct prompt given the trajectory"""
        state_info: StateInfo = trajectory[-1]  # type: ignore[assignment]

        obs = state_info["observation"][self.obs_modality]
        max_obs_length = self.lm_config.gen_config["max_obs_length"]
        if max_obs_length:
            if self.lm_config.provider == "google":
                print("NOTE: This is a Gemini model, so we use characters instead of tokens for max_obs_length.")
                obs = obs[:max_obs_length]
            else:
                try:
                    obs = self.tokenizer.decode(self.tokenizer.encode(obs)[:max_obs_length])  # type: ignore[arg-type]
                except:
                    print("NOTE: There is no available tokenizer, so we use characters instead of tokens for max_obs_length.")
                    obs = obs[:max_obs_length]

        turn_num = len(meta_data["action_history"])
        if turn_num == 1:
            previous_action_str = []
        else:
            previous_action_str = meta_data["action_history"][1:]
        
        index = turn_num - 1
        history = ""
        for i in range(index - 1, -1, -1):
            if i == 0:
                history = f"Round {i}\n\n<|eot_id|><|start_header_id|>user<|end_header_id|>\n{intent}\n\n<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n{previous_action_str[i]}\n\n" + history
            else:
                history = f"Round {i}\n\n<|eot_id|><|start_header_id|>user<|end_header_id|>\n** Simplified html **\n\n<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n{previous_action_str[i]}\n\n" + history
        if len(history) + len(obs) > (16384 - 512):
            obs = obs[:(16384 - 512)-len(history)]
        current_turn = f"Round {index}\n\n<|eot_id|><|start_header_id|>user<|end_header_id|>\n{obs}\n\n<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n"
        prompt = f"Task Instruction: {intent}\n\n{history}{current_turn}"

        return prompt

    def extract_action(self, response: str) -> str:
        # The model is expected to output a thought process in <think> tags,
        # followed by the action. We extract the action part.
        
        # Find the content after the </think> tag
        think_end_tag = "</think>"
        if think_end_tag in response:
            response_after_think = response.split(think_end_tag, 1)[-1]
        else:
            response_after_think = response

        # Use regex to find any of the four valid action patterns
        action_match = re.search(r'(do\(.*\)|exit\(.*\)|go_backward\(\)|go_forward\(\))', response_after_think)
        
        if action_match:
            action = action_match.group(0).strip()
            return action
        else:
            # As a fallback, try to find the last line that starts with a valid action
            lines = response_after_think.strip().split('\n')
            for line in reversed(lines):
                cleaned_line = line.strip()
                if cleaned_line.startswith(('do(', 'exit(', 'go_backward(', 'go_forward(')):
                    return cleaned_line
            # If no pattern is found, return the original response to see the error
            return response
    
class WebRLChatPromptConstructor(PromptConstructor):
    """The agent will direct predict the action"""

    def __init__(
        self,
        instruction_path: str | Path,
        lm_config: lm_config.LMConfig,
        tokenizer: Tokenizer,
    ):
        super().__init__(instruction_path, lm_config, tokenizer)

    def construct(
        self,
        trajectory: Trajectory,
        intent: str,
        meta_data: dict[str, Any] = {},
    ) -> APIInput:
        """Construct prompt given the trajectory"""
        state_info: StateInfo = trajectory[-1]  # type: ignore[assignment]

        obs = state_info["observation"][self.obs_modality]
        max_obs_length = self.lm_config.gen_config["max_obs_length"]
        if max_obs_length:
            if self.lm_config.provider == "google":
                print("NOTE: This is a Gemini model, so we use characters instead of tokens for max_obs_length.")
                obs = obs[:max_obs_length]
            else:
                try:
                    obs = self.tokenizer.decode(self.tokenizer.encode(obs)[:max_obs_length])  # type: ignore[arg-type]
                except:
                    print("NOTE: There is no available tokenizer, so we use characters instead of tokens for max_obs_length.")
                    obs = obs[:max_obs_length]

        turn_num = len(meta_data["action_history"])
        if turn_num == 1:
            previous_action_str = []
        else:
            previous_action_str = meta_data["action_history"][1:]
            
        index = turn_num - 1
        conversations = []
        for i in range(index - 1, -1, -1):
            if i == 0:
                content_user = f"Task Instruction: {intent}\n\nRound {i}\n{intent}"
                content_assistant = f"{previous_action_str[i]}"
            else:
                content_user = f"Round {i}\n** Simplified html **"
                content_assistant = f"{previous_action_str[i]}"
            conversation = [{'role': 'user', 'content': content_user}, {'role': 'assistant', 'content': content_assistant}]
            conversations = conversation + conversations
            
        system_turn = [{'role': 'system', 'content': self.instruction['intro']}]
        current_turn = [{'role': 'user', 'content': f'Round {index}\n\n{obs}'}]
        conversations = system_turn + conversations + current_turn

        return conversations

    def extract_action(self, response: str) -> str:
        # The model is expected to output a thought process in <think> tags,
        # followed by the action. We extract the action part.
        
        # Find the content after the </think> tag
        think_end_tag = "</think>"
        if think_end_tag in response:
            response_after_think = response.split(think_end_tag, 1)[-1]
        else:
            response_after_think = response

        # Use regex to find any of the four valid action patterns
        action_match = re.search(r'(do\(.*\)|exit\(.*\)|go_backward\(\)|go_forward\(\))', response_after_think)
        
        if action_match:
            action = action_match.group(0).strip()
            return action
        else:
            # As a fallback, try to find the last line that starts with a valid action
            lines = response_after_think.strip().split('\n')
            for line in reversed(lines):
                cleaned_line = line.strip()
                if cleaned_line.startswith(('do(', 'exit(', 'go_backward(', 'go_forward(')):
                    return cleaned_line
            # If no pattern is found, return the original response to see the error
            return response

class SystemMessagePromptConstructor(PromptConstructor):
    def __init__(
        self,
        instruction_path: str | Path,
        lm_config: lm_config.LMConfig,
        tokenizer: Tokenizer,
    ):
        super().__init__(instruction_path, lm_config, tokenizer)
        self.multimodal = True


class PlannerPromptConstructor(CoTPromptConstructor):
    def __init__(
        self,
        instruction_path: str,
        lm_config: lm_config.LMConfig,
        tokenizer: Tokenizer,
    ):
        super().__init__(instruction_path, lm_config, tokenizer)

    def extract_memory(self, response: str) -> str:
        """Extract memory from planner response."""
        match = re.search(r"\\MEMORY:(.*)", response)
        if match:
            return match.group(1).strip()
        return ""

    def construct(
        self, trajectory: Trajectory, intent: str, meta_data: dict[str, Any]
    ) -> APIInput:
        """Construct prompt with memory support."""
        intro = self.instruction["intro"]
        examples = self.instruction["examples"]
        template = self.instruction["template"]
        keywords = self.instruction["meta_data"]["keywords"]
        state_info: StateInfo = trajectory[-1]
        
        obs = state_info["observation"][self.obs_modality]
        max_obs_length = self.lm_config.gen_config["max_obs_length"]
        if max_obs_length:
            if self.lm_config.provider == "google":
                obs = obs[:max_obs_length]
            else:
                obs = self.tokenizer.decode(
                    self.tokenizer.encode(obs)[:max_obs_length]
                )

        # Get previous action description
        action_history = meta_data.get("action_history", [])
        if action_history:
            previous_action = action_history[-1]
        else:
            previous_action = "None"

        # Get accumulated memory
        accumulated_memory = meta_data.get("planner_memory", "")
        if not accumulated_memory:
            accumulated_memory = "No previous memory available."

        # Format the template with all required variables
        current = template.format(
            objective=intent,
            observation=obs,
            previous_action=previous_action,
            memory=accumulated_memory,
        )

        # Ensure all keywords are replaced
        assert all([f"{{k}}" not in current for k in keywords])

        # Use parent's method to properly format for API
        prompt = self.get_lm_api_input(intro, examples, current)
        return prompt

    def extract_action(self, response: str) -> str:
        # Stop case
        match = re.search(r"\\stop\((.*)\)", response)
        if match:
            return f"stop[{match.group(1)}]"
        
        # Instruction case
        match = re.search(r"\\INSTRUCTION:(.*)", response)
        if match:
            return match.group(1).strip()

        raise ActionParsingError(f"Cannot parse instruction or stop from planner response: {response}")


class ExecutorPromptConstructor(CoTPromptConstructor):
    def __init__(
        self,
        instruction_path: str,
        lm_config: lm_config.LMConfig,
        tokenizer: Tokenizer,
    ):
        super().__init__(instruction_path, lm_config, tokenizer)

    def construct(
        self, trajectory: Trajectory, intent: str, meta_data: dict[str, Any]
    ) -> str:
        # The 'intent' for the executor is the instruction from the planner.
        # The original user query is in meta_data.
        user_query = meta_data.get("intent", "")
        instruction_from_planner = intent

        state_info: StateInfo = trajectory[-1]
        # Per user's prompt, this should be HTML.
        # webrl observation is already in a simplified HTML format.
        obs = state_info["observation"]["text"]
        max_obs_length = self.lm_config.gen_config["max_obs_length"]
        if max_obs_length:
            if self.lm_config.provider == "google":
                obs = obs[:max_obs_length]
            else:
                obs = self.tokenizer.decode(
                    self.tokenizer.encode(obs)[:max_obs_length]
                )

        prompt = (
            f'You are a helpful WebAgent AI to do following task: "{user_query}". '
            f"You'll need to approach this through each step-by-step by first performing the following subtask based on the current HTML page provided.\n"
            f"Current subtask: {instruction_from_planner}\n"
            f"Reason through this subtask and provide the ONE action only to achieve the task using the list below. Put your answer of action with the format provided in your response:\n"
            f"- type(bid=<element ID>, value=<typed content>, press_enter=<True or False>)\n"
            f"- click(bid=<element ID>)\n"
            f"- select_option(bid=<element ID>, options=<chosen option>)\n"
            f"- go_back()\n"
            f"Example output:\n"
            f"type(bid=95, value=Hong Kong, press_enter=True)\n"
            f"HTML at the current page:\n"
            f"{obs}"
        )
        return prompt

    def _extract_action(self, response: str) -> str:
        # The model is supposed to return a single action line, but it sometimes adds extra text.
        # We will try to extract the first valid-looking action command.
        
        # Find the start of a potential action call
        match = re.search(r"(click|type|select_option|go_back)\s*\(", response)
        if match:
            start_index = match.start()
            open_paren_index = response.find('(', start_index)
            
            # Find the matching closing parenthesis
            open_paren_count = 1
            current_index = open_paren_index + 1
            
            while current_index < len(response) and open_paren_count > 0:
                if response[current_index] == '(':
                    open_paren_count += 1
                elif response[current_index] == ')':
                    open_paren_count -= 1
                current_index += 1
                
            if open_paren_count == 0:
                # We found the matching parenthesis
                end_index = current_index
                action_str = response[start_index:end_index]
                return action_str.strip()
        
        # If no standard action found, check for scroll action (keyword-based detection)
        if "scroll" in response.lower():
            return "scroll_down()"
        
        # If we couldn't find any match, fallback to the original behavior
        return response.strip()


__all__ = [
    "PromptConstructor",
    "DirectPromptConstructor",
    "CoTPromptConstructor",
    "MultimodalCoTPromptConstructor",
    "WebRLPromptConstructor",
    "WebRLChatPromptConstructor",
    "SystemMessagePromptConstructor",
    "PlannerPromptConstructor",
    "ExecutorPromptConstructor",
]