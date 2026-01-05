# :material-rocket-launch: Getting Started

Get up and running with the Epguides API in minutes.

---

## :material-cloud: Using the Public API

!!! success "Fastest way to start"
    The public API requires **no setup** - just start making requests!

| | Resource | URL |
|---|----------|-----|
| :material-api: | **Base URL** | `https://epguides.frecar.no` |
| :material-file-document: | **Swagger UI** | [epguides.frecar.no/docs](https://epguides.frecar.no/docs) |
| :material-book-open: | **ReDoc** | [epguides.frecar.no/redoc](https://epguides.frecar.no/redoc) |

### :material-console: Quick Examples

```bash
# 📺 Get show details
curl "https://epguides.frecar.no/shows/BreakingBad"

# 🔍 Search shows
curl "https://epguides.frecar.no/shows/search?query=breaking"

# 📋 Get episodes
curl "https://epguides.frecar.no/shows/BreakingBad/episodes"

# 🎯 Filter by season
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?season=5"
```

---

## :material-docker: Local Development

### :material-clipboard-check: Prerequisites

| Requirement | Version | Required |
|-------------|---------|----------|
| :material-docker: Docker | Latest | ✅ Yes |
| :material-git: Git | Latest | ✅ Yes |
| :material-language-python: Python | 3.11+ | ⚪ Optional (for tests) |

### :material-play-circle: Quick Start

=== ":material-numeric-1-circle: Clone"

    ```bash
    git clone https://github.com/frecar/epguides-api.git
    cd epguides-api
    ```

=== ":material-numeric-2-circle: Start"

    ```bash
    make up
    ```

=== ":material-numeric-3-circle: Open"

    ```bash
    open http://localhost:3000/docs
    ```

!!! tip "That's it!"
    The API is now running at `http://localhost:3000` with hot-reload enabled.

### :material-information: What `make up` Does

1. :material-docker: Builds the Docker image
2. :material-play: Starts FastAPI with hot-reload
3. :material-database: Starts Redis for caching
4. :material-tag: Sets version from git commit count

---

## :material-cog-outline: First Time Setup (Optional)

!!! note "Only needed for running tests locally"
    If you just want to run the API, `make up` is all you need!

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install pre-commit hooks (recommended)
pre-commit install
```

---

## :material-console: Development Commands

| Command | Description |
|---------|-------------|
| `make up` | :material-play: Start Docker services |
| `make down` | :material-stop: Stop Docker services |
| `make test` | :material-test-tube: Run tests |
| `make fix` | :material-auto-fix: Format and lint code |
| `make run` | :material-play-outline: Run locally (without Docker) |
| `make docs` | :material-book: Serve documentation |

---

## :material-folder-outline: Project Structure

```
epguides-api/
├── 📂 app/
│   ├── 📂 api/endpoints/      # REST endpoints
│   ├── 📂 core/               # Config, cache, middleware
│   ├── 📂 mcp/                # MCP server
│   ├── 📂 models/             # Pydantic schemas
│   ├── 📂 services/           # Business logic
│   └── 📂 tests/              # Test suite
├── 📂 docs/                   # Documentation
├── 🐳 Dockerfile              # Production container
├── 🐳 docker-compose.yml      # Development setup
├── 📄 Makefile                # Dev commands
└── 📄 requirements.txt        # Dependencies
```

---

## :material-arrow-right-circle: Next Steps

<div class="grid cards" markdown>

-   :material-api:{ .lg .middle } **REST API Reference**

    ---

    Explore all endpoints and response formats

    [:octicons-arrow-right-24: REST API](rest-api.md)

-   :material-robot:{ .lg .middle } **MCP Server**

    ---

    Integrate with AI assistants

    [:octicons-arrow-right-24: MCP Server](mcp-server.md)

-   :material-cog:{ .lg .middle } **Configuration**

    ---

    Environment variables and caching

    [:octicons-arrow-right-24: Configuration](configuration.md)

-   :material-code-braces:{ .lg .middle } **Development**

    ---

    Contributing and testing

    [:octicons-arrow-right-24: Development](development.md)

</div>
