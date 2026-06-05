from __future__ import annotations

import asyncio
import subprocess
from typing import Any


class _SyncPipeReader:
    def __init__(self, pipe: Any) -> None:
        self._pipe = pipe

    async def readline(self) -> bytes:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._pipe.readline)


class _PopenProcess:
    """Wrap subprocess.Popen with an asyncio.subprocess.Process-like surface."""

    def __init__(self, popen: subprocess.Popen[bytes]) -> None:
        self._popen = popen
        self.pid = popen.pid
        self.stdout = _SyncPipeReader(popen.stdout) if popen.stdout is not None else None
        self.stderr = _SyncPipeReader(popen.stderr) if popen.stderr is not None else None

    @property
    def returncode(self) -> int | None:
        return self._popen.returncode

    async def wait(self) -> int:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._popen.wait)

    def kill(self) -> None:
        self._popen.kill()

    async def communicate(self) -> tuple[bytes, bytes]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._popen.communicate)


def _map_stdio(value: Any) -> Any:
    if value in {asyncio.subprocess.PIPE, subprocess.PIPE}:
        return subprocess.PIPE
    if value in {asyncio.subprocess.STDOUT, subprocess.STDOUT}:
        return subprocess.STDOUT
    if value in {asyncio.subprocess.DEVNULL, subprocess.DEVNULL}:
        return subprocess.DEVNULL
    return value


async def create_subprocess_exec(
    *cmd: str | bytes,
    stdin: Any = None,
    stdout: Any = None,
    stderr: Any = None,
    cwd: str | bytes | None = None,
    env: dict[str, str] | None = None,
    **kwargs: Any,
) -> asyncio.subprocess.Process | _PopenProcess:
    try:
        return await asyncio.create_subprocess_exec(
            *cmd,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            cwd=cwd,
            env=env,
            **kwargs,
        )
    except NotImplementedError:
        loop = asyncio.get_running_loop()

        def _spawn() -> subprocess.Popen[bytes]:
            return subprocess.Popen(
                list(cmd),
                stdin=_map_stdio(stdin),
                stdout=_map_stdio(stdout),
                stderr=_map_stdio(stderr),
                cwd=cwd,
                env=env,
                **kwargs,
            )

        popen = await loop.run_in_executor(None, _spawn)
        return _PopenProcess(popen)
