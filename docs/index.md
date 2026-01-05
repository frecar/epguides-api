# Epguides API

A high-performance REST API and MCP server for accessing TV show metadata and episode lists.

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-green.svg)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Public API**: [https://epguides.frecar.no](https://epguides.frecar.no)  
**Interactive Docs**: [https://epguides.frecar.no/docs](https://epguides.frecar.no/docs)

## Features

- 📺 **Complete TV Database** - Access metadata for thousands of TV shows
- 🔍 **Smart Search** - Search by title with natural language queries (LLM-powered)
- 📅 **Episode Tracking** - Get next/latest episodes, filter by season/year
- 🤖 **MCP Support** - JSON-RPC interface for AI assistants
- ⚡ **Intelligent Caching** - 7-day cache for ongoing shows, 1-year for finished shows
- 📝 **Episode Summaries** - Plot descriptions via TVMaze integration

## Data Sources

This API aggregates data from multiple sources:

| Source | Data Provided | Used For |
|--------|--------------|----------|
| [epguides.com](http://epguides.com) | Show catalog, episode lists, air dates | Core show and episode data |
| [TVMaze API](https://api.tvmaze.com) | Episode summaries, plot descriptions | AI-powered search (NLQ), enhanced episode info |
| [IMDB](https://imdb.com) | IMDB IDs | Cross-referencing with IMDB |
| User-configured LLM (optional) | AI filtering | Natural language episode queries |

## Quick Start

```bash
# Using the public API
curl "https://epguides.frecar.no/shows/BreakingBad"

# Search for shows
curl "https://epguides.frecar.no/shows/search?query=breaking"

# Get episodes
curl "https://epguides.frecar.no/shows/BreakingBad/episodes"
```

See [Getting Started](getting-started.md) for local development setup.

