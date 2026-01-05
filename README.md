# Epguides API

A high-performance REST API and MCP server for accessing TV show metadata and episode lists.

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.128-green.svg)](https://fastapi.tiangolo.com/)
[![Documentation](https://img.shields.io/badge/docs-ReadTheDocs-blue.svg)](https://epguides-api.readthedocs.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## 🔗 Links

| Resource | URL |
|----------|-----|
| **Public API** | https://epguides.frecar.no |
| **Interactive Docs (Swagger)** | https://epguides.frecar.no/docs |
| **Full Documentation** | https://epguides-api.readthedocs.io |
| **MCP Endpoint** | https://epguides.frecar.no/mcp |

## ✨ Features

- 📺 **Complete TV Database** - Metadata for thousands of TV shows
- 🔍 **Smart Search** - Natural language queries powered by LLM
- 📅 **Episode Tracking** - Next/latest episodes, filter by season/year
- 🤖 **MCP Server** - JSON-RPC interface for AI assistants
- ⚡ **Smart Caching** - 7-day cache for ongoing, 1-year for finished shows
- 📝 **Episode Summaries** - Plot descriptions via TVMaze

## 🚀 Quick Start

```bash
# Get show details
curl "https://epguides.frecar.no/shows/BreakingBad"

# Search shows
curl "https://epguides.frecar.no/shows/search?query=breaking"

# Get episodes
curl "https://epguides.frecar.no/shows/BreakingBad/episodes"

# Filter episodes
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?season=5"

# Natural language query (when LLM enabled)
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?nlq=finale+episodes"
```

## 📖 Documentation

For comprehensive documentation: **[epguides-api.readthedocs.io](https://epguides-api.readthedocs.io)**:

- [Getting Started](https://epguides-api.readthedocs.io/en/latest/getting-started/) - Installation & setup
- [REST API Reference](https://epguides-api.readthedocs.io/en/latest/rest-api/) - All endpoints & examples
- [MCP Server](https://epguides-api.readthedocs.io/en/latest/mcp-server/) - AI assistant integration
- [Configuration](https://epguides-api.readthedocs.io/en/latest/configuration/) - Environment variables & caching
- [Development](https://epguides-api.readthedocs.io/en/latest/development/) - Contributing & testing

## 🛠️ Local Development

```bash
# Clone and start
git clone https://github.com/frecar/epguides-api.git
cd epguides-api
make up

# Open local docs
open http://localhost:3000/docs
```

## 📊 Data Sources

| Source | Data Provided |
|--------|---------------|
| [epguides.com](http://epguides.com) | Show catalog, episode lists, air dates |
| [TVMaze API](https://api.tvmaze.com) | Episode summaries, plot descriptions |
| [IMDB](https://imdb.com) | IMDB IDs for cross-referencing |

## 🙏 Acknowledgments

- [epguides.com](http://epguides.com) for TV show and episode data
- [TVMaze](https://www.tvmaze.com/api) for episode summaries
- [FastAPI](https://fastapi.tiangolo.com/) for the excellent framework
