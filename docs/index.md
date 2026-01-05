# Epguides API

<p align="center">
  <strong>REST API and MCP server for TV show and episode metadata</strong>
</p>

<p align="center">
  <a href="https://epguides.frecar.no"><img src="https://img.shields.io/badge/🚀_Live_API-epguides.frecar.no-blue?style=for-the-badge" alt="Live API"></a>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11-blue.svg" alt="Python 3.11"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.128-009688.svg" alt="FastAPI"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
  <a href="https://github.com/frecar/epguides-api"><img src="https://img.shields.io/github/stars/frecar/epguides-api?style=social" alt="GitHub Stars"></a>
</p>

---

## ✨ Features

| | |
|---|---|
| 📺 **TV Database** | Metadata for thousands of shows |
| 🔍 **Smart Search** | AI-powered natural language queries |
| 📅 **Episode Tracking** | Next/latest episodes, filters |
| 🤖 **MCP Server** | JSON-RPC for AI assistants |
| ⚡ **Smart Caching** | 7d ongoing / 1yr finished |
| 📝 **Summaries** | Plot descriptions via TVMaze |

---

## 🚀 Quick Start

```bash
# Search for shows
curl "https://epguides.frecar.no/shows/search?query=breaking"

# Get show details
curl "https://epguides.frecar.no/shows/BreakingBad"

# Get episodes
curl "https://epguides.frecar.no/shows/BreakingBad/episodes"
```

??? example "Python"
    ```python
    import httpx

    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://epguides.frecar.no/shows/search",
            params={"query": "breaking"}
        )
        shows = response.json()
    ```

??? example "JavaScript"
    ```javascript
    const response = await fetch(
      "https://epguides.frecar.no/shows/search?query=breaking"
    );
    const shows = await response.json();
    ```

---

## 📊 Data Sources

| Source | Data |
|--------|------|
| [epguides.com](http://epguides.com) | Shows, episodes, air dates |
| [TVMaze](https://api.tvmaze.com) | Episode summaries |
| [IMDB](https://imdb.com) | IMDB IDs |

---

## 🏗️ Architecture

```
┌───────────┐   ┌───────────┐   ┌───────────┐
│ REST API  │   │    MCP    │   │  Health   │
│ /shows/*  │   │   /mcp    │   │  /health  │
└─────┬─────┘   └─────┬─────┘   └───────────┘
      │               │
      └───────┬───────┘
              ▼
      ┌──────────────┐
      │Service Layer │
      └──────┬───────┘
             │
     ┌───────┼───────┐
     ▼       ▼       ▼
┌───────┐ ┌─────┐ ┌───────┐
│ Redis │ │ EPG │ │TVMaze │
│ Cache │ │.com │ │  API  │
└───────┘ └─────┘ └───────┘
```

---

## 📚 Next Steps

- **[Getting Started](getting-started.md)** — Local setup
- **[REST API](rest-api.md)** — Endpoint reference  
- **[MCP Server](mcp-server.md)** — AI integration
- **[Configuration](configuration.md)** — Environment & caching
