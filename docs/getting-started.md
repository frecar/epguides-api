# 🚀 Getting Started

Get up and running with the Epguides API in minutes.

---

## 🌐 Using the Public API

!!! success "No setup required"
    The public API is free and requires no authentication. Just start making requests!

| Resource | URL |
|----------|-----|
| **Base URL** | `https://epguides.frecar.no` |
| **Swagger UI** | [epguides.frecar.no/docs](https://epguides.frecar.no/docs) |
| **ReDoc** | [epguides.frecar.no/redoc](https://epguides.frecar.no/redoc) |

### Try It Now

```bash
# Get show details
curl "https://epguides.frecar.no/shows/BreakingBad"

# Search shows
curl "https://epguides.frecar.no/shows/search?query=breaking"

# Get episodes
curl "https://epguides.frecar.no/shows/BreakingBad/episodes"

# Filter by season
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?season=5"

# Get next episode for ongoing shows
curl "https://epguides.frecar.no/shows/Severance/episodes/next"
```

---

## 🐳 Self-Hosting (Local Development)

### Prerequisites

| Requirement | Version | Required |
|-------------|---------|:--------:|
| Docker | Latest | ✅ |
| Git | Latest | ✅ |
| Python | 3.11+ | ⚪ Optional |

### Quick Start

=== "1. Clone"

    ```bash
    git clone https://github.com/frecar/epguides-api.git
    cd epguides-api
    ```

=== "2. Start"

    ```bash
    make up
    ```

=== "3. Open"

    ```bash
    open http://localhost:3000/docs
    ```

!!! tip "That's it!"
    The API is now running at `http://localhost:3000` with hot-reload enabled.

### What `make up` Does

1. 🐳 Builds the Docker image
2. ▶️ Starts FastAPI with hot-reload
3. 🗄️ Starts Redis for caching
4. 🏷️ Sets version from git commit count

---

## ⚙️ First Time Setup (Optional)

!!! note "Only needed for running tests locally"
    If you just want to run the API, `make up` is all you need!

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install pre-commit hooks
pre-commit install
```

---

## 🔧 Commands

| Command | Description |
|---------|-------------|
| `make up` | Start Docker services |
| `make down` | Stop Docker services |
| `make test` | Run tests |
| `make fix` | Format and lint code |
| `make run` | Run locally (without Docker) |
| `make docs` | Serve documentation |

---

## 📁 Project Structure

```
epguides-api/
├── app/
│   ├── api/endpoints/      # REST API routes
│   ├── core/               # Config, cache, middleware
│   ├── mcp/                # MCP server for AI
│   ├── models/             # Pydantic schemas
│   ├── services/           # Business logic
│   └── tests/              # Test suite
├── docs/                   # This documentation
├── Dockerfile              # Production container
├── docker-compose.yml      # Development setup
├── Makefile                # Dev commands
└── requirements.txt        # Dependencies
```

---

## ➡️ Next Steps

- **[REST API Reference](rest-api.md)** — All endpoints with examples
- **[MCP Server](mcp-server.md)** — Integrate with AI assistants
- **[Configuration](configuration.md)** — Environment variables & caching
- **[Development](development.md)** — Contributing & testing
