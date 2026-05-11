# AI Agents

## What it is
An AI agent is a system that uses a large language model as its reasoning engine and can autonomously plan, use tools, and take actions to accomplish goals. Unlike chatbots that respond to a single prompt, agents operate in a loop: reason about what to do, act (call a tool, write code, search the web), observe the result, then decide the next step. This loop continues until the task is complete.

## How it works
The core pattern is the ReAct (Reason + Act) loop. The LLM receives a goal and a set of available tools (functions it can call). It generates a plan, selects a tool, the system executes that tool and returns the output, then the LLM reassesses. Think of it like hiring a junior employee: you give them a task, they figure out the steps, use the resources available to them, and come back with the result. Key components: the brain (the LLM), tools (APIs, code execution, web search), memory (conversation context + persistent storage), and orchestration (the code managing the loop, errors, and guardrails).

## Key concepts
- **Tool use / function calling**: The LLM generates structured requests to invoke external tools
- **Planning**: Breaking a complex goal into subtasks before executing
- **Reflection**: The agent evaluates its own output and self-corrects
- **Multi-agent systems**: Multiple specialised agents collaborating on a task
- **Human-in-the-loop**: Agents that ask for human approval at critical decision points
- **Agentic coding**: Agents that write, test, and debug code autonomously (Claude Code, GitHub Copilot Agent Mode)

## Current state (2026)
The major players: Anthropic (Claude Code, Agent SDK), OpenAI (Operator, ChatGPT agents), Google (Remy, Gemini agents), Meta (Hatch). Frameworks like LangGraph, CrewAI, and AutoGen make building agents accessible. Production deployments are growing in customer support, coding, research, and data analysis. The key challenge remains reliability — agents still fail on complex multi-step tasks roughly 20-30% of the time, making human oversight essential.

## Why it matters
Agents represent the shift from AI as a tool you operate to AI as a worker that operates tools on your behalf. This fundamentally changes software, automation, and knowledge work. The companies that master agentic AI will define the next era of computing.

## Related topics
- [[llms]] — The foundation models that power agents
- [[mcp]] — Protocol for connecting agents to external tools
- [[prompt-engineering]] — Techniques for directing agent behaviour
