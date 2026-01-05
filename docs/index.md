# Epguides API

<p align="center">
  <img src="https://img.shields.io/badge/📺-TV_Show_API-purple?style=for-the-badge" alt="TV Show API">
</p>

<p align="center">
  <strong>A high-performance REST API and MCP server for accessing TV show metadata and episode lists.</strong>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11-blue.svg" alt="Python 3.11"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.128-009688.svg" alt="FastAPI"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
  <a href="https://github.com/frecar/epguides-api"><img src="https://img.shields.io/github/stars/frecar/epguides-api?style=social" alt="GitHub Stars"></a>
</p>

<p align="center">
  <a href="https://epguides.frecar.no">🚀 Live API</a> · 
  <a href="https://epguides.frecar.no/docs">📖 Swagger</a> · 
  <a href="https://github.com/frecar/epguides-api">💻 GitHub</a>
</p>

---

!!! success "🎉 Public API Available"
    The API is **live and free to use** at **[epguides.frecar.no](https://epguides.frecar.no)**  
    No authentication required. Start building now!

---

## 🔗 Quick Links

| Resource | Description |
|----------|-------------|
| 🌐 [**Public API**](https://epguides.frecar.no) | Production endpoint |
| 📖 [**Swagger UI**](https://epguides.frecar.no/docs) | Interactive API explorer |
| 🤖 [**MCP Endpoint**](https://epguides.frecar.no/mcp) | For AI assistants |
| 💻 [**GitHub**](https://github.com/frecar/epguides-api) | Source code & issues |

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 📺 **Complete TV Database** | Metadata for thousands of TV shows |
| 🔍 **Smart Search** | AI-powered natural language queries |
| 📅 **Episode Tracking** | Next/latest episodes, season filters |
| 🤖 **MCP Server** | JSON-RPC for AI assistants |
| ⚡ **Smart Caching** | 7 days ongoing, 1 year finished |
| 📝 **Episode Summaries** | Plot descriptions via TVMaze |

---

## 🚀 Quick Start

Try the API right now - no setup required!

=== "curl"

    ```bash
    # 🔍 Search for shows
    curl "https://epguides.frecar.no/shows/search?query=breaking"
    
    # 📺 Get show details
    curl "https://epguides.frecar.no/shows/BreakingBad"
    
    # 📋 Get all episodes
    curl "https://epguides.frecar.no/shows/BreakingBad/episodes"
    
    # 🎯 Filter by season
    curl "https://epguides.frecar.no/shows/BreakingBad/episodes?season=5"
    ```

=== "Python"

    ```python
    import httpx

    async with httpx.AsyncClient() as client:
        # Search for shows
        response = await client.get(
            "https://epguides.frecar.no/shows/search",
            params={"query": "breaking"}
        )
        shows = response.json()
        
        # Get show details
        response = await client.get(
            "https://epguides.frecar.no/shows/BreakingBad"
        )
        show = response.json()
    ```

=== "JavaScript"

    ```javascript
    // Search for shows
    const response = await fetch(
      "https://epguides.frecar.no/shows/search?query=breaking"
    );
    const shows = await response.json();
    
    // Get show details
    const showResponse = await fetch(
      "https://epguides.frecar.no/shows/BreakingBad"
    );
    const show = await showResponse.json();
    ```

---

## 📊 Data Sources

!!! info "Aggregated from trusted sources"
    This API combines data from multiple sources to provide comprehensive TV show information.

| Source | Data Provided | 
|--------|---------------|
| 🌐 [epguides.com](http://epguides.com) | Show catalog, episode lists, air dates |
| 📡 [TVMaze API](https://api.tvmaze.com) | Episode summaries, plot descriptions |
| 🎬 [IMDB](https://imdb.com) | IMDB IDs for cross-referencing |

---

## 🏗️ Architecture

```
                        Epguides API
┌─────────────────────────────────────────────────────┐
│                                                     │
│  ┌───────────┐   ┌───────────┐   ┌───────────┐     │
│  │ REST API  │   │    MCP    │   │  Health   │     │
│  │ /shows/*  │   │   /mcp    │   │  /health  │     │
│  └─────┬─────┘   └─────┬─────┘   └───────────┘     │
│        │               │                           │
│        └───────┬───────┘                           │
│                ▼                                   │
│        ┌──────────────┐                            │
│        │Service Layer │                            │
│        └──────┬───────┘                            │
│               │                                    │
│       ┌───────┼───────┐                            │
│       ▼       ▼       ▼                            │
│   ┌───────┐ ┌─────┐ ┌───────┐                      │
│   │ Redis │ │ EPG │ │TVMaze │                      │
│   │ Cache │ │.com │ │  API  │                      │
│   └───────┘ └─────┘ └───────┘                      │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

## 📚 Documentation

| Guide | Description |
|-------|-------------|
| 🚀 [**Getting Started**](getting-started.md) | Installation and local setup |
| 📖 [**REST API**](rest-api.md) | Complete endpoint reference |
| 🤖 [**MCP Server**](mcp-server.md) | AI assistant integration |
| ⚙️ [**Configuration**](configuration.md) | Environment variables & caching |
| 💻 [**Development**](development.md) | Contributing & testing |

---

<p align="center">
  <strong>Ready to get started?</strong>
</p>

<p align="center">
  <a href="getting-started.md">🚀 Get Started</a> · 
  <a href="https://epguides.frecar.no/docs">📖 Try the API</a>
</p>
