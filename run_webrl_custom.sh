#!/bin/bash
python run.py \
  --instruction_path agent/prompts/jsons/p_webrl_chat.json \
  --test_start_idx 10 \
  --test_end_idx 30 \
  --result_dir results/Qwen3-32B \
  --test_config_base_dir config_files/wa/test_webarena_lite \
  --provider openai \
  --mode completion \
  --model "/home/ubuntu/saved_models/Qwen3-32B" \
  --planner_ip "http://localhost:5003/v1" \
  --stop_token "<|im_end|>" \
  --max_obs_length 0 \
  --max_tokens 2048 \
  --viewport_width 1280 \
  --viewport_height 720 \
  --action_set_tag webrl_id  --observation_type webrl 