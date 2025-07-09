#!/bin/bash

# OpenRouter API Setup Script for WebArena Lite Planner Agent

echo "=== OpenRouter API Setup for WebArena Lite ==="

# Check if OpenRouter API key is provided
if [ -z "$1" ]; then
    echo "Usage: $0 <your_openrouter_api_key>"
    echo "Example: $0 sk-or-v1-abcd1234..."
    echo ""
    echo "You can get your API key from: https://openrouter.ai/keys"
    exit 1
fi

OPENROUTER_API_KEY="$1"

# Export the API key for current session
export OPENROUTER_API_KEY="$OPENROUTER_API_KEY"

echo "✓ OpenRouter API key set for current session"

# Test the API connection
echo "Testing OpenRouter API connection..."

python3 -c "
import openai
import os

client = openai.OpenAI(
    api_key='$OPENROUTER_API_KEY',
    base_url='https://openrouter.ai/api/v1'
)

try:
    response = client.chat.completions.create(
        model='anthropic/claude-sonnet-4',
        messages=[{'role': 'user', 'content': 'Hello, just testing the connection. Please respond with \"DeepSeek R1 is working!\"'}],
        max_tokens=8192,
        temperature=0
    )
    print('✓ OpenRouter API connection successful!')
    print('Response:', response.choices[0].message.content)
except Exception as e:
    print('✗ OpenRouter API connection failed:', str(e))
    exit(1)
"

if [ $? -eq 0 ]; then
    echo ""
    echo "=== Setup Complete ==="
    echo "✓ OpenRouter API is working correctly"
    echo "✓ Claude Sonnet 4 is accessible"
    echo ""
    echo "To make the API key persistent, add this to your ~/.bashrc or ~/.zshrc:"
    echo "export OPENROUTER_API_KEY=\"$OPENROUTER_API_KEY\""
    echo ""
    echo "You can now run the planner agent with: ./run_plan_act.sh"
else
    echo "Setup failed. Please check your API key and try again."
    exit 1
fi 