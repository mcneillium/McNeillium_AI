#!/usr/bin/env python3
"""
McNeillium_AI — Script Generator
Uses Claude API to generate structured video scripts.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import anthropic
import yaml
from dotenv import load_dotenv

load_dotenv()

# Resolve paths relative to project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
OUTPUT_DIR = PROJECT_ROOT / "output" / "scripts"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


SYSTEM_PROMPT = """You are a professional YouTube scriptwriter for the channel "McNeillium_AI", 
which covers AI, machine learning, and emerging technology topics.

Your scripts should be:
- Conversational and engaging, as if talking directly to the viewer
- Educational but accessible — explain jargon when first used
- Include specific examples, analogies, and real-world applications
- Structured with clear sections for video production

IMPORTANT: Respond ONLY with valid JSON matching this exact structure:

{
  "title": "Video title for YouTube",
  "description": "YouTube video description (2-3 sentences with keywords)",
  "tags": ["tag1", "tag2", "tag3"],
  "sections": [
    {
      "id": "hook",
      "heading": "Section display heading",
      "narration": "The exact words to be spoken aloud by TTS. Write naturally.",
      "screen_text": "Key bullet points or text shown on screen (shorter than narration)",
      "visual_notes": "Description of what should appear on screen"
    }
  ],
  "estimated_duration_seconds": 480
}

Each section should have these types (in order):
1. hook — A compelling question or statement (15-30 seconds spoken)
2. intro — Introduce the topic and what viewers will learn (30-60 seconds)
3-5. main_point — Key concepts with examples (60-120 seconds each)
6. demo — A practical walkthrough or example (60-120 seconds)
7. summary — Recap the key takeaways (30-45 seconds)
8. outro — Call to action: like, subscribe, comment (15-30 seconds)
"""


def generate_script(topic: str, config: dict) -> dict:
    """Generate a video script using Claude API."""

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set in .env file")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    script_config = config.get("script", {})
    target_mins = script_config.get("target_duration_minutes", 8)

    user_prompt = f"""Create a complete YouTube video script about:

**Topic:** {topic}

**Target Duration:** ~{target_mins} minutes of spoken content
**Style:** {script_config.get('style', 'conversational and educational')}
**Channel:** {config['channel']['name']} — {config['channel'].get('tagline', '')}

Make the hook attention-grabbing. Use real examples and current developments.
Include specific details, not vague statements.
The narration text will be read by TTS, so write it to sound natural when spoken aloud.
Avoid markdown formatting in the narration — just plain spoken English.
"""

    print(f"  Generating script for: {topic}")
    print(f"  Model: {script_config.get('model', 'claude-sonnet-4-5-20241022')}")

    response = client.messages.create(
        model=script_config.get("model", "claude-sonnet-4-5-20241022"),
        max_tokens=script_config.get("max_tokens", 4096),
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    # Extract the JSON from the response
    response_text = response.content[0].text.strip()

    # Clean up if wrapped in code fences
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1]
        if response_text.endswith("```"):
            response_text = response_text.rsplit("```", 1)[0]
        response_text = response_text.strip()

    try:
        script_data = json.loads(response_text)
    except json.JSONDecodeError as e:
        print(f"  ERROR: Failed to parse script JSON: {e}")
        print(f"  Raw response saved to output/scripts/debug_response.txt")
        debug_path = OUTPUT_DIR / "debug_response.txt"
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(response_text)
        sys.exit(1)

    # Add metadata
    script_data["metadata"] = {
        "topic": topic,
        "generated_at": datetime.now().isoformat(),
        "model": script_config.get("model", "claude-sonnet-4-5-20241022"),
        "channel": config["channel"]["name"],
    }

    return script_data


def save_script(script_data: dict, topic: str) -> Path:
    """Save script to JSON file and return the path."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Create a filename from the topic
    safe_name = "".join(c if c.isalnum() or c in " -_" else "" for c in topic)
    safe_name = safe_name.strip().replace(" ", "_")[:60]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{safe_name}.json"

    filepath = OUTPUT_DIR / filename
    with open(filepath, "w") as f:
        json.dump(script_data, f, indent=2)

    # Also save as 'latest.json' for easy pipeline access
    latest_path = OUTPUT_DIR / "latest.json"
    with open(latest_path, "w") as f:
        json.dump(script_data, f, indent=2)

    return filepath


def main():
    parser = argparse.ArgumentParser(description="Generate a video script using Claude")
    parser.add_argument("--topic", "-t", required=True, help="Video topic")
    args = parser.parse_args()

    config = load_config()

    print("\n🎬 McNeillium_AI — Script Generator")
    print("=" * 50)

    script_data = generate_script(args.topic, config)
    filepath = save_script(script_data, args.topic)

    print(f"\n  ✅ Script saved: {filepath}")
    print(f"  📝 Title: {script_data.get('title', 'Untitled')}")
    print(f"  📑 Sections: {len(script_data.get('sections', []))}")
    est = script_data.get("estimated_duration_seconds", 0)
    print(f"  ⏱  Est. duration: {est // 60}m {est % 60}s")

    return filepath


if __name__ == "__main__":
    main()
