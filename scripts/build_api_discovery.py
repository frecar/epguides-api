from mkdocs.config.defaults import MkDocsConfig
from mkdocs.structure.files import File, Files


def on_files(files: Files, config: MkDocsConfig) -> Files:
    api = config.extra["public_api_base_url"].rstrip("/")
    pages = {
        "rest-api.md": (
            f"# REST API\n\n[Try the REST endpoints]({api}/docs#/Shows) · [Download OpenAPI]({api}/openapi.json)\n"
        ),
        "mcp-server.md": (
            "# MCP Server\n\n"
            f"Send JSON-RPC requests to `{api}/mcp`.\n\n"
            f"[Try discovery and tool calls]({api}/docs#/MCP) · [MCP health]({api}/mcp/health)\n"
        ),
    }
    for source_uri, content in pages.items():
        files.append(File.generated(config, source_uri, content=content))
    return files
