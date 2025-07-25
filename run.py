"""Script to run end-to-end evaluation on the benchmark.

Modified from https://github.com/web-arena-x/webarena/blob/main/run.py.
"""
import argparse
import glob
import json
import logging
import os
import random
import subprocess
import tempfile
import time
from pathlib import Path
from typing import List, Any
import cv2
import shutil
import numpy as np

import openai
import requests
import torch
from PIL import Image, ImageDraw, ImageFont

from agent import (
    PromptAgent,
    construct_agent,
)
from agent.prompts import *
from llms import lm_config
from llms.tokenizers import Tokenizer
from browser_env import (
    Action,
    ActionTypes,
    ScriptBrowserEnv,
    StateInfo,
    Trajectory,
    create_stop_action,
)
from browser_env.actions import is_equivalent
from browser_env.auto_login import get_site_comb_from_filepath
from browser_env.helper_functions import (
    RenderHelper,
    get_action_description,
)
from evaluation_harness import evaluator_router, image_utils

DATASET = os.environ["DATASET"]

LOG_FOLDER = "log_files"
Path(LOG_FOLDER).mkdir(parents=True, exist_ok=True)
LOG_FILE_NAME = f"{LOG_FOLDER}/log_{time.strftime('%Y%m%d%H%M%S', time.localtime())}_{random.randint(0, 10000)}.log"

logger = logging.getLogger("logger")
logger.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
logger.addHandler(console_handler)

file_handler = logging.FileHandler(LOG_FILE_NAME)
file_handler.setLevel(logging.DEBUG)
logger.addHandler(file_handler)

# Set the log format
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)

class DialogueLogEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.ndarray, np.generic)):
            return obj.tolist()
        if callable(obj):
            return obj.__name__
        try:
            return json.JSONEncoder.default(self, obj)
        except TypeError:
            return str(obj)

def text_wrap(text, font, max_width):
    lines = []
    paragraphs = text.split('\n')  # 按照 \n 分割文本为段落
    for paragraph in paragraphs:
        words = paragraph.split(' ')
        line = ''
        for word in words:
            # 临时行
            test_line = f"{line} {word}".strip()
            # 获取临时行的宽度
            test_line_bbox = font.getbbox(test_line)
            test_line_width = test_line_bbox[2] - test_line_bbox[0]
            if test_line_width <= max_width:
                # 如果临时行的宽度不超过图片宽度，继续添加单词
                line = test_line
            else:
                # 如果超过了最大宽度，保存当前行，开始新的一行
                lines.append(line)
                line = word
        # 添加每段的最后一行
        if line:
            lines.append(line)
        # 每个段落后添加一个空行，以保留段落的换行
        lines.append('')
    # 移除最后一个空行（不需要额外的空行）
    if lines[-1] == '':
        lines.pop()
    return lines

