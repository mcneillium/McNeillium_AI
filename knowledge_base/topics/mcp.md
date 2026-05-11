# Model Context Protocol (MCP)

## What it is
MCP is an open protocol created by Anthropic that standardises how AI models connect to external tools, data sources, and services. Before MCP, every AI application needed custom integrations for each tool — one connector for Google Drive, another for GitHub, another for Slack. MCP creates a universal interface: build one MCP server for your tool, and any MCP-compatible AI client can use it. It has been called "the USB-C of AI" because it replaces a tangle of proprietary connectors with a single standard.

## How it works
MCP uses a client-server architecture. The AI application (like Claude Code or Cursor) is the MCP client. External services expose MCP servers that describe what tools they offer using a structured schema. When the AI needs to use a tool, it sends a request through the MCP protocol, the server executes it and returns the result. The protocol handles discovery (what tools are available?), invocation (call this tool with these parameters), and response (here's the result). Think of it like a restaurant menu: the MCP server publishes a menu of capabilities, and the AI orders what it needs.

## Key concepts
- **MCP servers**: Programs that expose tools, resources, and prompts to AI clients
- **MCP clients**: AI applications that connect to MCP servers (Claude Desktop, IDEs, custom apps)
- **Tools**: Functions the AI can call (search files, query databases, send messages)
- **Resources**: Data the AI can read (documents, database records, API responses)
- **Transport**: Communication layer — typically stdio (local) or SSE/HTTP (remote)
- **Tool schemas**: JSON descriptions of each tool's name, parameters, and return type

## Current state (2026)
MCP has been widely adopted since its late 2024 release. Major adopters include Claude Code, Cursor, VS Code, JetBrains IDEs, and dozens of AI applications. Thousands of community-built MCP servers exist for databases, APIs, cloud services, and dev tools. Anthropic, Google, and Microsoft have all committed to the protocol. The ecosystem is still maturing — security, authentication, and remote server hosting are active development areas.

## Why it matters
MCP solves the integration problem that was holding back practical AI deployment. Instead of building N x M custom integrations (N AI apps times M tools), you build N + M MCP implementations. This dramatically lowers the barrier for connecting AI to real-world systems, which is essential for agents that need to take actions, not just generate text.

## Related topics
- [[agents]] — MCP enables agents to use external tools
- [[llms]] — The models that consume MCP tool results
- [[prompt-engineering]] — Tool descriptions in MCP are essentially prompts
