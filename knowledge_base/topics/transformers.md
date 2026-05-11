# Transformer Architecture

## What it is
The transformer is the neural network architecture behind virtually all modern AI language models, image generators, and multimodal systems. Introduced in Google's 2017 paper "Attention Is All You Need," it replaced older recurrent neural networks (RNNs) by processing entire sequences in parallel rather than one token at a time. This parallelism made transformers dramatically faster to train and enabled scaling to billions of parameters.

## How it works
The core innovation is the self-attention mechanism. For each token in a sequence, self-attention computes how relevant every other token is to it, creating a weighted representation that captures context. Think of reading a sentence: when you see the word "it" you automatically look back to figure out what "it" refers to — self-attention does this mathematically for every token simultaneously. The architecture has two main components: an encoder (reads and understands input) and a decoder (generates output). GPT-style models use decoder-only, BERT-style use encoder-only, and T5-style use both. Key building blocks: multi-head attention (multiple parallel attention computations capture different types of relationships), feed-forward layers, layer normalisation, and positional encodings (since attention has no inherent sense of word order).

## Key concepts
- **Self-attention**: Each token attends to all other tokens to build contextual representations
- **Multi-head attention**: Running attention multiple times in parallel to capture different patterns
- **Positional encoding**: Injecting sequence order information since attention is position-agnostic
- **Encoder-decoder**: The original architecture; encoders understand input, decoders generate output
- **Scaling laws**: Performance improves predictably with more parameters, data, and compute
- **Context window**: The maximum number of tokens the model can process at once (from 2K to 1M+)

## Current state (2026)
Transformers dominate AI. Every frontier model — GPT-4, Claude, Gemini, Llama — is transformer-based. Recent innovations include mixture-of-experts (MoE) for efficiency, state-space models (Mamba) as potential alternatives for very long sequences, and hybrid architectures that combine attention with other mechanisms. Context windows have expanded from 2,000 tokens to over a million, enabling entirely new applications.

## Why it matters
The transformer is arguably the most consequential AI architecture ever invented. Understanding how attention works is foundational to understanding modern AI — every chatbot, image generator, code assistant, and AI agent runs on transformers.

## Related topics
- [[llms]] — Large language models are transformers scaled up
- [[rag]] — RAG retrieves context for transformer-based generators
- [[prompt-engineering]] — Effective prompting exploits how transformers process context
