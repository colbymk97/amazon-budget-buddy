from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Button, Checkbox, RichLog, Static

from ..command_runner import run_command


class CommandsView(Container):
    """Run amazon-spending subcommands inline; stream output to a log."""

    BINDINGS = [("c", "clear_log", "Clear log")]

    def __init__(self, db_path: Path) -> None:
        super().__init__(id="view-commands")
        self.db_path = db_path
        self._running = False

    def compose(self) -> ComposeResult:
        yield Static("Run commands", id="commands-title")
        with Horizontal(id="commands-toggles"):
            yield Checkbox("--headed (show browser)", id="opt-headed")
            yield Checkbox("--dry-run (actual-sync)", id="opt-dry-run")
            yield Checkbox("--stop-on-known (collect)", value=True, id="opt-stop-known")
        with Horizontal(id="commands-buttons"):
            yield Button("Login", id="cmd-login")
            yield Button("Collect", id="cmd-collect", variant="primary")
            yield Button("Audit (latest)", id="cmd-audit")
            yield Button("Actual Sync", id="cmd-actual-sync")
            yield Button("Export CSV", id="cmd-export")
            yield Button("DB Status", id="cmd-status")
        yield Static("[dim]idle[/dim]", id="commands-state")
        yield RichLog(id="commands-log", wrap=True, highlight=True, markup=True, max_lines=2000)

    def action_clear_log(self) -> None:
        self.query_one("#commands-log", RichLog).clear()

    def _headed(self) -> bool:
        return self.query_one("#opt-headed", Checkbox).value

    def _dry_run(self) -> bool:
        return self.query_one("#opt-dry-run", Checkbox).value

    def _stop_on_known(self) -> bool:
        return self.query_one("#opt-stop-known", Checkbox).value

    @on(Button.Pressed)
    async def _on_button(self, event: Button.Pressed) -> None:
        if self._running:
            return

        button_id = event.button.id or ""
        args: list[str] | None = None
        if button_id == "cmd-login":
            args = ["login", "--retailer", "amazon"]
            if not self._headed():
                args.append("--check")
        elif button_id == "cmd-collect":
            args = ["collect", "--retailer", "amazon"]
            if self._stop_on_known():
                args.append("--stop-on-known")
            if self._headed():
                args.append("--headed")
        elif button_id == "cmd-audit":
            args = ["audit", "--mode", "latest"]
            if self._headed():
                args.append("--headed")
        elif button_id == "cmd-actual-sync":
            args = ["actual-sync"]
            if self._dry_run():
                args.append("--dry-run")
        elif button_id == "cmd-export":
            args = ["export"]
        elif button_id == "cmd-status":
            args = ["db-status"]

        if args is None:
            return

        await self._run(args)

    async def _run(self, args: list[str]) -> None:
        self._running = True
        state = self.query_one("#commands-state", Static)
        log = self.query_one("#commands-log", RichLog)
        state.update("[yellow]running…[/yellow]")
        try:
            result = await run_command(args, lambda line: log.write(line))
            color = "green" if result.ok else "red"
            label = "ok" if result.ok else f"exit {result.returncode}"
            state.update(f"[{color}]{label}[/{color}]")
        except Exception as exc:
            state.update(f"[red]error: {exc}[/red]")
            log.write(f"[red]command failed: {exc}[/red]")
        finally:
            self._running = False
