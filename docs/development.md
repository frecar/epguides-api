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

The CI secret scanner downloads a version- and SHA256-pinned gitleaks binary.
If its release URL fails, it tries the exact uploaded asset through GitHub's
REST API once. Both transports must match the same checksum before extraction
or installation; failed or ambiguous metadata and wrong bytes keep the check
red. The ephemeral job token stays in `GH_TOKEN`, and temporary partials are
removed on exit. Installer failure contracts live in
`app/tests/test_gitleaks_download.py`.

### What They Do

1. 🔢 **Update version** - Increments build number
2. 🔧 **Format & lint** - Runs `make fix`

### Setup

```bash
# Install hooks (one-time)
pre-commit install
```

Keep the configured hooks enabled; fix a failing check before publishing.

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

### Strict CI execution evidence

The `Test` job is one GitHub-hosted job with the Redis service and the
capacity-aware `pytest -n auto` worker selector; fork pull requests run there
too. It enforces the fixed 95% application coverage floor. This public repo has
no parallel shard route: the estate's shard planner (`estate-ci`) runs on
private runners only.

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
| ⚡ **Ruff** | Linting, formatting (120 chars), and import sorting |
| 🧪 **pytest** | Testing (100% coverage required) |
| 🔎 **mypy** | Static type checking |
| 📦 **uv** | Dependency + environment management |

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

### Service contracts

- The epguides CSV endpoint can return HTML with HTTP 200. Reject that body before CSV parsing and fall back to TVMaze when episode data is unavailable. Prefer a TVMaze ID recovered from the show page to a title search, which can select a different show. An IMDb reverse index avoids repeating that work for shows already seen.
- Redis holds raw episode dictionaries separately from the validated episode cache. A refresh invalidates both keys because the validated cache is rebuilt from the raw data.
- Swagger UI and ReDoc load CDN assets and initialize them with inline code. The middleware grants the relaxed content security policy only to those documentation routes.
- Upstream freshness is shared across workers. A successful fetch writes its timestamp without a TTL so an old value distinguishes stale data from a deployment that has never fetched it. Multiprocess metrics take the maximum timestamp across workers.
- The bounded Redis write/read probe distinguishes a live write path from a replica that answers PING. Redis problems can leave readiness degraded. The authoritative epguides source becomes unready when stale, with a startup grace period for an absent value. Read the top-level overall_ok field when monitoring readiness.
- The request observability configuration excludes bodies and stack-frame locals, since tool-call parameters and credentials can be present there. Recursive redaction covers sensitive fields nested in captured context.
- The LLM gateway retries once on connection problems, timeouts, HTTP 429, or server errors. Other client errors fall back immediately. Both JSON output forms are accepted for compatibility with gateways that ignore the response format hint.

### Build and tool constraints

- Build and runtime images use immutable base digests. The uv tool image uses the centrally synchronized exact version tag. Its runtime bytes are used to install locked dependencies in the builder. The dependency layer copies lock and project metadata before app code for cache reuse.
- The production image applies available Debian security patches after selecting the base digest. The development container uses a writable bind mount for reloads and transient Python files.
- The coverage runs isolate data per invocation because concurrent runs otherwise combine and remove the same coverage fragments. Ruff uses the resolved lockfile version locally and in CI. Host-run scripts must parse on Python 3.12, even though the application runtime is newer.
- A scan suppression needs an identified finding, a reason, and review. Use the lifetime required by the scan policy and remove the suppression when an upgrade fixes the finding. OSV uses the dependency lockfile and Trivy checks the file tree and built image separately. The local OSV wrapper only permits the recognized offline cases to skip the scan.
- Managed CI workflow blocks, public templates, and shared build helper copies are updated at their owning source. Preserve their provenance markers and the inline version annotations on pinned Actions.

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
# or: docker compose -f docker-compose.prod.yml -f docker-compose.build.yml build
#     docker compose -f docker-compose.prod.yml up -d
```

`docker-compose.prod.yml` names a prebuilt image,
`${IMAGE_REGISTRY}/apps/epguides/api:${IMAGE_TAG}` (defaults `localhost` and
`ci`, which is what `make up-prod` builds). A deployment sets both variables
and pulls the image built from that git SHA; it never builds on the host.
`docker-compose.build.yml` is the build recipe used by CI and `make build`.

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
docker build --build-arg OS_SECURITY_EPOCH=dev -t epguides-api .
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

<!-- merge-lane canary b -->