def config() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run end-to-end evaluation on the benchmark"
    )
    parser.add_argument(
        "--render", action="store_true", help="Render the browser"
    )

    parser.add_argument(
        "--slow_mo",
        type=int,
        default=0,
        help="Slow down the browser by the specified amount",
    )
    parser.add_argument(
        "--action_set_tag", default="id_accessibility_tree", help="Action type"
    )
    parser.add_argument(
        "--observation_type",
        choices=[
            "accessibility_tree",
            "accessibility_tree_with_captioner",
            "html",
            "image",
            "image_som",
            "webrl",
        ],
        default="accessibility_tree",
        help="Observation type",
    )
    parser.add_argument(
        "--current_viewport_only",
        action="store_true",
        help="Only use the current viewport for the observation",
    )
    parser.add_argument("--viewport_width", type=int, default=1280)
    parser.add_argument("--viewport_height", type=int, default=2048)
    parser.add_argument("--save_trace_enabled", action="store_true")
    parser.add_argument("--sleep_after_execution", type=float, default=0.0)

    parser.add_argument("--max_steps", type=int, default=30)

    # agent config
    parser.add_argument("--agent_type", type=str, default="prompt")
    parser.add_argument(
        "--instruction_path",
        type=str,
        default="agent/prompts/jsons/p_cot_id_actree_2s_no_na.json",
    )
    parser.add_argument("--use_plan_act", action="store_true", help="Use planner-executor agent")
    parser.add_argument(
        "--planner_instruction_path",
        type=str,
        default="agent/prompts/jsons/plan-act/planner.json",
    )
    parser.add_argument(
        "--executor_instruction_path",
        type=str,
        default="agent/prompts/jsons/plan-act/executor.json",
    )
    parser.add_argument(
        "--parsing_failure_th",
        help="When consecutive parsing failures exceed this threshold, the agent will terminate early.",
        type=int,
        default=3,
    )
    parser.add_argument(
        "--repeating_action_failure_th",
        help="When consecutive repeated actions exceed this threshold, the agent will terminate early.",
        type=int,
        default=5,
    )

    parser.add_argument("--test_config_base_dir", type=str)

    parser.add_argument(
        "--eval_captioning_model_device",
        type=str,
        default="cpu",
        choices=["cpu", "cuda"],
        help="Device to run eval captioning model on. By default, runs it on CPU.",
    )
    parser.add_argument(
        "--eval_captioning_model",
        type=str,
        default="Salesforce/blip2-flan-t5-xl",
        choices=["Salesforce/blip2-flan-t5-xl"],
        help="Captioning backbone for VQA-type evals.",
    )
    parser.add_argument(
        "--captioning_model",
        type=str,
        default="Salesforce/blip2-flan-t5-xl",
        choices=["Salesforce/blip2-flan-t5-xl", "llava-hf/llava-1.5-7b-hf"],
        help="Captioning backbone for accessibility tree alt text.",
    )

    # lm config
    parser.add_argument("--provider", type=str, default="openai")
    parser.add_argument("--model", type=str, default="gpt-3.5-turbo")
    parser.add_argument("--mode", type=str, default="chat")
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--top_p", type=float, default=0.9)
    parser.add_argument("--context_length", type=int, default=0)
    parser.add_argument("--max_tokens", type=int, default=384)
    parser.add_argument("--stop_token", type=str, default=None)
    parser.add_argument(
        "--max_retry",
        type=int,
        help="max retry times to perform generations when parsing fails",
        default=1,
    )
    parser.add_argument(
        "--max_obs_length",
        type=int,
        help="when not zero, will truncate the observation to this length before feeding to the model",
        default=3840,
    )

    # planner/executor model configs
    parser.add_argument("--planner_provider", type=str, default="openai")
    parser.add_argument(
        "--planner_endpoint",
        type=str,
        default="http://127.0.0.1:5000/v1",
        help="The endpoint for the planner model.",
    )
    parser.add_argument(
        "--planner_model_name",
        type=str,
        default="gpt-4-turbo-preview",
        help="The name of the planner model.",
    )
    parser.add_argument("--executor_provider", type=str, default="openai")
    parser.add_argument(
        "--executor_endpoint",
        type=str,
        default="http://127.0.0.1:5000/v1",
        help="The endpoint for the executor model.",
    )
    parser.add_argument(
        "--executor_model_name",
        type=str,
        default="gpt-4-turbo-preview",
        help="The name of the executor model.",
    )

    # example config
    parser.add_argument("--test_start_idx", type=int, default=0)
    parser.add_argument("--test_end_idx", type=int, default=910)

    # logging related
    parser.add_argument("--result_dir", type=str, default="")
    
    # if use self-deployed model
    parser.add_argument("--planner_ip", type=str, default=None)
    args = parser.parse_args()

    # check the whether the action space is compatible with the observation space
    if (
        args.action_set_tag == "id_accessibility_tree"
        and args.observation_type
        not in [
            "accessibility_tree",
            "accessibility_tree_with_captioner",
            "image_som",
        ]
    ):
        raise ValueError(
            f"Action type {args.action_set_tag} is incompatible with the observation type {args.observation_type}"
        )

    return args


