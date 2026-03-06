# OpenGrok MCP Server 🔍

This is a Model Context Protocol (MCP) server for [OpenGrok](https://oracle.github.io/opengrok/), allowing AI assistants (like Claude, ChatGPT, or OpenClaw agents) to search and read source code indexed by OpenGrok.

## Features

- **`search`**: Multi-dimensional search across projects (full text, definitions, symbols, paths).
- **`get_file`**: Retrieve raw content of any file in the index.
- **`get_defs`**: Get symbol definitions for a specific file (functions, variables, etc.).
- **`get_history`**: Get revision history for a file or directory.
- **`get_annotations`**: Get blame/annotation information (line-by-line author/revision).
- **`list_directory`**: List entries in a directory (like an explorer).
- **`list_projects`**: Discover all indexed projects in the OpenGrok instance.

## Prerequisites

- **Python 3.10+**
- An active OpenGrok instance with REST API enabled (default in modern versions).

## Installation

```bash
git clone https://github.com/xiaowenzhou/opengrok-mcp.git
cd opengrok-mcp
# Recommended: use a virtual environment
python3 -m venv venv
source venv/bin/activate
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
      "command": "/path/to/opengrok-mcp/venv/bin/python3",
      "args": ["/path/to/opengrok-mcp/server.py"],
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
# Using the test client script
./venv/bin/python3 test_client.py
```
*Note: The server communicates via JSON-RPC over Standard Input/Output.*

## License

MIT
