"""Run amazon-spending subcommands from inside the TUI.

The TUI shells out to the same CLI binary the user would invoke from a normal
shell, so there's exactly one orchestration path. stdout/stderr are streamed
line-by-line to a RichLog widget so progress is visible in real time.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
from dataclasses import dataclass
from typing import Any, Callable


# A log sink takes one line of output. It may return None (sync) or an
# awaitable (async); we await whichever comes back.
LogSink = Callable[[str], Any]


@dataclass
class CommandResult:
    returncode: int
    @property
    def ok(self) -> bool:
        return self.returncode == 0


def _resolve_cli() -> list[str]:
    """Locate the amazon-spending entry point.

    Prefer the installed console_script on PATH; fall back to `python -m
    amazon_spending` so the TUI also works in editable installs where the
    script may not be on PATH yet.
    """
    bin_path = shutil.which("amazon-spending")
    if bin_path:
        return [bin_path]
    return [sys.executable, "-m", "amazon_spending"]


async def run_command(args: list[str], log: LogSink) -> CommandResult:
    """Run `amazon-spending <args>` and stream output through `log`."""
    cli = _resolve_cli()
    cmd_str = " ".join(cli + args)
    await _emit(log, f"$ {cmd_str}")

    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    proc = await asyncio.create_subprocess_exec(
        *cli, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )

    assert proc.stdout is not None
    while True:
        chunk = await proc.stdout.readline()
        if not chunk:
            break
        await _emit(log, chunk.decode("utf-8", errors="replace").rstrip("\n"))

    returncode = await proc.wait()
    await _emit(log, f"[exit {returncode}]")
    return CommandResult(returncode=returncode)


async def _emit(log: LogSink, line: str) -> None:
    result = log(line)
    if asyncio.iscoroutine(result):
        await result
