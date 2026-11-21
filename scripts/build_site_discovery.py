import subprocess
from pathlib import Path

from mkdocs.config.defaults import MkDocsConfig
from mkdocs.structure.files import File, Files

ROOT = Path(__file__).resolve().parents[1]


def on_files(files: Files, config: MkDocsConfig) -> Files:
    make_help = subprocess.check_output(
        ["make", "--no-print-directory", "help"],
        cwd=ROOT,
        text=True,
        timeout=15,
    ).rstrip()
    repository = config.repo_url.rstrip("/")
    api = config.extra["public_api_base_url"].rstrip("/")
    pages = {
        "configuration.md": (
            "# Configuration\n\n"
            f"[Environment template]({repository}/blob/main/.env.example) · "
            f"[Settings and defaults]({repository}/blob/main/app/core/config.py)\n"
        ),
        "development.md": f"# Development\n\n```text\n{make_help}\n```\n",
        "rest-api.md": (
            f"# REST API\n\n[Try the REST endpoints]({api}/docs#/Shows) · [Download OpenAPI]({api}/openapi.json)\n"
        ),
        "mcp-server.md": (
            "# MCP Server\n\n"
            f"Send JSON-RPC requests to `{api}/mcp`.\n\n"
            f"[Try discovery and tool calls]({api}/docs#/MCP) · [MCP health]({api}/mcp/health)\n"
        ),
    }
    readme = str(ROOT / "README.md")
    for source_uri in ("index.md", "getting-started.md"):
        files.append(File.generated(config, source_uri, abs_src_path=readme))
    for source_uri, content in pages.items():
        files.append(File.generated(config, source_uri, content=content))
    return files
