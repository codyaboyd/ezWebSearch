from __future__ import annotations

import asyncio
import importlib.util
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

import httpx


_SEARXNG_IMPORT_LOCK = threading.Lock()


class LocalSearXNG:
    """Provision and run a temporary local SearXNG instance.

    ``auto`` uses the in-process server when SearXNG is installed in the
    current Python environment and otherwise uses the official Docker image.
    """

    DEFAULT_HOST = "127.0.0.1"
    DOCKER_HOST = "0.0.0.0"
    DOCKER_PORT = 8080
    DEFAULT_DOCKER_IMAGE = "docker.io/searxng/searxng:latest"
    DEFAULT_STARTUP_TIMEOUT_SECONDS = 120.0

    def __init__(
        self,
        *,
        startup_timeout_seconds: float | None = None,
        backend: str | None = None,
        docker_image: str | None = None,
    ) -> None:
        self.startup_timeout_seconds = (
            startup_timeout_seconds
            if startup_timeout_seconds is not None
            else float(
                os.getenv(
                    "SEARXNG_STARTUP_TIMEOUT_SECONDS",
                    str(self.DEFAULT_STARTUP_TIMEOUT_SECONDS),
                )
            )
        )
        self.backend = (
            backend or os.getenv("SEARXNG_BACKEND", "auto")
        ).strip().lower()
        self.docker_image = (
            docker_image
            or os.getenv("SEARXNG_DOCKER_IMAGE", self.DEFAULT_DOCKER_IMAGE)
        ).strip()
        self.url: str | None = None
        self._config_dir: Path | None = None
        self._server: Any | None = None
        self._thread: threading.Thread | None = None
        self._thread_error: BaseException | None = None
        self._container_id: str | None = None
        self._container_name: str | None = None
        self._stop_requested = threading.Event()

    @staticmethod
    def _find_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((LocalSearXNG.DEFAULT_HOST, 0))
            return int(sock.getsockname()[1])

    def _write_settings(self, port: int, host: str = DEFAULT_HOST) -> Path:
        config_dir = Path(tempfile.mkdtemp(prefix="ezwebsearch-"))
        self._config_dir = config_dir

        settings = config_dir / "settings.yml"
        settings.write_text(
            """
use_default_settings: true

general:
  instance_name: "Temporary SearXNG for ezWebSearch"

search:
  formats:
    - html
    - json

server:
  secret_key: "{secret_key}"
  bind_address: "{host}"
  port: {port}
  limiter: false
""".format(
                secret_key=secrets.token_hex(32),
                host=host,
                port=port,
            ),
            encoding="utf-8",
        )
        settings.chmod(0o644)
        return settings

    def _selected_backend(self) -> str:
        if self.backend not in {"auto", "docker", "python"}:
            raise RuntimeError(
                "SEARXNG_BACKEND must be one of: auto, docker, python"
            )

        if self.backend != "auto":
            return self.backend

        try:
            has_python_searxng = importlib.util.find_spec("searx") is not None
        except (ImportError, ValueError):
            has_python_searxng = False

        return "python" if has_python_searxng else "docker"

    @staticmethod
    def _docker_error(result: subprocess.CompletedProcess[str]) -> RuntimeError:
        details = (result.stderr or result.stdout or "").strip()
        if not details:
            details = f"docker exited with status {result.returncode}"
        return RuntimeError(
            f"Failed to start local SearXNG with Docker: {details}"
        )

    async def _start_docker(self, settings_path: Path, port: int) -> None:
        if shutil.which("docker") is None:
            raise RuntimeError(
                "SearXNG is not installed and Docker is unavailable; install "
                "Docker, install SearXNG in this Python environment, or "
                "provide --searxng-url/SEARXNG_URL"
            )

        container_name = (
            f"ezwebsearch-searxng-{os.getpid()}-"
            f"{secrets.token_hex(4)}"
        )
        command = [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--name",
            container_name,
            "--publish",
            f"{self.DEFAULT_HOST}:{port}:{self.DOCKER_PORT}",
            "--volume",
            f"{self._config_dir}:/etc/searxng",
            "--env",
            f"BIND_ADDRESS={self.DOCKER_HOST}:{self.DOCKER_PORT}",
            "--env",
            "FORCE_OWNERSHIP=false",
            "--env",
            f"SEARXNG_BASE_URL=http://{self.DEFAULT_HOST}:{port}",
            self.docker_image,
        ]

        try:
            result = await asyncio.to_thread(
                subprocess.run,
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=max(self.startup_timeout_seconds, 30.0),
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "SearXNG is not installed and Docker could not be executed; "
                "install Docker, install SearXNG in this Python environment, "
                "or provide --searxng-url/SEARXNG_URL"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                "Timed out while provisioning local SearXNG with Docker"
            ) from exc

        if result.returncode != 0:
            raise self._docker_error(result)

        self._container_id = result.stdout.strip() or container_name
        self._container_name = container_name

    async def _stop_docker(self) -> None:
        container = self._container_id or self._container_name
        if not container or shutil.which("docker") is None:
            return

        for command in (
            ["docker", "stop", "--time", "5", container],
            ["docker", "rm", "--force", container],
        ):
            try:
                await asyncio.to_thread(
                    subprocess.run,
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=15.0,
                )
            except (OSError, subprocess.SubprocessError):
                # The container may already have exited or Docker may be
                # shutting down. Continue to the next cleanup action.
                pass

        self._container_id = None
        self._container_name = None

    def _run_server(self, settings_path: Path, port: int) -> None:
        """Import and serve SearXNG without blocking the application thread."""

        server: Any | None = None

        try:
            # SearXNG reads SEARXNG_SETTINGS_PATH while importing its web app,
            # so the environment must be set before these imports happen.
            with _SEARXNG_IMPORT_LOCK:
                previous_settings_path = os.environ.get("SEARXNG_SETTINGS_PATH")
                os.environ["SEARXNG_SETTINGS_PATH"] = str(settings_path)
                try:
                    from searx import webapp
                finally:
                    if previous_settings_path is None:
                        os.environ.pop("SEARXNG_SETTINGS_PATH", None)
                    else:
                        os.environ["SEARXNG_SETTINGS_PATH"] = previous_settings_path

            from werkzeug.serving import make_server

            server = make_server(
                self.DEFAULT_HOST,
                port,
                webapp.app,
                threaded=True,
            )
            self._server = server

            if self._stop_requested.is_set():
                server.server_close()
                return

            server.serve_forever()
        except BaseException as exc:
            self._thread_error = exc
        finally:
            if server is not None:
                try:
                    server.server_close()
                except Exception:
                    pass

    def _startup_error(self) -> RuntimeError | None:
        if self._thread_error is None:
            return None

        error = self._thread_error
        if isinstance(error, ModuleNotFoundError) and error.name == "searx":
            return RuntimeError(
                "SearXNG could not be imported for the in-process backend; "
                "install SearXNG in this Python environment, use Docker, or "
                "provide --searxng-url/SEARXNG_URL"
            )
        return RuntimeError(f"Failed to start local SearXNG: {error}")

    async def _wait_until_ready(self) -> None:
        if not self.url:
            raise RuntimeError("Local SearXNG URL was not initialized")

        deadline = asyncio.get_running_loop().time() + self.startup_timeout_seconds
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(2.0),
            trust_env=False,
        ) as client:
            while True:
                startup_error = self._startup_error()
                if startup_error is not None:
                    raise startup_error from self._thread_error

                thread = self._thread
                if thread is not None and not thread.is_alive():
                    raise RuntimeError("Local SearXNG stopped before becoming ready")

                try:
                    response = await client.get(f"{self.url}/healthz")
                    if response.status_code < 500:
                        return
                except httpx.HTTPError:
                    pass

                if asyncio.get_running_loop().time() >= deadline:
                    break
                await asyncio.sleep(0.25)

        startup_error = self._startup_error()
        if startup_error is not None:
            raise startup_error from self._thread_error
        raise RuntimeError("Temporary local SearXNG did not become ready")

    async def start(self) -> str:
        """Start SearXNG in a background thread and return its local base URL."""

        if self.url:
            return self.url

        try:
            selected_backend = self._selected_backend()
            port = self._find_free_port()
            if selected_backend == "docker":
                settings_path = self._write_settings(
                    self.DOCKER_PORT,
                    host=self.DOCKER_HOST,
                )
            else:
                settings_path = self._write_settings(port)
            self._thread_error = None
            self._stop_requested.clear()
            self._server = None
            self.url = f"http://{self.DEFAULT_HOST}:{port}"
            if selected_backend == "docker":
                await self._start_docker(settings_path, port)
            else:
                self._thread = threading.Thread(
                    target=self._run_server,
                    args=(settings_path, port),
                    name="ezwebsearch-searxng",
                    daemon=True,
                )
                self._thread.start()
            await self._wait_until_ready()
            return self.url
        except Exception:
            await self.close()
            raise

    async def close(self) -> None:
        """Stop the background SearXNG server and remove its temporary config."""

        thread = self._thread
        server = self._server
        self._stop_requested.set()

        if server is not None:
            try:
                await asyncio.to_thread(server.shutdown)
            except Exception:
                pass

        await self._stop_docker()

        if thread is not None and thread.is_alive():
            await asyncio.to_thread(thread.join, 5.0)

        self.url = None
        self._thread = None
        self._server = None
        self._thread_error = None
        self._container_id = None
        self._container_name = None

        if self._config_dir:
            shutil.rmtree(self._config_dir, ignore_errors=True)
            self._config_dir = None

    async def __aenter__(self) -> "LocalSearXNG":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()
