# OpenRouter API Integration for WebArena Lite Planner Agent

This document describes how to use OpenRouter API (specifically Claude Sonnet 4) for the planner agent while keeping the executor agent running on local VLLM.

## Architecture Overview

- **Planner Agent**: Claude Sonnet 4 via OpenRouter API
- **Executor Agent**: Local VLLM model (`Qwen2.5-3B-Instruct-actionRL`)

## Setup Instructions

### 1. Get OpenRouter API Key

1. Visit [OpenRouter](https://openrouter.ai/keys)
2. Create an account and generate an API key
3. Note: Claude Sonnet 4 costs $3/M input tokens and $15/M output tokens

### 2. Configure API Key

Run the setup script:
```bash
./setup_openrouter.sh your_openrouter_api_key_here
```

Or set the environment variable manually:
```bash
export OPENROUTER_API_KEY="your_openrouter_api_key_here"
```

### 3. Start Local VLLM for Executor

Start the executor model (unchanged from original setup):
```bash
# Start executor model on port 5002
vllm serve /home/ubuntu/saved_models/Qwen2.5-3B-Instruct-actionRL \
    --host 0.0.0.0 \
    --port 5002 \
    --api-key dummy
```

### 4. Run the Planner Agent

Execute the modified script:
```bash
./run_plan_act.sh
```

## Configuration Details

### Modified Files

1. **`run_plan_act.sh`**: Updated planner configuration
   - `PLANNER_ENDPOINT="https://openrouter.ai/api/v1"`
   - `PLANNER_MODEL_NAME="anthropic/claude-sonnet-4"`

2. **`llms/providers/openai_utils.py`**: Added OpenRouter-specific headers and Claude model support

3. **`llms/utils.py`**: Auto-detection of Claude models for chat mode

### Key Features

- **OpenRouter Headers**: Proper tracking headers for API calls
- **Auto Chat Mode**: Claude models automatically use chat completions
- **Fallback Support**: Maintains compatibility with existing VLLM setup
- **Error Handling**: Comprehensive error handling and retry logic

## Pricing Information

Based on [OpenRouter pricing](https://openrouter.ai/anthropic/claude-sonnet-4/api):
- **Input tokens**: $3.00 per million tokens
- **Output tokens**: $15.00 per million tokens  
- **Context length**: 200,000 tokens
- **Image processing**: $4.80 per 1K images

## Troubleshooting

### Common Issues

1. **API Key Not Found**
   ```bash
   export OPENROUTER_API_KEY="your_key_here"
   ```

2. **Connection Issues**
   - Check your internet connection
   - Verify API key is valid
   - Run `./setup_openrouter.sh your_key` to test

3. **Model Access Issues**
   - Ensure you have sufficient credits on OpenRouter
   - Check if Claude Sonnet 4 is available in your region

### Debug Mode

Add debug logging to see API calls:
```bash
export OPENAI_LOG=debug
./run_plan_act.sh
```

## Performance Comparison

| Aspect | Local VLLM | OpenRouter Claude-4 |
|--------|------------|-------------------|
| Latency | ~100ms | ~500-1000ms |
| Cost | Hardware cost | $3-15/M tokens |
| Quality | Model dependent | State-of-the-art |
| Reliability | Local control | API dependency |

## Next Steps

1. **Monitor Usage**: Track API costs via OpenRouter dashboard
2. **Optimize Prompts**: Reduce token usage for cost efficiency  
3. **Batch Processing**: Consider batching for multiple tasks
4. **Fallback Logic**: Implement fallback to local model if API fails

For more information, see the [OpenRouter API documentation](https://openrouter.ai/docs). 