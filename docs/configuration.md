# Configuration

Configuration is loaded from environment variables. Create a `.env` file for local development.

## Environment Variables

### Redis

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_HOST` | `redis` | Redis server hostname |
| `REDIS_PORT` | `6379` | Redis server port |
| `REDIS_DB` | `0` | Redis database number |
| `REDIS_PASSWORD` | (none) | Redis password |

### Cache

| Variable | Default | Description |
|----------|---------|-------------|
| `CACHE_TTL_SECONDS` | `604800` | Default cache TTL (7 days) |

### API

| Variable | Default | Description |
|----------|---------|-------------|
| `API_BASE_URL` | `http://localhost:3000/` | Base URL for generated links |

### LLM (Optional)

| Variable | Required | Description |
|----------|----------|-------------|
| `LLM_ENABLED` | No | Set to `true` to enable NLQ |
| `LLM_API_URL` | If enabled | OpenAI-compatible API endpoint |
| `LLM_API_KEY` | If required | API key for authentication |

### Logging

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Log level |
| `LOG_REQUESTS` | `true` | Log HTTP requests |

## Example `.env`

```bash
# Redis
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=

# Cache (7 days for ongoing shows)
CACHE_TTL_SECONDS=604800

# API
API_BASE_URL=http://localhost:3000/

# LLM (optional)
LLM_ENABLED=true
LLM_API_URL=https://api.openai.com/v1
LLM_API_KEY=sk-your-api-key

# Logging
LOG_LEVEL=INFO
LOG_REQUESTS=true
```

## LLM Provider Examples

### OpenAI

```bash
LLM_API_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
```

### Azure OpenAI

```bash
LLM_API_URL=https://your-resource.openai.azure.com/openai/deployments/your-deployment
LLM_API_KEY=your-azure-key
```

### Local Ollama

```bash
LLM_API_URL=http://localhost:11434/v1
LLM_API_KEY=  # Not required
```

### Self-hosted (vLLM, etc.)

```bash
LLM_API_URL=https://your-llm-server.com/v1
LLM_API_KEY=your-key
```

## Caching Strategy

Smart caching minimizes external API calls:

| Data Type | Cache Duration | Notes |
|-----------|----------------|-------|
| Finished shows | 1 year | Data won't change |
| Shows master list | 30 days | New shows added infrequently |
| Ongoing show episodes | 7 days | Episodes air weekly at most |

**Finished Show Detection**: When a show has an `end_date`, caches are automatically extended to 1 year.

**Cache Refresh**: Use `?refresh=true` on endpoints to bypass cache.

**Smart `/next` Endpoint**: Automatically refreshes if the cached "next" episode date has passed.

