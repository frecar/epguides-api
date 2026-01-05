# :material-cog: Configuration

Configure the Epguides API using environment variables.

!!! tip "Quick Setup"
    Copy `.env.example` to `.env` and customize for your environment.

---

## :material-format-list-bulleted: Environment Variables

### :material-database: Redis

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_HOST` | `redis` | Redis server hostname |
| `REDIS_PORT` | `6379` | Redis server port |
| `REDIS_DB` | `0` | Redis database number |
| `REDIS_PASSWORD` | - | Redis password (optional) |

### :material-cached: Cache

| Variable | Default | Description |
|----------|---------|-------------|
| `CACHE_TTL_SECONDS` | `604800` | Default cache TTL (7 days) |

### :material-api: API

| Variable | Default | Description |
|----------|---------|-------------|
| `API_BASE_URL` | `http://localhost:3000/` | Base URL for generated links |

### :material-robot: LLM (Optional)

| Variable | Required | Description |
|----------|:--------:|-------------|
| `LLM_ENABLED` | ⚪ | Set to `true` to enable NLQ |
| `LLM_API_URL` | If enabled | OpenAI-compatible API endpoint |
| `LLM_API_KEY` | If needed | API key for authentication |

### :material-text-box-outline: Logging

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Log level (DEBUG, INFO, WARNING, ERROR) |
| `LOG_REQUESTS` | `true` | Enable request logging |

---

## :material-file-document: Example `.env`

```bash
# 🗄️ Redis
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=

# ⏱️ Cache (7 days for ongoing shows)
CACHE_TTL_SECONDS=604800

# 🌐 API
API_BASE_URL=http://localhost:3000/

# 🤖 LLM (optional)
LLM_ENABLED=true
LLM_API_URL=https://api.openai.com/v1
LLM_API_KEY=sk-your-api-key

# 📝 Logging
LOG_LEVEL=INFO
LOG_REQUESTS=true
```

---

## :material-robot: LLM Provider Examples

!!! abstract "OpenAI-Compatible APIs"
    The LLM feature works with any OpenAI-compatible API.

=== ":material-openai: OpenAI"

    ```bash
    LLM_API_URL=https://api.openai.com/v1
    LLM_API_KEY=sk-...
    ```

=== ":material-microsoft-azure: Azure OpenAI"

    ```bash
    LLM_API_URL=https://your-resource.openai.azure.com/openai/deployments/your-deployment
    LLM_API_KEY=your-azure-key
    ```

=== ":material-llama: Ollama (Local)"

    ```bash
    LLM_API_URL=http://localhost:11434/v1
    LLM_API_KEY=  # Not required
    ```

=== ":material-server: Self-hosted"

    ```bash
    # vLLM, text-generation-inference, etc.
    LLM_API_URL=https://your-llm-server.com/v1
    LLM_API_KEY=your-key
    ```

---

## :material-lightning-bolt: Caching Strategy

!!! info "Smart Caching"
    The API uses intelligent caching to minimize external requests while keeping data fresh.

### :material-timer-sand: Cache Durations

| Data Type | Duration | Rationale |
|-----------|----------|-----------|
| :material-check-circle:{ .green } Finished shows | **1 year** | Data won't change |
| :material-format-list-bulleted: Shows master list | **30 days** | New shows added infrequently |
| :material-play-circle: Ongoing shows | **7 days** | Episodes air weekly at most |

### :material-chart-timeline-variant: Cache Flow

```
┌──────────────────────────────────────────────────────────┐
│                  📦 Cache Decision Flow                  │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  Request comes in                                        │
│       │                                                  │
│       ▼                                                  │
│  ┌─────────────┐  Yes   ┌─────────────┐                  │
│  │ ?refresh=   │───────▶│ Fetch fresh │                  │
│  │   true?     │        │    data     │                  │
│  └──────┬──────┘        └─────────────┘                  │
│         │ No                                             │
│         ▼                                                │
│  ┌─────────────┐  Yes   ┌─────────────┐                  │
│  │  In cache?  │───────▶│   Return    │                  │
│  │             │        │   cached    │                  │
│  └──────┬──────┘        └─────────────┘                  │
│         │ No                                             │
│         ▼                                                │
│  ┌─────────────┐                                         │
│  │ Fetch from  │                                         │
│  │  external   │                                         │
│  │    APIs     │                                         │
│  └──────┬──────┘                                         │
│         │                                                │
│         ▼                                                │
│  ┌─────────────┐  Yes                                    │
│  │  Show has   │───────▶ Cache for 1 year ✓              │
│  │  end_date?  │        (finished show)                  │
│  └──────┬──────┘                                         │
│         │ No                                             │
│         ▼                                                │
│  Cache for 7 days                                        │
│  (ongoing show)                                          │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### :material-auto-fix: Automatic Behaviors

| Feature | Behavior |
|---------|----------|
| :material-check-circle: **Finished Shows** | When `end_date` is set, cache extends to 1 year |
| :material-refresh: **Manual Refresh** | Use `?refresh=true` to bypass cache |
| :material-clock-fast: **Smart `/next`** | Auto-refreshes when cached episode date has passed |

---

## :material-check-decagram: Verification

### :material-heart-pulse: Check API Health

```bash
curl "https://epguides.frecar.no/health"
```

### :material-robot-outline: Check LLM Status

```bash
curl "https://epguides.frecar.no/health/llm"
```

Expected response when configured:

```json
{
  "enabled": true,
  "configured": true,
  "api_url": "https://api.openai.com/v1"
}
```