def early_stop(
    trajectory: Trajectory, max_steps: int, thresholds: dict[str, int], actions=None
) -> tuple[bool, str]:
    """Check whether need to stop early"""

    # reach the max step
    num_steps = (len(trajectory) - 1) / 2
    if num_steps >= max_steps:
        return True, f"Reach max steps {max_steps}"

    last_k_actions: list[Action]
    action_seq: list[Action]

    # Case: parsing failure for k times
    k = thresholds["parsing_failure"]
    last_k_actions = trajectory[1::2][-k:]  # type: ignore[assignment]
    if len(last_k_actions) >= k:
        if all(
            [
                action["action_type"] == ActionTypes.NONE
                for action in last_k_actions
            ]
        ):
            return True, f"Failed to parse actions for {k} times"

    # Case: same action for k times
    k = thresholds["repeating_action"]
    last_k_actions = trajectory[1::2][-k:]  # type: ignore[assignment]
    action_seq = trajectory[1::2]  # type: ignore[assignment]

    if len(action_seq) == 0:
        return False, ""

    if actions is None:
        last_action: Action = action_seq[-1]
        if last_action["action_type"] != ActionTypes.TYPE:
            if len(last_k_actions) >= k:
                if all(
                    [
                        is_equivalent(action, last_action)
                        for action in last_k_actions
                    ]
                ):
                    return True, f"Same action for {k} times"
        else:
            # check the action sequence
            if (
                sum([is_equivalent(action, last_action) for action in action_seq])
                >= k
            ):
                return True, f"Same typing action for {k} times"
        return False, ""

    else:
        last_k_actions = actions[-k:]
        last_action = actions[-1]
        if len(last_k_actions) >= k:
            if all(
                [
                    action == last_action
                    for action in last_k_actions
                ]
            ):
                return True, f"Same action for {k} times"
        return False, ""

def update_action_history(path: str, task_id: int, actions: list, score: float=-0.1):    
    class NumpyEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            return super().default(obj)
    obj = {
        "task_id": task_id,
        "score": score,
        "actions": actions
    }
    json.dump(obj, open(path, "w"), indent=4, cls=NumpyEncoder)


def get_agent(args: argparse.Namespace, agent_type: str) -> PromptAgent:
    """Helper function to get an agent instance based on agent_type."""
    if agent_type == "planner":
        provider = args.planner_provider
        endpoint = args.planner_endpoint
        model_name = args.planner_model_name
        prompt_file = "agent/prompts/jsons/plan-act/planner.json"
        prompt_constructor_class = PlannerPromptConstructor
    elif agent_type == "executor":
        provider = args.executor_provider
        endpoint = args.executor_endpoint
        model_name = args.executor_model_name
        prompt_file = "agent/prompts/jsons/plan-act/executor.json"
        prompt_constructor_class = ExecutorPromptConstructor
    else:
        raise ValueError(f"Unknown agent type: {agent_type}")

    agent_lm_config = lm_config.LMConfig(
        provider=provider,
        model=model_name,
        mode=args.mode,
        base_url=endpoint,
        gen_config={
            "temperature": 0,
            "top_p": 1.0,
            "context_length": args.context_length,
            "max_obs_length": args.max_obs_length,
            "max_tokens": args.max_tokens,
            "stop_token": args.stop_token,
            "max_retry": args.max_retry,
        },
    )

    tokenizer = Tokenizer(
        model_name=agent_lm_config.model,
        provider=agent_lm_config.provider,
    )

    prompt_constructor = prompt_constructor_class(
        instruction_path=prompt_file,
        lm_config=agent_lm_config,
        tokenizer=tokenizer,
    )

    agent = PromptAgent(
        action_set_tag=args.action_set_tag,
        lm_config=agent_lm_config,
        prompt_constructor=prompt_constructor,
    )

    return agent


def log_dialogue(result_dir: str, task_id: str, turn_id: int, agent: str, dialogue: dict) -> None:
    """Logs the dialogue between planner and executor."""
    dialogue_dir = Path(result_dir) / "dialogues"
    dialogue_dir.mkdir(exist_ok=True)
    log_file = dialogue_dir / f"{task_id}.jsonl"
    entry = {"turn_id": turn_id, "agent": agent, **dialogue}
    with log_file.open("a") as f:
        f.write(json.dumps(entry, cls=DialogueLogEncoder) + "\n")


