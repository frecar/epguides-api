# 💻 Development Guide

Everything you need to contribute to the Epguides API.

---

## 🚀 Quick Start

```bash
# Clone and start
git clone https://github.com/frecar/epguides-api.git
cd epguides-api
make up

# 🎉 API running at http://localhost:3000
```

---

## 🔧 Commands

| Command | Description |
|---------|-------------|
| `make up` | ▶️ Start development environment |
| `make up-prod` | 🚀 Start production environment |
| `make down` | ⏹️ Stop all Docker services |
| `make test` | 🧪 Run all tests |
| `make fix` | 🔧 Format and lint |
| `make run` | ▶️ Run locally (no Docker) |
| `make logs` | 📋 View container logs |
| `make docs` | 📖 Serve docs locally |
| `make docs-build` | 📦 Build static docs |

---

## 🪝 Pre-commit Hooks

!!! success "Automatic Quality Checks"
    Pre-commit hooks ensure code quality on every commit.

### What They Do

1. 🔢 **Update version** - Increments build number
2. 🔧 **Format & lint** - Runs `make fix`

### Setup

```bash
# Install hooks (one-time)
pre-commit install
```

### Skip (Not Recommended)

```bash
git commit --no-verify
```

---

## 🏷️ Versioning

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

## 🧪 Testing

### Run Tests

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

### Test Structure

```
app/tests/
├── test_endpoints.py      # REST API unit tests
├── test_e2e.py            # End-to-end tests
├── test_llm_service.py    # LLM service tests
├── test_mcp.py            # MCP server tests
├── test_mcp_endpoints.py  # MCP HTTP tests
└── test_services.py       # Service layer tests
```

---

## ✨ Code Quality

!!! abstract "Tooling"
    The project enforces consistent code quality.

| Tool | Purpose |
|------|---------|
| 🎨 **Black** | Code formatting (120 chars) |
| 📦 **isort** | Import sorting |
| ⚡ **Ruff** | Fast linting |
| 🧪 **pytest** | Testing |

### Manual Checks

```bash
# Format only
make format

# Lint only
make lint

# Fix all
make fix
```

---

## 🏗️ Architecture

```
┌────────────┐      ┌────────────┐
│REST Router │      │ MCP Router │
│  /shows/*  │      │    /mcp    │
└─────┬──────┘      └──────┬─────┘
      │                    │
      └─────────┬──────────┘
                ▼
      ┌─────────────────┐
      │  Service Layer  │
      └────────┬────────┘
               │
     ┌─────────┼─────────┐
     ▼         ▼         ▼
┌───────┐ ┌───────┐ ┌───────┐
│ Redis │ │  EPG  │ │TVMaze │
│ Cache │ │scraper│ │client │
└───────┘ └───────┘ └───────┘
```

---

## 🐳 Docker Environments

!!! info "Two Docker Compose Files"
    The project includes separate configurations for development and production.

### Development Mode

```bash
make up
# or: docker compose up -d
```

**Features:**

- 🔄 Hot reload (code changes apply instantly)
- 🐛 Debug logging
- 💾 256MB Redis cache
- 📁 Volume mount for live code editing

### Production Mode

```bash
make up-prod
# or: docker compose -f docker-compose.prod.yml up -d
```

**Features:**

- ⚡ 12 uvicorn workers (optimized for 16-core server)
- 🚀 uvloop + httptools (2x faster)
- 💾 5GB Redis cache with io-threads
- 📊 Health checks and logging rotation
- 🔒 Resource limits and reservations

### Configuration Comparison

| Setting | Development | Production |
|---------|-------------|------------|
| **Workers** | 1 (with reload) | 12 |
| **Event loop** | asyncio | uvloop |
| **HTTP parser** | default | httptools |
| **Log level** | debug | warning |
| **Redis memory** | 256MB | 5GB |
| **Redis io-threads** | - | 8 |
| **Health checks** | Basic | Full |
| **Restart policy** | - | unless-stopped |

### Switching Environments

```bash
# Stop current environment
make down

# Start development
make up

# Or start production
make up-prod
```

### View Logs

```bash
# Development
docker compose logs -f

# Production
docker compose -f docker-compose.prod.yml logs -f
```

---

## 🏗️ Production Deployment

### Build Image

```bash
docker build -t epguides-api .
```

### Run with Custom Redis

```bash
docker run -d -p 3000:3000 \
  -e REDIS_HOST=your-redis \
  -e REDIS_PORT=6379 \
  -e API_BASE_URL=https://your-domain.com/ \
  epguides-api
```

### Dockerfile Features

| Feature | Description |
|---------|-------------|
| 🏗️ Multi-stage build | Smaller final image |
| 👤 Non-root user | Security best practice |
| 💚 Health check | For orchestration |
| ⚡ PYTHONOPTIMIZE=2 | Optimized bytecode |
| 📦 Slim base | Minimal attack surface |

---

## 🤝 Contributing

### 1️⃣ Fork & Clone

```bash
gh repo fork frecar/epguides-api --clone
cd epguides-api
```

### 2️⃣ Create Branch

```bash
git checkout -b feature/amazing-feature
```

### 3️⃣ Make Changes

- Write code
- Add tests
- Update docs

### 4️⃣ Test

```bash
make test
```

### 5️⃣ Commit

```bash
git commit -m "feat: add amazing feature"
```

!!! tip "Pre-commit hooks will auto-format"

### 6️⃣ Push & PR

```bash
git push origin feature/amazing-feature
```

Then open a Pull Request on GitHub.

---

## 📝 Code Style

| Rule | Standard |
|------|----------|
| 📏 Line length | 120 characters |
| 🏷️ Type hints | Required for all functions |
| ⚡ Async | Use for all I/O operations |
| 📖 Docstrings | Required for public functions |
