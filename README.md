# OpenGrok MCP Server 🔍

This is a Model Context Protocol (MCP) server for [OpenGrok](https://oracle.github.io/opengrok/), allowing AI assistants (like Claude, ChatGPT, or OpenClaw agents) to search and read source code indexed by OpenGrok.

## Features

- **`search`**: Multi-dimensional search across projects (full text, definitions, symbols, paths).
- **`get_file`**: Retrieve raw content of any file in the index.
- **`list_projects`**: Discover all indexed projects in the OpenGrok instance.

## Prerequisites

- **Python 3.10+**
- An active OpenGrok instance with REST API enabled (default in modern versions).

## Installation

```bash
git clone https://github.com/your-username/opengrok-mcp.git
cd opengrok-mcp
pip install -r requirements.txt
```

## Configuration

The server is configured via environment variables:

| Variable | Description | Default |
| :--- | :--- | :--- |
| `OPENGROK_URL` | Base URL of your OpenGrok instance (including `/source`) | `http://localhost:8080/source` |

## Usage

### Integration with MCP Clients

#### OpenClaw

Add to your `openclaw.json`:

```json
"plugins": {
  "entries": {
    "opengrok-mcp": {
      "enabled": true,
      "config": {
        "command": "python3",
        "args": ["/path/to/opengrok-mcp/server.py"],
        "env": {
          "OPENGROK_URL": "http://your-server:8080/source"
        }
      }
    }
  }
}
```

#### Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "opengrok": {
      "command": "python3",
      "args": ["/absolute/path/to/opengrok-mcp/server.py"],
      "env": {
        "OPENGROK_URL": "http://your-server:8080/source"
      }
    }
  }
}
```

## Development and Testing

You can test the server locally by setting the environment variable and running it directly:

```bash
export OPENGROK_URL="http://your-server:8080/source"
python3 server.py
```
*Note: The server communicates via JSON-RPC over Standard Input/Output.*

## License

MIT
