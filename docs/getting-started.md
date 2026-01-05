# Getting Started

## Using the Public API

The easiest way to use the API is via the public endpoint:

- **Base URL**: `https://epguides.frecar.no`
- **Interactive Docs**: [https://epguides.frecar.no/docs](https://epguides.frecar.no/docs)

```bash
# Get show details
curl "https://epguides.frecar.no/shows/BreakingBad"

# Search shows
curl "https://epguides.frecar.no/shows/search?query=breaking"

# Get episodes
curl "https://epguides.frecar.no/shows/BreakingBad/episodes"
```

## Local Development

### Prerequisites

- Docker and Docker Compose
- Python 3.11+ (for running tests locally)
- Git

### Quick Start

```bash
# Clone repository
gh repo clone frecar/epguides-api
cd epguides-api

# Start all services
make up

# Access local API docs
open http://localhost:3000/docs
```

### First Time Setup

If you want to run tests or development tools locally:

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Install pre-commit hooks (recommended)
pre-commit install
```

### Development Commands

```bash
# Start Docker services
make up

# Stop Docker services
make down

# View logs
make logs

# Run tests
make test

# Format and lint code
make fix

# Run API locally (without Docker)
make run
```

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
├── docs/                   # Documentation (you are here)
├── Dockerfile              # Production container
├── docker-compose.yml      # Development setup
├── Makefile                # Development commands
└── requirements.txt        # Python dependencies
```

