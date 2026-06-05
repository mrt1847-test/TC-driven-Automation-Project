from __future__ import annotations

import asyncio
import sys

from worker.core import subprocess_compat


def test_create_subprocess_exec_falls_back_when_asyncio_spawn_unsupported(monkeypatch) -> None:
    async def raise_not_implemented(*_args, **_kwargs):
        raise NotImplementedError

    monkeypatch.setattr(subprocess_compat.asyncio, "create_subprocess_exec", raise_not_implemented)

    async def run_spawn() -> tuple[int | None, bytes, bytes]:
        process = await subprocess_compat.create_subprocess_exec(
            sys.executable,
            "-c",
            "print('spawn-ok')",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        return process.returncode, stdout, stderr

    return_code, stdout, stderr = asyncio.run(run_spawn())

    assert return_code == 0
    assert stdout.decode().strip() == "spawn-ok"
    assert stderr == b""
