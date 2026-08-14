FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Copy packaging metadata first so Docker can reuse the dependency layer when
# application code changes.
COPY pyproject.toml README.md LICENSE ./
COPY ezwebsearch ./ezwebsearch
COPY api.py cli.py config.py local_searxng.py runtime.py search_service.py ./

RUN python -m pip install --upgrade pip \
    && python -m pip install ".[server]" \
    && python -m playwright install --with-deps chromium

EXPOSE 3000

CMD ["ezwebsearch-api"]
