# ezWebSearch

ezWebSearch is an open-source, self-hostable Python service for searching the
web and returning clean, readable page content as JSON. It uses SearXNG for
search, HTTPX for fast page retrieval, Trafilatura for content extraction, and
Playwright with headless Chromium when JavaScript rendering is required.

## Features

- Search a SearXNG instance for candidate pages.
- Fetch ordinary pages quickly with HTTPX.
- Extract the main readable content and page metadata with Trafilatura.
- Fall back to Playwright for JavaScript-heavy pages.
- Continue through additional SearXNG result pages until the requested number
  of readable pages is reached or the retry budget is exhausted.
- Use the command line interface for one-off searches or FastAPI for a service.
- Block private and local result URLs by default to reduce SSRF risk.

## Quick start with Docker

Docker Compose is the easiest setup on a new machine. It starts both the
ezWebSearch API and a private SearXNG instance; no Python installation or
browser setup is required on the host.

```bash
git clone <repository-url> ezWebSearch
cd ezWebSearch
docker compose up --build
```

Then search from another terminal:

```bash
curl "http://127.0.0.1:3000/search?query=best%20local%20LLMs&links=5&retries=3"
```

The API is available at `http://127.0.0.1:3000`; interactive documentation is
at `http://127.0.0.1:3000/docs`. The SearXNG container is not published to the
host by default.

## How it works

```text
SearXNG -> HTTPX -> Trafilatura -> JSON
                       |
                       +-> Playwright + Chromium -> Trafilatura -> JSON
```

## Requirements and installation

- Python 3.10+
- Docker for the automatic local SearXNG backend, unless an external SearXNG
  URL is configured

For a native Python installation, the repository includes a bootstrap script:

```bash
./setup.sh
source .venv/bin/activate
```

This installs the server dependencies, the Chromium browser used for
JavaScript-heavy pages, and the `ezwebsearch` / `ezwebsearch-api` commands.
On Linux servers where Playwright OS packages are missing, install them with:

```bash
python -m playwright install --with-deps chromium
```

The native setup can use an existing SearXNG instance by copying the template
and setting `SEARXNG_URL`:

```bash
cp env.example .env
${EDITOR:-vi} .env
ezwebsearch-api
```

If `SEARXNG_URL` is left unset, CLI and API modes provision a temporary local
instance automatically. The default backend uses the installed SearXNG Python
module when present and Docker otherwise. Set `SEARXNG_BACKEND=docker` or
`SEARXNG_BACKEND=python` to choose explicitly.

## Python client library

The repository also ships a lightweight client library for applications that
want to call a running ezWebSearch API. Install it from this repository (or
from its published package when available):

```bash
pip install .
```

Use the synchronous client with a running API server:

```python
from ezwebsearch import EzWebSearchClient

with EzWebSearchClient("http://127.0.0.1:3000") as client:
    response = client.search("best local LLMs", links=5, retries=2)

for page in response["results"]:
    print(page["title"])
    print(page["text"])
```

An asynchronous client is available for async applications:

```python
from ezwebsearch import AsyncEzWebSearchClient

async with AsyncEzWebSearchClient("http://127.0.0.1:3000") as client:
    response = await client.search("best local LLMs")
```

Both clients provide `search()` and `health()` methods, return the API's JSON
objects as dictionaries, and raise `EzWebSearchHTTPError` for non-success HTTP
responses. The client package only requires `httpx`; server dependencies remain
available through the optional `server` extra:

```bash
pip install ".[server]"
```

## Configure SearXNG

Docker Compose already supplies a SearXNG configuration with JSON output
enabled. For an externally managed instance, add JSON to its `settings.yml`:

```yaml
search:
  formats:
    - html
    - json
```

The same configuration is available in
[`searxng-settings-snippet.yml`](searxng-settings-snippet.yml).

Copy the environment template when configuring an external instance or the
local server:

```bash
cp env.example .env
# Set this only when SearXNG is managed separately, for example:
# SEARXNG_URL=http://127.0.0.1:8080
```

The application loads `.env` automatically. Process environment variables take
precedence.

## CLI usage

Run a single search. If no SearXNG URL is supplied, ezWebSearch provisions a
temporary local SearXNG server, waits for it to become ready, and shuts it down
when the query finishes.

```bash
ezwebsearch "best local LLMs" --links 5 --retries 3
```

Use an existing SearXNG instance instead:

```bash
ezwebsearch \
  --query "best local LLMs" \
  --links 5 \
  --retries 3 \
  --searxng-url http://127.0.0.1:8080
```

Save the returned JSON:

```bash
ezwebsearch \
  "best local LLMs" \
  --links 5 \
  --retries 3 \
  --output result.json
```

CLI exit codes:

- `0`: the requested number of pages was returned
- `1`: fatal execution error
- `2`: invalid or missing CLI arguments
- `3`: the search completed, but fewer than the requested number of pages
  could be extracted

## API usage

Start the API:

```bash
ezwebsearch-api
```

Or use Uvicorn directly:

```bash
uvicorn api:app --host 0.0.0.0 --port 3000
```

Search and check health:

```bash
curl "http://127.0.0.1:3000/search?query=best%20local%20LLMs&links=5&retries=3"
curl http://127.0.0.1:3000/health
```

Interactive FastAPI documentation is available at
`http://127.0.0.1:3000/docs`.

## Parameters

The API and CLI use the same three main parameters:

- `query`: the search query.
- `links`: the number of successfully extracted pages requested.
- `retries`: the number of additional SearXNG result pages to try if the
  requested number of pages has not been reached.

For example, `retries=3` permits SearXNG pages 1, 2, 3, and 4 to be searched if
needed.

## Example response

```json
{
  "query": "best local LLMs",
  "requested_links": 2,
  "returned_links": 2,
  "missing_links": 0,
  "complete": true,
  "retries_allowed": 2,
  "search_pages_used": 1,
  "results": [
    {
      "url": "https://example.com/article",
      "search_title": "Example result",
      "search_snippet": "Search engine snippet",
      "rendered": false,
      "extraction_method": "http",
      "title": "Example Article",
      "author": "Example Author",
      "date": "2026-08-12",
      "hostname": "example.com",
      "description": "Example description",
      "sitename": "Example",
      "language": "en",
      "text": "Clean main page text...",
      "characters": 18320,
      "rank": 1
    }
  ],
  "failures": []
}
```

JavaScript-rendered results contain:

```json
{
  "rendered": true,
  "extraction_method": "playwright"
}
```

## Safety

By default, result URLs are blocked if they resolve to local, private,
loopback, link-local, multicast, reserved, or otherwise non-public IP
addresses. This reduces SSRF risk when the API is exposed to other users.

Enable private URL retrieval only when it is explicitly needed:

```bash
export ALLOW_PRIVATE_URLS=true
```

Do not enable it on a public-facing API unless you understand the SSRF
implications.

## Development

Run the test suite with:

```bash
python3 -m unittest discover -v
```

The project also includes [`SKILL.md`](SKILL.md), which documents how an AI
agent can use ezWebSearch as a web-retrieval skill.

## Contributing

Contributions are welcome. Before opening a pull request:

1. Keep changes focused and explain the user-facing behavior they affect.
2. Run the test suite locally.
3. Update the README or `SKILL.md` when interfaces or workflows change.
4. Avoid weakening the default URL safety checks without documenting the risk.

Please report bugs and security issues privately when they could expose
internal or private network resources.

## License

ezWebSearch is released under the [MIT License](LICENSE).
