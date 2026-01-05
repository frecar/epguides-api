# :material-code-braces: Development Guide

Everything you need to contribute to the Epguides API.

---

## :material-rocket-launch: Quick Start

```bash
# Clone and start
git clone https://github.com/frecar/epguides-api.git
cd epguides-api
make up

# 🎉 API running at http://localhost:3000
```

---

## :material-console: Commands

| Command | Description |
|---------|-------------|
| `make up` | :material-play: Start Docker services |
| `make down` | :material-stop: Stop Docker services |
| `make test` | :material-test-tube: Run all tests |
| `make fix` | :material-auto-fix: Format and lint |
| `make run` | :material-play-outline: Run locally |
| `make docs` | :material-book: Serve docs |
| `make docs-build` | :material-package: Build static docs |

---

## :material-git: Pre-commit Hooks

!!! success "Automatic Quality Checks"
    Pre-commit hooks ensure code quality on every commit.

### :material-check-all: What They Do

1. :material-numeric-plus: **Update version** - Increments build number
2. :material-auto-fix: **Format & lint** - Runs `make fix`

### :material-download: Setup

```bash
# Install hooks (one-time)
pre-commit install
```

### :material-skip-forward: Skip (Not Recommended)

```bash
git commit --no-verify
```

---

## :material-tag: Versioning

!!! info "Automatic Versioning"
    Version is a simple incrementing number based on git commits.

| Component | Location |
|-----------|----------|
| Version file | `VERSION` |
| Updated by | Pre-commit hook |
| Manual management | Not needed |

```bash
# Check current version
cat VERSION

# Or via API
curl http://localhost:3000/health
```

---

## :material-test-tube: Testing

### :material-play: Run Tests

```bash
# All tests
make test

# With coverage
pytest --cov=app --cov-report=term-missing

# Specific file
pytest app/tests/test_endpoints.py

# Specific test
pytest app/tests/test_endpoints.py::test_get_show

# LLM integration tests (requires LLM)
pytest app/tests/test_e2e.py -k "llm"
```

### :material-folder-outline: Test Structure

```
app/tests/
├── 📄 test_endpoints.py      # REST API unit tests
├── 📄 test_e2e.py            # End-to-end tests
├── 📄 test_llm_service.py    # LLM service tests
├── 📄 test_mcp.py            # MCP server tests
├── 📄 test_mcp_endpoints.py  # MCP HTTP tests
└── 📄 test_services.py       # Service layer tests
```

---

## :material-check-decagram: Code Quality

!!! abstract "Tooling"
    The project enforces consistent code quality.

| Tool | Purpose |
|------|---------|
| :material-format-paint: **Black** | Code formatting (120 chars) |
| :material-sort-alphabetical-ascending: **isort** | Import sorting |
| :material-lightning-bolt: **Ruff** | Fast linting |
| :material-test-tube: **pytest** | Testing |

### :material-console: Manual Checks

```bash
# Format only
make format

# Lint only
make lint

# Fix all
make fix
```

---

## :material-chart-box: Architecture

```
┌────────────────────────────────────────────────────────────┐
│                     🏗️ Architecture                        │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  ┌─────────────────┐    ┌─────────────────┐               │
│  │   REST Router   │    │   MCP Router    │               │
│  │    /shows/*     │    │      /mcp       │               │
│  └────────┬────────┘    └────────┬────────┘               │
│           │                      │                         │
│           └──────────┬───────────┘                         │
│                      ▼                                     │
│           ┌─────────────────────┐                          │
│           │    Service Layer    │                          │
│           │   (show_service)    │                          │
│           └──────────┬──────────┘                          │
│                      │                                     │
│    ┌─────────────────┼─────────────────┐                   │
│    ▼                 ▼                 ▼                   │
│  ┌──────┐      ┌──────────┐     ┌───────────┐              │
│  │Cache │      │ epguides │     │  TVMaze   │              │
│  │Redis │      │ scraper  │     │  client   │              │
│  └──────┘      └──────────┘     └───────────┘              │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

---

## :material-docker: Production Deployment

### :material-package: Build Image

```bash
docker build -t epguides-api .
```

### :material-play: Run Container

```bash
docker run -d -p 3000:3000 \
  -e REDIS_HOST=your-redis \
  -e REDIS_PORT=6379 \
  -e API_BASE_URL=https://your-domain.com/ \
  epguides-api
```

### :material-shield-check: Docker Features

| Feature | Description |
|---------|-------------|
| :material-account: Non-root user | Security best practice |
| :material-heart-pulse: Health check | For orchestration |
| :material-layers: Layer caching | Fast rebuilds |
| :material-size-s: Alpine base | Smaller image |

---

## :material-source-pull: Contributing

### :material-numeric-1-circle: Fork & Clone

```bash
gh repo fork frecar/epguides-api --clone
cd epguides-api
```

### :material-numeric-2-circle: Create Branch

```bash
git checkout -b feature/amazing-feature
```

### :material-numeric-3-circle: Make Changes

- Write code
- Add tests
- Update docs

### :material-numeric-4-circle: Test

```bash
make test
```

### :material-numeric-5-circle: Commit

```bash
git commit -m "feat: add amazing feature"
```

!!! tip "Pre-commit hooks will auto-format"

### :material-numeric-6-circle: Push & PR

```bash
git push origin feature/amazing-feature
```

Then open a Pull Request on GitHub.

---

## :material-file-document-edit: Code Style

| Rule | Standard |
|------|----------|
| :material-ruler: Line length | 120 characters |
| :material-tag-text: Type hints | Required for all functions |
| :material-sync: Async | Use for all I/O operations |
| :material-text-box: Docstrings | Required for public functions |
