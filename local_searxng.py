from __future__ import annotations

import asyncio
import os
import secrets
import shutil
import tempfile
from pathlib import Path
from typing import Sequence

import httpx


class LocalSearXNG:
    """Manage a short-lived local SearXNG container for CLI searches."""

    DEFAULT_IMAGE = "docker.io/searxng/searxng:latest"
    DEFAULT_STARTUP_TIMEOUT_SECONDS = 120.0

    def __init__(
        self,
        *,
        runtime: str | None = None,
        image: str | None = None,
        startup_timeout_seconds: float | None = None,
    ) -> None:
        self.runtime = runtime or os.getenv("SEARXNG_CONTAINER_RUNTIME", "docker")
        self.image = image or os.getenv("SEARXNG_IMAGE", self.DEFAULT_IMAGE)
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
        self.container_id: str | None = None
        self.container_name: str | None = None
        self.url: str | None = None
        self._config_dir: Path | None = None

    async def _run_command(
        self,
        arguments: Sequence[str],
        *,
        timeout: float | None = 30.0,
    ) -> str:
        process = await asyncio.create_subprocess_exec(
            self.runtime,
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            raise RuntimeError(
                f"{self.runtime} {' '.join(arguments)} timed out"
            ) from None

        if process.returncode != 0:
            details = stderr.decode(errors="replace").strip()
            message = f"{self.runtime} {' '.join(arguments)} failed"
            if details:
                message += f": {details}"
            raise RuntimeError(message)

        return stdout.decode(errors="replace").strip()

    def _write_settings(self) -> Path:
        config_dir = Path(tempfile.mkdtemp(prefix="ezwebsearch-"))
        self._config_dir = config_dir
        # tempfile directories are private by default. The container's
        # unprivileged SearXNG user needs to be able to traverse the mount.
        config_dir.chmod(0o755)

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
  bind_address: "0.0.0.0"
  limiter: false
""".format(secret_key=secrets.token_hex(32)),
            encoding="utf-8",
        )
        settings.chmod(0o644)
        return config_dir

    @staticmethod
    def _port_from_output(output: str) -> int:
        for line in output.splitlines():
            value = line.rsplit(":", 1)[-1].strip()
            if value.isdigit():
                port = int(value)
                if 1 <= port <= 65535:
                    return port
        raise RuntimeError(f"Could not determine the local SearXNG port: {output}")

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
                try:
                    response = await client.get(f"{self.url}/")
                    if response.status_code < 500:
                        return
                except httpx.HTTPError:
                    pass

                if asyncio.get_running_loop().time() >= deadline:
                    break
                await asyncio.sleep(0.25)

        logs = ""
        if self.container_id:
            try:
                logs = await self._run_command(
                    ["logs", "--tail", "30", self.container_id],
                    timeout=5.0,
                )
            except Exception:
                pass

        message = "Temporary local SearXNG did not become ready"
        if logs:
            message += f". Container log:\n{logs}"
        raise RuntimeError(message)

    async def start(self) -> str:
        """Start SearXNG and return its local base URL."""

        if self.url:
            return self.url

        if not shutil.which(self.runtime):
            raise RuntimeError(
                f"{self.runtime} is required when --searxng-url is omitted; "
                f"install {self.runtime} or provide --searxng-url"
            )

        self.container_name = f"ezwebsearch-{secrets.token_hex(8)}"

        try:
            config_dir = self._write_settings()
            container_output = await self._run_command(
                [
                    "run",
                    "--detach",
                    "--rm",
                    "--name",
                    self.container_name,
                    "--publish",
                    "127.0.0.1::8080/tcp",
                    "--volume",
                    f"{config_dir}:/etc/searxng",
                    "--env",
                    "FORCE_OWNERSHIP=false",
                    self.image,
                ],
                timeout=self.startup_timeout_seconds,
            )
            self.container_id = container_output.splitlines()[-1].strip()
            if not self.container_id:
                raise RuntimeError("Docker returned no SearXNG container ID")

            port_output = await self._run_command(
                ["port", self.container_id, "8080/tcp"],
            )
            port = self._port_from_output(port_output)
            self.url = f"http://127.0.0.1:{port}"
            await self._wait_until_ready()
            return self.url
        except Exception:
            await self.close()
            raise

    async def close(self) -> None:
        """Stop the temporary container and remove its temporary config."""

        container_id = self.container_id
        container_target = container_id or self.container_name
        self.container_id = None
        self.container_name = None
        self.url = None

        if container_target:
            try:
                await self._run_command(
                    ["stop", "--time", "2", container_target],
                    timeout=10.0,
                )
            except Exception:
                # --rm normally removes the container after stop. If it has
                # already exited, force-remove it as a best-effort fallback.
                try:
                    await self._run_command(
                        ["rm", "--force", container_target],
                        timeout=10.0,
                    )
                except Exception:
                    pass

        if self._config_dir:
            shutil.rmtree(self._config_dir, ignore_errors=True)
            self._config_dir = None

    async def __aenter__(self) -> "LocalSearXNG":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()
