"""
Hot-plug plugin scanner — watches ./plugins/ for new stdio MCP servers.

Uses watchdog to monitor the directory. When a new executable file appears,
it attempts a FastMCP stdio connection handshake. On success it registers
the server with the running proxy. On file removal it deregisters.

Usage:
    scanner = PluginScanner(plugins_dir, on_register, on_deregister)
    scanner.start()   # begins watching
    scanner.stop()    # stops watching
"""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from typing import Callable, Optional

# watchdog is optional; scanner degrades gracefully if not installed
try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer
    _watchdog_available = True
except ImportError:
    _watchdog_available = False
    FileSystemEventHandler = object  # type: ignore[assignment,misc]


RegisterCallback = Callable[[str, str], None]   # (name, command)
DeregisterCallback = Callable[[str], None]       # (name,)


def _log(msg: str) -> None:
    sys.stderr.write(f"{msg}\n")


def _is_executable(path: Path) -> bool:
    try:
        mode = path.stat().st_mode
        return bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
    except OSError:
        return False


def _name_from_path(path: Path) -> str:
    """Derive a server name from a plugin filename, stripping extension."""
    return path.stem


class _PluginEventHandler(FileSystemEventHandler):
    def __init__(
        self,
        on_register: RegisterCallback,
        on_deregister: DeregisterCallback,
    ) -> None:
        self._on_register = on_register
        self._on_deregister = on_deregister
        self._registered: set[str] = set()

    def _try_register(self, path: Path) -> None:
        if not path.is_file():
            return
        if path.name.startswith("."):
            return
        if not _is_executable(path):
            _log(f"[plugin_scanner] Skipping non-executable: {path.name}")
            return
        name = _name_from_path(path)
        if name in self._registered:
            return
        command = str(path.resolve())
        _log(f"[plugin_scanner] Registering hot-plug plugin: {name} ({command})")
        self._registered.add(name)
        self._on_register(name, command)

    def _try_deregister(self, path: Path) -> None:
        name = _name_from_path(path)
        if name in self._registered:
            _log(f"[plugin_scanner] Deregistering plugin: {name}")
            self._registered.discard(name)
            self._on_deregister(name)

    # watchdog callbacks
    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._try_register(Path(str(event.src_path)))

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._try_deregister(Path(str(event.src_path)))

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._try_register(Path(str(event.src_path)))


class PluginScanner:
    """
    Watches a directory for executable MCP provider scripts.

    Args:
        plugins_dir: Path to the plugins directory (created if missing).
        on_register: Called with (name, command) when a new plugin is detected.
        on_deregister: Called with (name,) when a plugin is removed.
    """

    def __init__(
        self,
        plugins_dir: Path | str,
        on_register: RegisterCallback,
        on_deregister: DeregisterCallback,
    ) -> None:
        self._dir = Path(plugins_dir)
        self._on_register = on_register
        self._on_deregister = on_deregister
        self._observer: Optional[object] = None

    def scan_existing(self) -> None:
        """Register any executables already in the directory at startup."""
        if not self._dir.exists():
            return
        handler = self._get_handler()
        for entry in sorted(self._dir.iterdir()):
            if entry.is_file() and not entry.name.startswith("."):
                handler._try_register(entry)

    def _get_handler(self) -> _PluginEventHandler:
        if not hasattr(self, "_handler"):
            self._handler = _PluginEventHandler(self._on_register, self._on_deregister)
        return self._handler

    def start(self) -> None:
        """Start watching the plugins directory."""
        if not _watchdog_available:
            _log(
                "[plugin_scanner] watchdog is not installed. "
                "Hot-plug scanning disabled. Install with: uv add watchdog"
            )
            self.scan_existing()
            return

        self._dir.mkdir(parents=True, exist_ok=True)
        self.scan_existing()

        handler = self._get_handler()
        observer = Observer()
        observer.schedule(handler, str(self._dir), recursive=False)
        observer.start()
        self._observer = observer
        _log(f"[plugin_scanner] Watching {self._dir} for hot-plug plugins.")

    def stop(self) -> None:
        """Stop the file watcher."""
        if self._observer is not None:
            self._observer.stop()  # type: ignore[attr-defined]
            self._observer.join()  # type: ignore[attr-defined]
            self._observer = None
