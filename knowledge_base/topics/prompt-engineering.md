# Prompt Engineering

## What it is
Prompt engineering is the practice of crafting inputs to language models to elicit the best possible outputs. Since LLMs are fundamentally next-token predictors, the way you frame a request dramatically affects the quality, accuracy, and format of the response. Good prompt engineering is the difference between a vague, generic answer and a precise, useful one. It is both an art (knowing what to ask) and an emerging science (systematic techniques with measurable results).

## How it works
At its core, prompting works because LLMs are pattern-completion machines. The prompt establishes a pattern, and the model continues it. A well-structured prompt sets the context, role, task, constraints, and output format so the model's continuation aligns with what you need. Think of it like briefing a contractor: the more specific and clear your brief, the closer the result matches your vision. Key techniques have been formalised through research and practice, each exploiting different aspects of how transformers process context.

## Key concepts
- **System prompts**: Instructions that set the model's role, behaviour, and constraints
- **Few-shot prompting**: Providing examples of desired input-output pairs in the prompt
- **Chain-of-thought (CoT)**: Asking the model to reason step-by-step before answering, which improves accuracy on complex tasks
- **Role prompting**: Assigning the model a specific persona ("You are a senior security engineer")
- **Structured output**: Requesting specific formats (JSON, XML, markdown) with schemas
- **Prompt chaining**: Breaking complex tasks into sequential prompts where each builds on the last
- **Temperature and sampling**: Adjusting randomness — low temperature for factual tasks, higher for creative ones
- **Extended thinking**: Giving models a dedicated reasoning space before they respond (used by Claude, o1)

## Current state (2026)
Prompt engineering has matured from ad-hoc tips into a systematic discipline. Best practices are well-documented: be specific, provide examples, use structured output formats, and break complex tasks into steps. The field is evolving as models become more capable — many techniques that helped weaker models are less necessary with frontier models, while new techniques (like extended thinking and tool-use prompting) have emerged. Automated prompt optimisation tools are growing but human expertise still outperforms them for novel tasks.

## Why it matters
Prompt engineering is the primary interface between humans and AI. Even as models improve, the quality of instructions determines the quality of output. For developers building AI applications, prompt design is often the single highest-leverage activity — more impactful than model choice or infrastructure optimisation.

## Related topics
- [[llms]] — The models being prompted
- [[agents]] — Agent orchestration relies heavily on system prompts
- [[rag]] — Retrieved context must be effectively integrated into prompts