def test(
    args: argparse.Namespace,
    config_file_list: list[str]
) -> None:
    scores = []
    max_steps = args.max_steps

    early_stop_thresholds = {
        "parsing_failure": args.parsing_failure_th,
        "repeating_action": args.repeating_action_failure_th,
    }

    if args.observation_type in [
        "accessibility_tree_with_captioner",
        # "image_som",
    ]:
        device = torch.device("cuda") if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        caption_image_fn = image_utils.get_captioning_fn(
            device, dtype, args.captioning_model
        )
    else:
        caption_image_fn = None

    # Load a (possibly different) captioning model for running VQA evals.
    if DATASET == 'visualwebarena':
        if (
            caption_image_fn
            and args.eval_captioning_model == args.captioning_model
        ):
            eval_caption_image_fn = caption_image_fn
        else:
            eval_caption_image_fn = image_utils.get_captioning_fn(
                args.eval_captioning_model_device,
                torch.float16
                if (
                    torch.cuda.is_available()
                    and args.eval_captioning_model_device == "cuda"
                )
                else torch.float32,
                args.eval_captioning_model,
            )
    else:
        caption_image_fn = None
        eval_caption_image_fn = None

    if args.use_plan_act:
        planner_agent = get_agent(args, "planner")
        executor_agent = get_agent(args, "executor")
    else:
        # agent = get_agent(args, "prompt")
        agent = construct_agent(args)
        planner_agent = None
        executor_agent = None

    browser_env = None  # Initialize to None to avoid UnboundLocalError
    for config_file in config_file_list:
        try:
            render_helper = RenderHelper(
                config_file, args.result_dir, args.action_set_tag
            )

            # Load task.
            with open(config_file) as f:
                _c = json.load(f)
                intent = _c["intent"]
                task_id = _c["task_id"]
                image_paths = _c.get("image", None)
                images = []

                # automatically login
                if _c["storage_state"]:
                    cookie_file_name = os.path.basename(_c["storage_state"])
                    comb = get_site_comb_from_filepath(cookie_file_name)
                    temp_dir = tempfile.mkdtemp()
                    # subprocess to renew the cookie
                    subprocess.run(
                        [
                            "python",
                            "browser_env/auto_login.py",
                            "--auth_folder",
                            temp_dir,
                            "--site_list",
                            *comb,
                        ]
                    )
                    _c["storage_state"] = f"{temp_dir}/{cookie_file_name}"
                    assert os.path.exists(_c["storage_state"])
                    # update the config file
                    config_file = f"{temp_dir}/{os.path.basename(config_file)}"
                    with open(config_file, "w") as f:
                        json.dump(_c, f)

                # Load input images for the task, if any.
                if image_paths is not None:
                    if isinstance(image_paths, str):
                        image_paths = [image_paths]
                    for image_path in image_paths:
                        # Load image either from the web or from a local path.
                        if image_path.startswith("http"):
                            input_image = Image.open(requests.get(image_path, stream=True).raw)
                        else:
                            input_image = Image.open(image_path)

                        images.append(input_image)

            logger.info(f"[Config file]: {config_file}")
            logger.info(f"[Intent]: {intent}")

            browser_env = ScriptBrowserEnv(
                headless=not args.render,
                slow_mo=args.slow_mo,
                observation_type=args.observation_type,
                current_viewport_only=args.current_viewport_only,
                viewport_size={
                    "width": args.viewport_width,
                    "height": args.viewport_height,
                },
                save_trace_enabled=args.save_trace_enabled,
                sleep_after_execution=args.sleep_after_execution,
                captioning_fn=caption_image_fn,
            )

            trajectory: Trajectory = []
            obs, info = browser_env.reset(options={"config_file": config_file})

            # The task is to navigate to a website and do something.
            if args.use_plan_act:
                meta_data = {
                    "action_history": [],
                    "start_url": browser_env.page.url,
                    "intent": intent,
                    "planner_memory": "",  # Initialize memory for planner
                }
            else:
                prompt_constructor = (
                    agent.prompt_constructor
                    if isinstance(agent, PromptAgent)
                    else None
                )
                action_description = get_action_description(
                    None,
                    info["state_info"]["info"]["observation_metadata"],
                    args.action_set_tag,
                    prompt_constructor,
                )
                meta_data = {
                    "action_history": f"Tab {browser_env.page.tab_id}: {action_description}"
                }

            state_info: StateInfo = info["state_info"]
            trajectory.append(state_info)
            
            os.makedirs(os.path.join(args.result_dir, 'screehshots'), exist_ok=True)
            if os.path.exists(os.path.join(args.result_dir, 'screehshots', f"{task_id}")):
                shutil.rmtree(os.path.join(args.result_dir, 'screehshots', f"{task_id}"))
            os.makedirs(os.path.join(args.result_dir, 'screehshots', f"{task_id}"))
            
            for i in range(args.max_steps):
                if args.use_plan_act:
                    # Planner generates an instruction
                    instruction = planner_agent.get_instruction(
                        trajectory, intent, meta_data
                    )
                    
                    # Extract memory from planner response for next turn
                    if hasattr(planner_agent.prompt_constructor, 'extract_memory'):
                        new_memory = planner_agent.prompt_constructor.extract_memory(
                            planner_agent.last_raw_response
                        )
                        if new_memory:
                            # Append new memory to existing memory
                            if meta_data["planner_memory"]:
                                meta_data["planner_memory"] += f"\n{new_memory}"
                            else:
                                meta_data["planner_memory"] = new_memory
                    
                    log_dialogue(
                        args.result_dir,
                        str(task_id),
                        i,
                        "planner",
                        {
                            "raw_response": planner_agent.last_raw_response,
                            "parsed_instruction": instruction,
                            "extracted_memory": meta_data["planner_memory"],
                        },
                    )

                    # Check for stop condition from planner
                    if "stop" in instruction.lower():
                        # Extract answer from "stop[answer]" format
                        if instruction.startswith("stop[") and instruction.endswith("]"):
                            answer = instruction[5:-1]  # Remove "stop[" and "]"
                        else:
                            answer = instruction  # Fallback for unexpected format
                        action = create_stop_action(answer)
                    else:
                        # Executor generates an action based on the planner's instruction
                        action = executor_agent.next_action(
                            trajectory, instruction, meta_data
                        )
                        log_dialogue(
                            args.result_dir,
                            str(task_id),
                            i,
                            "executor",
                            {
                                "raw_response": executor_agent.last_raw_response,
                                "parsed_action": action,
                            },
                        )
                else:
                    action = agent.next_action(
                        trajectory, intent, meta_data, images
                    )
                
                trajectory.append(action)

                if action["action_type"] != ActionTypes.STOP:
                    obs, _, terminated, _, info = browser_env.step(action)
                    state_info = info["state_info"]
                    trajectory.append(state_info)

                if render_helper:
                    render_helper.render(
                        action, state_info, meta_data, args.render_screenshot
                    )
                    
                    current_screenshot = os.path.join(args.result_dir, 'screehshots', f"{task_id}", f"{i}.png")
                    browser_env.page.screenshot(path=current_screenshot)
                    element_id = action.get("element_id", "")
                    if element_id:
                        element = browser_env.page.query_selector(f"[data-label-id='{element_id}']")
                        if element:
                            bbox = element.bounding_box()
                            if bbox:
                                bbox = [int(bbox['x']), int(bbox['y']), int(bbox['width']),int(bbox['height'])]
                                image = cv2.imread(current_screenshot)
                                cv2.rectangle(image, (bbox[0], bbox[1]), (bbox[0] + bbox[2], bbox[1] + bbox[3]), (0, 255, 0), 2)
                                cv2.circle(image, (int(bbox[0] + bbox[2] / 2), int(bbox[1] + bbox[3] / 2)), 3, (0, 255, 0), -1)
                                cv2.imwrite(current_screenshot, image)
                
                prompt_constructor = None
                if args.use_plan_act:
                    prompt_constructor = executor_agent.prompt_constructor
                elif isinstance(agent, PromptAgent):
                    prompt_constructor = agent.prompt_constructor

                action_description = get_action_description(
                    action,
                    state_info["info"]["observation_metadata"],
                    args.action_set_tag,
                    prompt_constructor,
                )
                if args.use_plan_act:
                    meta_data["action_history"].append(action_description)
                else:
                    meta_data["action_history"] += f"\nTab {info['tab_id']}: {action_description}"

                # Early stop
                if action["action_type"] == ActionTypes.STOP or ("terminated" in locals() and terminated):
                    if action["action_type"] != ActionTypes.STOP:
                        # add a placeholder STOP so trajectory length remains 2*steps+1
                        trajectory.append(create_stop_action(""))
                    break
            
            # NOTE: eval_caption_image_fn is used for running eval_vqa functions.
            evaluator = evaluator_router(
                config_file, captioning_fn=eval_caption_image_fn
            )
            score = evaluator(
                trajectory=trajectory,
                config_file=config_file,
                page=browser_env.page
            )

            out_path = os.path.join(args.result_dir, "actions", f"{task_id}.json")
            actions = [step for step in trajectory if isinstance(step, dict) and "action_type" in step]
            update_action_history(out_path, task_id, actions=actions, score=score)
            scores.append(score)

            if score == 1:
                logger.info(f"[Result] (PASS) {config_file}")
                print(f"[Result] (PASS) {config_file}")
            else:
                logger.info(f"[Result] (FAIL) {config_file}")
                print(f"[Result] (FAIL) {config_file}")

            if args.save_trace_enabled:
                browser_env.save_trace(
                    Path(args.result_dir) / "traces" / f"{task_id}.zip"
                )
        except openai.OpenAIError as e:
            logger.info(f"[OpenAI Error] {repr(e)}")
        except Exception as e:
            logger.info(f"[Unhandled Error] {repr(e)}]")
            import traceback

            # write to error file
            with open(Path(args.result_dir) / "error.txt", "a") as f:
                f.write(f"[Config file]: {config_file}\n")
                f.write(f"[Unhandled Error] {repr(e)}\n")
                f.write(traceback.format_exc())  # write stack trace to file

        render_helper.close()

    if browser_env is not None:
        browser_env.close()
    if len(scores):
        logger.info(f"Average score: {sum(scores) / len(scores)}")


