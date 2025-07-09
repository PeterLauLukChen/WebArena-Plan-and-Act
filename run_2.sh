#!/bin/bash

# Array of indices to skip (these exist in test_webarena_lite)
SKIP_INDICES=(4 7 15 20 23 27 33 37 43 44 48 56 58 65 69 71 75 77 82 88 93 95 96 97 98 103 109 115 117 118 123 125 127 131 135 139 144 149 155 156 157 162 167 169 173 182 190 196 202 205 211 215 220 221 225 227 235 236 240 247 250 254 258 259 268 270 276 283 285 287 288 296 300 311 313 318 321 324 333 335 348 349 354 357 361 367 368 369 374 376 381 382 383 384 386 387 392 401 404 415 419 423 426 431 440 448 454 458 464 466 470 476 485 488 491 497 505 506 509 514 516 521 524 528 534 538 548 566 567 574 577 582 599 601 605 612 619 626 631 641 645 652 657 668 673 678 682 686 693 704 710 714 720 729 733 741 745 748 760 762 768 791 798 809 811)
RANGE=("689-692" "705-708" "709-713" "715-718" "719-724" "726-729" "731-735" "743-746" "749-751" "769-770" "794-798" "808-809" "810-811")
# --- Task and Result Configuration ---
# START_IDX and END_IDX are now handled by RANGE array
export RESULT_DIR="results/Train_traj_claude4_new"
export DATASET="webarena" # or "visualwebarena"

# --- Path Configuration ---
TEST_CONFIG_BASE_DIR="config_files/wa/test_webarena"

# --- Model Endpoint Configuration ---
# Set provider to "openai" for any OpenAI-compatible API (like VLLM or OpenRouter)
PLANNER_PROVIDER="openai"
EXECUTOR_PROVIDER="openai"

# OpenRouter endpoint for planner (OpenAI-compatible)
PLANNER_ENDPOINT="https://openrouter.ai/api/v1"
# Local VLLM endpoint for executor
EXECUTOR_ENDPOINT="http://localhost:5003/v1"

# The 'model_name' MUST match the model path used to launch your VLLM server OR the OpenRouter model name.
# For OpenRouter: use the model identifier from their API
PLANNER_MODEL_NAME="anthropic/claude-sonnet-4"
EXECUTOR_MODEL_NAME="/home/ubuntu/saved_models/Qwen2.5-3B-Instruct-actionRL"

# --- OpenRouter API Configuration ---
# Set your OpenRouter API key as environment variable
export OPENAI_API_KEY="${OPENROUTER_API_KEY:-your_openrouter_api_key_here}"

# --- Generation Configuration ---
# Use chat mode for Claude models (will be auto-detected for OpenRouter Claude)
MODE="completion"
# Note: Claude models typically use different stop tokens, but we'll use the OpenRouter compatible format
STOP_TOKEN="<|im_end|>"
MAX_TOKENS=1024
CONTEXT_LENGTH=200000

# --- Environment and Observation Configuration ---
MAX_OBS_LENGTH=0
VIEWPORT_WIDTH=1280
VIEWPORT_HEIGHT=1440
OBSERVATION_TYPE="webrl"
ACTION_SET_TAG="webrl_id"

# --- Run the script for each range ---
for range in "${RANGE[@]}"; do
  # Parse the range (e.g., "141-145" -> START_IDX=141, END_IDX=146)
  START_IDX=$(echo $range | cut -d'-' -f1)
  END_IDX=$(($(echo $range | cut -d'-' -f2) + 1))  # +1 because end_idx is exclusive
  
  echo "Processing range $range (indices $START_IDX to $((END_IDX-1)))"
  
  for ((i=START_IDX; i<END_IDX; i++)); do
    # Skip indices that exist in test_webarena_lite
    if [[ " ${SKIP_INDICES[@]} " =~ " ${i} " ]]; then
      echo "Skipping index $i (exists in test_webarena_lite)"
      continue
    fi
    
    echo "Processing index $i"
    python run.py \
      --use_plan_act \
      --test_start_idx $i \
      --test_end_idx $((i+1)) \
      --result_dir $RESULT_DIR \
      --test_config_base_dir $TEST_CONFIG_BASE_DIR \
      --planner_provider "$PLANNER_PROVIDER" \
      --planner_endpoint "$PLANNER_ENDPOINT" \
      --planner_model_name "$PLANNER_MODEL_NAME" \
      --executor_provider "$EXECUTOR_PROVIDER" \
      --executor_endpoint "$EXECUTOR_ENDPOINT" \
      --executor_model_name "$EXECUTOR_MODEL_NAME" \
      --mode "$MODE" \
      --stop_token "$STOP_TOKEN" \
      --max_tokens $MAX_TOKENS \
      --context_length $CONTEXT_LENGTH \
      --max_obs_length $MAX_OBS_LENGTH \
      --viewport_width $VIEWPORT_WIDTH \
      --viewport_height $VIEWPORT_HEIGHT \
      --observation_type "$OBSERVATION_TYPE" \
      --action_set_tag "$ACTION_SET_TAG" 
  done
done 