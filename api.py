from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from search_service import SearchService


service = SearchService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await service.start()
    try:
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "3000")),
        reload=False,
    )
