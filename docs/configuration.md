# ⚙️ Configuration

Configure the Epguides API using environment variables.

!!! tip "Quick Setup"
    Copy `.env.example` to `.env` and customize for your environment.

---

## 📋 Environment Variables

### 🗄️ Redis

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_HOST` | `redis` | Redis server hostname |
| `REDIS_PORT` | `6379` | Redis server port |
| `REDIS_DB` | `0` | Redis database number |
| `REDIS_PASSWORD` | - | Redis password (optional) |
| `REDIS_MAX_CONNECTIONS` | `100` | Max pool connections (~10 per worker) |

### ⏱️ Cache

| Variable | Default | Description |
|----------|---------|-------------|
| `CACHE_TTL_SECONDS` | `604800` | Default cache TTL (7 days) |

### 🌐 API

| Variable | Default | Description |
|----------|---------|-------------|
| `API_BASE_URL` | `http://localhost:3000/` | Base URL for generated links |

### 🤖 LLM (Optional)

| Variable | Required | Description |
|----------|:--------:|-------------|
| `LLM_ENABLED` | ⚪ | Set to `true` to enable NLQ |
| `LLM_API_URL` | If enabled | OpenAI-compatible API endpoint |
| `LLM_API_KEY` | If needed | API key for authentication |

### 📝 Logging

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Log level (DEBUG, INFO, WARNING, ERROR) |
| `LOG_REQUESTS` | `true` | Enable request logging |

---

## 📄 Example `.env`

=== "Development"

    ```bash
    # Redis (local Docker)
    REDIS_HOST=redis
    REDIS_PORT=6379
    REDIS_PASSWORD=

    # API
    API_BASE_URL=http://localhost:3000/

    # Logging (verbose for debugging)
    LOG_LEVEL=DEBUG
    LOG_REQUESTS=true
    ```

=== "Production"

    ```bash
    # Redis (production)
    REDIS_HOST=redis
    REDIS_PORT=6379
    REDIS_PASSWORD=your-secure-password
    REDIS_MAX_CONNECTIONS=100

    # API
    API_BASE_URL=https://your-domain.com/

    # LLM (optional)
    LLM_ENABLED=true
    LLM_API_URL=https://api.openai.com/v1
    LLM_API_KEY=sk-your-api-key

    # Logging (less verbose)
    LOG_LEVEL=WARNING
    LOG_REQUESTS=false
    ```

---

## 🤖 LLM Provider Examples

!!! abstract "OpenAI-Compatible APIs"
    The LLM feature works with any OpenAI-compatible API.

=== "OpenAI"

    ```bash
    LLM_API_URL=https://api.openai.com/v1
    LLM_API_KEY=sk-...
    ```

=== "Azure OpenAI"

    ```bash
    LLM_API_URL=https://your-resource.openai.azure.com/openai/deployments/your-deployment
    LLM_API_KEY=your-azure-key
    ```

=== "Ollama (Local)"

    ```bash
    LLM_API_URL=http://localhost:11434/v1
    LLM_API_KEY=  # Not required
    ```

=== "Self-hosted"

    ```bash
    # vLLM, text-generation-inference, etc.
    LLM_API_URL=https://your-llm-server.com/v1
    LLM_API_KEY=your-key
    ```

---

## ⚡ Caching Strategy

!!! info "Smart Caching"
    The API uses intelligent caching to minimize external requests while keeping data fresh.

### ⏰ Cache Durations

| Data Type | Duration | Rationale |
|-----------|----------|-----------|
| ✅ Finished shows | **1 year** | Data won't change |
| 📋 Shows master list | **30 days** | New shows added infrequently |
| ▶️ Ongoing shows | **7 days** | Episodes air weekly at most |

### 📊 Cache Flow

```
Request comes in
      │
      ▼
┌─────────┐  Yes   ┌─────────────┐
│refresh= │───────▶│ Fetch fresh │
│  true?  │        │    data     │
└────┬────┘        └─────────────┘
     │ No
     ▼
┌─────────┐  Yes   ┌─────────────┐
│In cache?│───────▶│Return cached│
└────┬────┘        └─────────────┘
     │ No
     ▼
┌───────────┐
│Fetch from │
│external   │
│APIs       │
└─────┬─────┘
      │
      ▼
┌──────────┐  Yes
│Show has  │──────▶ Cache 1 year (finished)
│end_date? │
└────┬─────┘
     │ No
     ▼
Cache 7 days (ongoing)
```

### 🔄 Automatic Behaviors

| Feature | Behavior |
|---------|----------|
| ✅ **Finished Shows** | When `end_date` is set, cache extends to 1 year |
| 🔄 **Manual Refresh** | Use `?refresh=true` to bypass cache |
| ⏰ **Smart `/next`** | Auto-refreshes when cached episode date has passed |

---

## ✅ Verification

### 💚 Check API Health

```bash
curl "https://epguides.frecar.no/health"
```

### 🤖 Check LLM Status

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
