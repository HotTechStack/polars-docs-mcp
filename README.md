# README.md

```markdown
# Polars Docs MCP

A FastMCP tool to search and retrieve Polars API documentation.

## Features

- Automatically discover Polars public components (classes, functions, submodules).
- Search Polars API by component or query string.
- Returns structured JSON with API signatures and descriptions.
- Integrates with `mcp` for seamless LLM-powered workflows.

## Usage

1. Claude Desktop Config

```json
{
    "mcpServers": {
        "polarsapifinder": {
            "command": "uv",
            "args": [
                "--directory",
                <PATH TO polars-docs-mcp>",
                "run",
                "polarsdocsfinder.py"
            ]
        }
    }
}
```

Requires Python 3.11+.


### Tool Endpoints

- `list_polars_components()`: List all high-level Polars API components.
- `search_polars_docs(api_refs: list[str] | None, query: str | None, max_results: int = 1000)`: Search and retrieve API signatures.


## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Contact

Created by [ABC](mailto:abc@abhishekchoudhary.net). Report issues or request features at https://github.com/HotTechStack/polars-docs-mcp/issues.