def prepare(args: argparse.Namespace) -> None:
    # convert prompt python files to json
    from agent.prompts import to_json

    to_json.run()

    # prepare result dir
    result_dir = args.result_dir
    if not result_dir:
        result_dir = (
            f"cache/results_{time.strftime('%Y%m%d%H%M%S', time.localtime())}"
        )
    if not Path(result_dir).exists():
        Path(result_dir).mkdir(parents=True, exist_ok=True)
        args.result_dir = result_dir
        logger.info(f"Create result dir: {result_dir}")

    if not (Path(result_dir) / "traces").exists():
        (Path(result_dir) / "traces").mkdir(parents=True)

    os.makedirs(os.path.join(result_dir, "actions"), exist_ok=True)

    # log the log file
    with open(os.path.join(result_dir, "log_files.txt"), "a+") as f:
        f.write(f"{LOG_FILE_NAME}\n")


def get_unfinished(config_files: list[str], result_dir: str) -> list[str]:
    result_files = glob.glob(f"{result_dir}/*.html")
    task_ids = [
        os.path.basename(f).split(".")[0].split("_")[1] for f in result_files
    ]
    unfinished_configs = []
    for config_file in config_files:
        task_id = os.path.basename(config_file).split(".")[0]
        try:
            with open(f"{result_dir}/actions/{task_id}.json", "r") as f:
                jd = json.load(f)
        except:
            jd = {}
        if task_id not in task_ids or jd.get('score', -1) < 0:
            unfinished_configs.append(config_file)
    return unfinished_configs


def dump_config(args: argparse.Namespace) -> None:
    config_file = Path(args.result_dir) / "config.json"
    if not config_file.exists():
        with open(config_file, "w") as f:
            json.dump(vars(args), f, indent=4)
            logger.info(f"Dump config to {config_file}")


if __name__ == "__main__":
    os.environ["TOKENIZERS_PARALLELISM"] = "false"

    args = config()
    args.sleep_after_execution = 3.0
    prepare(args)

    test_config_base_dir = args.test_config_base_dir

    test_file_list = []
    st_idx = args.test_start_idx
    ed_idx = args.test_end_idx
    for i in range(st_idx, ed_idx):
        test_file_list.append(os.path.join(test_config_base_dir, f"{i}.json"))
    test_file_list = get_unfinished(test_file_list, args.result_dir)
    print(f"Total {len(test_file_list)} tasks left")
    args.render = False
    args.render_screenshot = True
    args.save_trace_enabled = True

    args.current_viewport_only = True
    dump_config(args)

    test(args, test_file_list)
