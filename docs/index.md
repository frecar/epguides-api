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
  <a href="https://epguides.frecar.no">:material-rocket-launch: Live API</a> · 
  <a href="https://epguides.frecar.no/docs">:material-file-document: Swagger</a> · 
  <a href="https://github.com/frecar/epguides-api">:material-github: GitHub</a>
</p>

---

!!! success "🎉 Public API Available"
    The API is **live and free to use** at **[epguides.frecar.no](https://epguides.frecar.no)**  
    No authentication required. Start building now!

---

## :material-link-variant: Quick Links

| | Resource | Description |
|---|----------|-------------|
| :material-api: | [**Public API**](https://epguides.frecar.no) | Production endpoint |
| :material-file-document-outline: | [**Swagger UI**](https://epguides.frecar.no/docs) | Interactive API explorer |
| :material-robot: | [**MCP Endpoint**](https://epguides.frecar.no/mcp) | For AI assistants |
| :material-github: | [**GitHub**](https://github.com/frecar/epguides-api) | Source code & issues |

---

## :material-star-shooting: Features

| | Feature | Description |
|---|---------|-------------|
| :material-television: | **Complete TV Database** | Metadata for thousands of TV shows |
| :material-magnify: | **Smart Search** | AI-powered natural language queries |
| :material-calendar-clock: | **Episode Tracking** | Next/latest episodes, season filters |
| :material-robot-outline: | **MCP Server** | JSON-RPC for AI assistants |
| :material-lightning-bolt: | **Smart Caching** | 7 days ongoing, 1 year finished |
| :material-text-box-outline: | **Episode Summaries** | Plot descriptions via TVMaze |

---

## :material-rocket-launch: Quick Start

Try the API right now - no setup required!

=== ":material-console: curl"

    ```bash
    # 🔍 Search for shows
    curl "https://epguides.frecar.no/shows/search?query=breaking"
    
    # 📺 Get show details
    curl "https://epguides.frecar.no/shows/BreakingBad"
    
    # 📋 Get all episodes
    curl "https://epguides.frecar.no/shows/BreakingBad/episodes"
    
    # 🎯 Filter by season
    curl "https://epguides.frecar.no/shows/BreakingBad/episodes?season=5"
    
    # 🤖 Natural language query (when LLM enabled)
    curl "https://epguides.frecar.no/shows/BreakingBad/episodes?nlq=finale+episodes"
    ```

=== ":material-language-python: Python"

    ```python
    import httpx

    async with httpx.AsyncClient() as client:
        # 🔍 Search for shows
        response = await client.get(
            "https://epguides.frecar.no/shows/search",
            params={"query": "breaking"}
        )
        shows = response.json()
        
        # 📺 Get show details
        response = await client.get(
            "https://epguides.frecar.no/shows/BreakingBad"
        )
        show = response.json()
        print(f"Found: {show['title']} ({show['total_episodes']} episodes)")
        
        # 📋 Get episodes
        response = await client.get(show['api_episodes_url'])
        episodes = response.json()
    ```

=== ":material-language-javascript: JavaScript"

    ```javascript
    // 🔍 Search for shows
    const searchResponse = await fetch(
      "https://epguides.frecar.no/shows/search?query=breaking"
    );
    const shows = await searchResponse.json();
    
    // 📺 Get show details
    const showResponse = await fetch(
      "https://epguides.frecar.no/shows/BreakingBad"
    );
    const show = await showResponse.json();
    console.log(`Found: ${show.title} (${show.total_episodes} episodes)`);
    
    // 📋 Get episodes
    const episodesResponse = await fetch(show.api_episodes_url);
    const episodes = await episodesResponse.json();
    ```

---

## :material-database: Data Sources

!!! info "Aggregated from trusted sources"
    This API combines data from multiple sources to provide comprehensive TV show information.

| Source | Data Provided | 
|--------|---------------|
| :material-web: [epguides.com](http://epguides.com) | Show catalog, episode lists, air dates |
| :material-api: [TVMaze API](https://api.tvmaze.com) | Episode summaries, plot descriptions |
| :material-movie-open: [IMDB](https://imdb.com) | IMDB IDs for cross-referencing |

---

## :material-chart-box: Architecture

```
┌──────────────────────────────────────────────────┐
│                 🎬 Epguides API                  │
├──────────────────────────────────────────────────┤
│                                                  │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│   │ REST API │  │   MCP    │  │  Health  │      │
│   │ /shows/* │  │   /mcp   │  │ /health  │      │
│   └────┬─────┘  └────┬─────┘  └──────────┘      │
│        │             │                          │
│        └──────┬──────┘                          │
│               │                                 │
│               ▼                                 │
│        ┌─────────────┐                          │
│        │Service Layer│                          │
│        └──────┬──────┘                          │
│               │                                 │
│      ┌────────┼────────┐                        │
│      │        │        │                        │
│      ▼        ▼        ▼                        │
│   ┌─────┐ ┌────────┐ ┌───────┐                  │
│   │Redis│ │epguides│ │TVMaze │                  │
│   │Cache│ │  .com  │ │  API  │                  │
│   └─────┘ └────────┘ └───────┘                  │
│                                                  │
└──────────────────────────────────────────────────┘
```

---

## :material-book-open-variant: Documentation

| | Guide | Description |
|---|-------|-------------|
| :material-rocket-launch: | [**Getting Started**](getting-started.md) | Installation and local setup |
| :material-api: | [**REST API**](rest-api.md) | Complete endpoint reference |
| :material-robot: | [**MCP Server**](mcp-server.md) | AI assistant integration |
| :material-cog: | [**Configuration**](configuration.md) | Environment variables & caching |
| :material-code-braces: | [**Development**](development.md) | Contributing & testing |

---

<p align="center">
  <strong>Ready to get started?</strong>
</p>

<p align="center">
  <a href="getting-started.md" class="md-button md-button--primary">:material-rocket-launch: Get Started</a>
  <a href="https://epguides.frecar.no/docs" class="md-button">:material-api: Try the API</a>
</p>
