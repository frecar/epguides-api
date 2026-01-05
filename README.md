# Epguides API

Free REST API for TV show data, episode lists, air dates, and plot summaries. Also includes an MCP server for AI assistant integration.

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.128-green.svg)](https://fastapi.tiangolo.com/)
[![Documentation](https://img.shields.io/badge/docs-ReadTheDocs-blue.svg)](https://epguides-api.readthedocs.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## 🔗 Links

| Resource | URL |
|----------|-----|
| **Public API** | https://epguides.frecar.no |
| **Swagger UI** | https://epguides.frecar.no/docs |
| **Full Documentation** | https://epguides-api.readthedocs.io |
| **MCP Endpoint** | https://epguides.frecar.no/mcp |

## ✨ Features

- 📺 **TV Show Database** — Metadata for thousands of TV series
- 🔍 **Search** — Find shows by title
- 📅 **Episode Data** — Full episode lists with air dates
- 📝 **Plot Summaries** — Episode descriptions via TVMaze
- ⏭️ **Episode Tracking** — Get next/latest episodes
- 🤖 **AI Search** — Natural language queries (LLM-powered)
- 🔌 **MCP Server** — JSON-RPC for AI assistants

## 🚀 Quick Start

No API key needed. Just start making requests:

```bash
# Search for shows
curl "https://epguides.frecar.no/shows/search?query=breaking+bad"

# Get show details
curl "https://epguides.frecar.no/shows/BreakingBad"

# Get episodes
curl "https://epguides.frecar.no/shows/BreakingBad/episodes"

# Filter by season
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?season=5"

# Get next episode
curl "https://epguides.frecar.no/shows/Severance/episodes/next"
```

## 📖 Documentation

Full documentation at **[epguides-api.readthedocs.io](https://epguides-api.readthedocs.io)**:

- [Getting Started](https://epguides-api.readthedocs.io/en/latest/getting-started/)
- [REST API Reference](https://epguides-api.readthedocs.io/en/latest/rest-api/)
- [MCP Server](https://epguides-api.readthedocs.io/en/latest/mcp-server/)
- [Configuration](https://epguides-api.readthedocs.io/en/latest/configuration/)
- [Development](https://epguides-api.readthedocs.io/en/latest/development/)

## 🛠️ Self-Hosting

```bash
git clone https://github.com/frecar/epguides-api.git
cd epguides-api
make up

# API running at http://localhost:3000
```

## 📊 Data Sources

| Source | Data |
|--------|------|
| [epguides.com](http://epguides.com) | Show catalog, episode lists, air dates |
| [TVMaze](https://api.tvmaze.com) | Episode summaries |
| [IMDB](https://imdb.com) | IMDB IDs |

## 📄 License

MIT — see [LICENSE](https://opensource.org/licenses/MIT)
