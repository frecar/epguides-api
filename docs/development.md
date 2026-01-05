# Development

## Commands

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

## Pre-commit Hooks

The project includes pre-commit hooks that automatically:

1. **Update version number** - Increments the build number in `VERSION` file
2. **Format and lint code** - Runs `make fix`

### Setup

```bash
pre-commit install
```

### Skip (not recommended)

```bash
git commit --no-verify
```

## Versioning

The API version is a simple incrementing build number based on git commit count.

- The `VERSION` file contains the current build number
- Pre-commit hook automatically updates it on each commit
- No manual version management needed

Check current version:

```bash
cat VERSION
# or
curl http://localhost:3000/health
```

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
```

## Code Quality

The project uses:

- **Black** - Code formatting (120 char line length)
- **isort** - Import sorting
- **Ruff** - Fast linting
- **pytest** - Testing

All checks run automatically via `make fix` and pre-commit hooks.

## Production Deployment

```bash
# Build image
docker build -t epguides-api .

# Run container
docker run -d -p 3000:3000 \
  -e REDIS_HOST=your-redis \
  -e REDIS_PORT=6379 \
  epguides-api
```

The Dockerfile includes:

- Non-root user for security
- Health check for container orchestration
- Optimized layer caching

