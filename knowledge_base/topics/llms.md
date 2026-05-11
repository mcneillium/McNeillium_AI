# Large Language Models (LLMs)

## What it is
A large language model is a neural network (typically a transformer) trained on massive text datasets to predict the next token in a sequence. Despite this simple training objective, scaling to hundreds of billions of parameters produces emergent capabilities: reasoning, code generation, translation, summarisation, and instruction following. LLMs are the foundation of modern AI assistants, coding tools, and agentic systems.

## How it works
Training happens in stages. Pre-training: the model reads trillions of tokens of text from the internet, books, and code, learning to predict the next word. This creates a powerful base model that understands language structure and has broad knowledge. Fine-tuning: the base model is trained on curated instruction-response pairs to follow human directions. RLHF (Reinforcement Learning from Human Feedback): human raters rank the model's outputs, training a reward model that further aligns the LLM with human preferences. Think of it as: pre-training gives the model knowledge, fine-tuning teaches it manners, and RLHF teaches it judgment.

## Key concepts
- **Tokens**: The units LLMs process — roughly 3/4 of a word in English
- **Parameters**: The learned weights — GPT-4 has an estimated 1.8 trillion across mixture-of-experts
- **Context window**: Maximum input length — ranges from 4K to over 1M tokens in 2026
- **Temperature**: Controls randomness in generation — low for factual, high for creative
- **Inference**: Running the model to generate output (as opposed to training)
- **Frontier models**: The most capable models from leading labs (Claude, GPT, Gemini)
- **Open-weight models**: Models with publicly available weights (Llama, Mistral, Qwen)

## Current state (2026)
The frontier is led by Anthropic (Claude 4 family), OpenAI (GPT-4+), Google (Gemini 2), and Meta (Llama 4). Open-weight models from Meta, Mistral, and Alibaba (Qwen) have closed the gap significantly, enabling local deployment. Key trends: longer context windows, multimodal capabilities (text + images + audio + video), and the shift from standalone chat to agentic workflows. Cost has dropped roughly 100x in two years, making LLMs economically viable for a vastly wider range of applications.

## Why it matters
LLMs are the most general-purpose technology since the internet. They power search, coding assistants, customer support, content creation, research, education, and increasingly autonomous agents. Understanding LLMs is essential for anyone working in or affected by technology — which is effectively everyone.

## Related topics
- [[transformers]] — The architecture LLMs are built on
- [[agents]] — LLMs as the reasoning engine for autonomous systems
- [[prompt-engineering]] — Techniques for getting the best output from LLMs
- [[rag]] — Augmenting LLMs with external knowledge
