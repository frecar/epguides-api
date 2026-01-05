# Development Guide

## Quick Start

```bash
# Clone and start
git clone https://github.com/frecar/epguides-api.git
cd epguides-api
make up

# API is now running at http://localhost:3000
```

---

## Commands

| Command | Description |
|---------|-------------|
| `make up` | Start Docker services (API + Redis) |
| `make down` | Stop Docker services |
| `make test` | Run all tests |
| `make fix` | Format and lint code |
| `make run` | Run API locally (without Docker) |
| `make docs` | Serve documentation locally |
| `make docs-build` | Build static documentation |

---

## Pre-commit Hooks

The project includes pre-commit hooks that automatically:

1. **Update version number** - Increments build number in `VERSION` file
2. **Format and lint code** - Runs `make fix`

### Setup

```bash
# After cloning, install hooks
pre-commit install
```

### Skip (Not Recommended)

```bash
git commit --no-verify
```

---

## Versioning

The API uses a simple incrementing build number based on git commit count.

- The `VERSION` file contains the current build number
- Pre-commit hook automatically updates it
- No manual version management needed

```bash
# Check current version
cat VERSION

# Or via API
curl http://localhost:3000/health
```

---

## Testing

```bash
# Run all tests
make test

# Run with coverage
pytest --cov=app --cov-report=term-missing

# Run specific test file
pytest app/tests/test_endpoints.py

# Run specific test
pytest app/tests/test_endpoints.py::test_get_show

# Run only LLM integration tests (requires LLM configured)
pytest app/tests/test_e2e.py -k "llm"
```

### Test Structure

```
app/tests/
├── test_endpoints.py      # REST API unit tests
├── test_e2e.py            # End-to-end tests
├── test_llm_service.py    # LLM service tests
├── test_mcp.py            # MCP server unit tests
├── test_mcp_endpoints.py  # MCP HTTP endpoint tests
└── test_services.py       # Service layer tests
```

---

## Code Quality

The project enforces code quality with:

| Tool | Purpose |
|------|---------|
| **Black** | Code formatting (120 char line length) |
| **isort** | Import sorting |
| **Ruff** | Fast linting |
| **pytest** | Testing |

All checks run automatically via `make fix` and pre-commit hooks.

### Manual Checks

```bash
# Format code
make format

# Lint only
make lint

# Fix all (format + lint)
make fix
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        FastAPI App                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────┐  ┌─────────────────┐                  │
│  │   REST Router   │  │   MCP Router    │                  │
│  │   /shows/*      │  │     /mcp        │                  │
│  └────────┬────────┘  └────────┬────────┘                  │
│           │                    │                            │
│           └──────────┬─────────┘                            │
│                      │                                      │
│           ┌──────────▼──────────┐                          │
│           │   Service Layer     │                          │
│           │   (show_service)    │                          │
│           └──────────┬──────────┘                          │
│                      │                                      │
│    ┌─────────────────┼─────────────────┐                   │
│    │                 │                 │                   │
│    ▼                 ▼                 ▼                   │
│ ┌──────┐       ┌──────────┐     ┌───────────┐             │
│ │Cache │       │ epguides │     │  TVMaze   │             │
│ │(Redis)│       │ scraper  │     │  client   │             │
│ └──────┘       └──────────┘     └───────────┘             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Production Deployment

### Build Image

```bash
docker build -t epguides-api .
```

### Run Container

```bash
docker run -d -p 3000:3000 \
  -e REDIS_HOST=your-redis \
  -e REDIS_PORT=6379 \
  -e API_BASE_URL=https://your-domain.com/ \
  epguides-api
```

### Docker Features

The Dockerfile includes:

- ✅ Non-root user for security
- ✅ Health check for orchestration
- ✅ Optimized layer caching
- ✅ Alpine-based for smaller image

### Health Check

```bash
curl http://your-domain/health
```

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing`)
3. Make your changes
4. Run tests (`make test`)
5. Commit (pre-commit hooks will format code)
6. Push and create a Pull Request

### Code Style

- Follow PEP 8 with 120 char line length
- Use type hints for all functions
- Use async/await for I/O operations
- Add docstrings to public functions
