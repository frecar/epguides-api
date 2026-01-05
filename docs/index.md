# Epguides API

<p align="center">
  <strong>Free REST API for TV show data, episode lists, and air dates</strong>
</p>

<p align="center">
  <a href="https://epguides.frecar.no/shows"><img src="https://img.shields.io/badge/🚀_Try_the_API-epguides.frecar.no-blue?style=for-the-badge" alt="Try the API"></a>
  <a href="https://epguides.frecar.no/docs"><img src="https://img.shields.io/badge/📖_Swagger-Interactive_Docs-green?style=for-the-badge" alt="Swagger"></a>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11-blue.svg" alt="Python 3.11"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.128-009688.svg" alt="FastAPI"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
  <a href="https://github.com/frecar/epguides-api"><img src="https://img.shields.io/github/stars/frecar/epguides-api?style=social" alt="GitHub Stars"></a>
</p>

---

A high-performance **TV show API** providing access to metadata for thousands of television series. Get episode lists, air dates, plot summaries, and more. Perfect for building TV tracking apps, media centers, or AI assistants.

!!! success "No API key required"
    The public API is **free to use** with no authentication needed. Start making requests immediately!

---

## ✨ What You Can Do

| Feature | Description |
|---------|-------------|
| 📺 **Browse TV Shows** | Access metadata for thousands of TV series |
| 🔍 **Search Shows** | Find shows by title with instant results |
| 📅 **Get Episode Lists** | Full episode data with air dates and summaries |
| ⏭️ **Track New Episodes** | Get next/upcoming episode for any show |
| 🤖 **AI-Powered Search** | Natural language queries like "finale episodes" |
| 🔌 **MCP for AI Assistants** | JSON-RPC endpoint for Claude, ChatGPT, etc. |

---

## 🚀 Quick Start

```bash
# Search for TV shows
curl "https://epguides.frecar.no/shows/search?query=breaking+bad"

# Get show details
curl "https://epguides.frecar.no/shows/BreakingBad"

# Get all episodes
curl "https://epguides.frecar.no/shows/BreakingBad/episodes"

# Filter by season
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?season=5"

# Get next upcoming episode
curl "https://epguides.frecar.no/shows/Severance/episodes/next"
```

??? example "Python Example"
    ```python
    import httpx

    async with httpx.AsyncClient() as client:
        # Search for shows
        response = await client.get(
            "https://epguides.frecar.no/shows/search",
            params={"query": "breaking bad"}
        )
        shows = response.json()
        
        # Get episodes
        response = await client.get(
            "https://epguides.frecar.no/shows/BreakingBad/episodes"
        )
        episodes = response.json()
    ```

??? example "JavaScript Example"
    ```javascript
    // Search for shows
    const response = await fetch(
      "https://epguides.frecar.no/shows/search?query=breaking+bad"
    );
    const shows = await response.json();
    
    // Get episodes
    const episodesResponse = await fetch(
      "https://epguides.frecar.no/shows/BreakingBad/episodes"
    );
    const episodes = await episodesResponse.json();
    ```

---

## 📊 Data Provided

| Data | Source | Description |
|------|--------|-------------|
| **Shows** | [epguides.com](http://epguides.com) | Title, network, country, start/end dates |
| **Episodes** | [epguides.com](http://epguides.com) | Season, episode number, title, air date |
| **Summaries** | [TVMaze](https://api.tvmaze.com) | Plot descriptions for episodes |
| **IMDB IDs** | [IMDB](https://imdb.com) | Cross-reference with IMDB |

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

## 📚 Documentation

| Guide | Description |
|-------|-------------|
| **[Getting Started](getting-started.md)** | Quick setup for using the API |
| **[REST API Reference](rest-api.md)** | All endpoints with examples |
| **[MCP Server](mcp-server.md)** | AI assistant integration |
| **[Configuration](configuration.md)** | Environment variables & caching |
| **[Development](development.md)** | Contributing & self-hosting |
