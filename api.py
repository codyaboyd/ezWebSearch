from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from config import Settings
from search_service import SearchService


service = SearchService(Settings.from_env())


@asynccontextmanager
async def lifespan(app: FastAPI):
    configured = Settings.from_env()
    # Refresh the URL at lifespan time so process managers and tests that set
    # environment variables after importing this module behave predictably.
    service.settings.searxng_url = configured.searxng_url

    try:
        await service.start()
        yield
    finally:
        await service.close()


app = FastAPI(
    title="ezWebSearch",
    version="1.0.0",
    description=(
        "Search with SearXNG, retrieve result pages, render JavaScript-heavy "
        "sites with Playwright when needed, extract clean main content with "
        "Trafilatura, and return JSON."
    ),
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/search")
async def search(
    query: str = Query(..., min_length=1, description="Search query"),
    links: int = Query(
        5,
        ge=1,
        le=25,
        description="Number of successfully extracted result pages required",
    ),
    retries: int = Query(
        2,
        ge=0,
        le=10,
        description=(
            "Number of additional SearXNG result pages to try if fewer than "
            "the requested number of pages can be extracted"
        ),
    ),
):
    try:
        return await service.search(query=query, links=links, retries=retries)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def main() -> None:
    import uvicorn

    uvicorn.run(
        "api:app",
        host=Settings.from_env().host,
        port=Settings.from_env().port,
        reload=False,
    )


if __name__ == "__main__":
    main()
