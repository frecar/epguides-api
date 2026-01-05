# Getting Started

## Using the Public API

The fastest way to get started is using the public API:

| Resource | URL |
|----------|-----|
| Base URL | `https://epguides.frecar.no` |
| Swagger UI | [https://epguides.frecar.no/docs](https://epguides.frecar.no/docs) |
| ReDoc | [https://epguides.frecar.no/redoc](https://epguides.frecar.no/redoc) |

### Quick Examples

```bash
# Get show details
curl "https://epguides.frecar.no/shows/BreakingBad"

# Search shows
curl "https://epguides.frecar.no/shows/search?query=breaking"

# Get episodes
curl "https://epguides.frecar.no/shows/BreakingBad/episodes"

# Filter by season
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?season=5"
```

---

## Local Development

### Prerequisites

- Docker and Docker Compose
- Git
- Python 3.11+ (optional, for running tests locally)

### Quick Start

```bash
# Clone repository
git clone https://github.com/frecar/epguides-api.git
cd epguides-api

# Start all services (API + Redis)
make up

# Open local API docs
open http://localhost:3000/docs
```

That's it! The API is now running at `http://localhost:3000`.

### What `make up` Does

1. Builds the Docker image
2. Starts the FastAPI server with hot-reload
3. Starts Redis for caching
4. Sets the version from git commit count

---

## First Time Setup (Optional)

If you want to run tests or use development tools locally (outside Docker):

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

## Development Commands

| Command | Description |
|---------|-------------|
| `make up` | Start Docker services |
| `make down` | Stop Docker services |
| `make test` | Run tests |
| `make fix` | Format and lint code |
| `make run` | Run API locally (without Docker) |
| `make docs` | Serve documentation locally |

---

## Project Structure

```
epguides-api/
├── app/
│   ├── api/endpoints/      # REST endpoints (shows.py, mcp.py)
│   ├── core/               # Config, cache, middleware, constants
│   ├── mcp/                # MCP server implementation
│   ├── models/             # Pydantic schemas
│   ├── services/           # Business logic
│   └── tests/              # Test suite
├── docs/                   # Documentation (ReadTheDocs)
├── Dockerfile              # Production container
├── docker-compose.yml      # Development setup
├── Makefile                # Development commands
└── requirements.txt        # Python dependencies
```

---

## Next Steps

- [REST API Reference](rest-api.md) - Explore all endpoints
- [MCP Server](mcp-server.md) - AI assistant integration
- [Configuration](configuration.md) - Environment variables
- [Development](development.md) - Contributing guide
