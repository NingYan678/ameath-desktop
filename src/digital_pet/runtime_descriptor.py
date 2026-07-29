"""Safe, low-overhead access to a Gateway desktop runtime descriptor."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class RuntimeHealth(StrEnum):
    VERIFYING = "verifying"
    READY = "ready"
    STOPPED = "stopped"
    UNTRUSTED = "untrusted"
    ERROR = "error"


@dataclass(frozen=True)
class RuntimeDescriptor:
    port: int
    token: str
    pid: int


@dataclass(frozen=True)
class RuntimeFingerprint:
    path: Path
    modified_ns: int
    size: int
    pid: int
    port: int
    source: Path


def read_runtime_descriptor(path: Path) -> RuntimeDescriptor | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("state") != "ready":
        return None
    port, token, pid = payload.get("port"), payload.get("token"), payload.get("pid")
    if not isinstance(port, int) or not 1 <= port <= 65_535:
        return None
    if not isinstance(token, str) or len(token) < 24 or not isinstance(pid, int) or pid <= 0:
        return None
    return RuntimeDescriptor(port, token, pid)


def runtime_fingerprint(path: Path, source: Path) -> RuntimeFingerprint | None:
    descriptor = read_runtime_descriptor(path)
    if descriptor is None:
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    return RuntimeFingerprint(path.resolve(), stat.st_mtime_ns, stat.st_size, descriptor.pid, descriptor.port, source.resolve())


def pid_is_alive(pid: int) -> bool:
    """Use the native Windows process API; never spawn a shell for polling."""
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not process:
        return False
    try:
        exit_code = ctypes.c_ulong()
        return bool(ctypes.windll.kernel32.GetExitCodeProcess(process, ctypes.byref(exit_code))) and exit_code.value == 259
    finally:
        ctypes.windll.kernel32.CloseHandle(process)


def quick_runtime_health(path: Path, source: Path, verified: RuntimeFingerprint | None) -> tuple[RuntimeHealth, RuntimeFingerprint | None]:
    fingerprint = runtime_fingerprint(path, source)
    if fingerprint is None or not pid_is_alive(fingerprint.pid):
        return RuntimeHealth.STOPPED, fingerprint
    return (RuntimeHealth.READY if fingerprint == verified else RuntimeHealth.VERIFYING), fingerprint


def pid_belongs_to_runtime(pid: int, source: Path) -> bool:
    """Strict ownership verification, performed only in a background worker."""
    expected_source = str(source.resolve()).replace("'", "''").lower()
    script = f"""
$expected = '{expected_source}'
$current = Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}'
for ($step = 0; $step -lt 4 -and $null -ne $current; $step++) {{
  $line = [string]$current.CommandLine
  $ownsSource = $line.ToLowerInvariant().Contains($expected)
  $gateway = ($line -match 'hermes(?:_cli)?') -and ($line -match 'gateway([ ]|$)')
  if ($step -eq 0 -and -not $ownsSource -and -not $gateway) {{ break }}
  if ($gateway -and $ownsSource) {{ 'true'; exit 0 }}
  $parent = [int]$current.ParentProcessId
  if ($parent -le 0 -or $parent -eq [int]$current.ProcessId) {{ break }}
  $current = Get-CimInstance Win32_Process -Filter "ProcessId = $parent"
}}
'false'
"""
    try:
        result = subprocess.run(
            ["powershell", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def read_verified_runtime(path: Path, source: Path) -> RuntimeDescriptor | None:
    descriptor = read_runtime_descriptor(path)
    return descriptor if descriptor is not None and pid_is_alive(descriptor.pid) and pid_belongs_to_runtime(descriptor.pid, source) else None


def stop_verified_runtime(path: Path, source: Path) -> bool:
    """Always re-verify immediately before terminating a process."""
    descriptor = read_verified_runtime(path, source)
    if descriptor is None:
        return False
    expected_source = str(source.resolve()).replace("'", "''").lower()
    script = f"""
$expected = '{expected_source}'
$root = Get-CimInstance Win32_Process -Filter 'ProcessId = {descriptor.pid}'
if ($null -eq $root) {{ exit 1 }}
$targets = New-Object 'System.Collections.Generic.HashSet[int]'
$queue = New-Object 'System.Collections.Generic.Queue[int]'
[void]$targets.Add([int]{descriptor.pid})
[void]$queue.Enqueue([int]{descriptor.pid})
$current = $root
for ($step = 0; $step -lt 4 -and $null -ne $current; $step++) {{
  $parent = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$current.ParentProcessId)"
  if ($null -eq $parent) {{ break }}
  $line = [string]$parent.CommandLine
  $ownsSource = $line.ToLowerInvariant().Contains($expected)
  $gateway = ($line -match 'hermes(?:_cli)?') -and ($line -match 'gateway([ ]|$)')
  if (-not $ownsSource -or -not $gateway) {{ break }}
  if ($targets.Add([int]$parent.ProcessId)) {{ [void]$queue.Enqueue([int]$parent.ProcessId) }}
  $current = $parent
}}
while ($queue.Count -gt 0) {{
  $parentId = $queue.Dequeue()
  foreach ($child in @(Get-CimInstance Win32_Process | Where-Object {{ [int]$_.ParentProcessId -eq $parentId }})) {{
    $line = [string]$child.CommandLine
    if ($line.ToLowerInvariant().Contains($expected) -and $targets.Add([int]$child.ProcessId)) {{
      [void]$queue.Enqueue([int]$child.ProcessId)
    }}
  }}
}}
$targets | Sort-Object -Descending | ForEach-Object {{ Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }}
    """
    result = subprocess.run(
        # The descriptor points at the uv Python leaf; also stop its verified
        # Hermes wrapper and source-owned children so updates can replace the exe.
        ["powershell", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    return result.returncode == 0
