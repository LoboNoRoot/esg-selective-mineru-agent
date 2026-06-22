from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Any, Dict


def run_mineru(pdf_path: Path, output_root: Path, command_template: str, timeout_seconds: int) -> Dict[str, Any]:
    if not command_template.strip():
        return {"attempted": False, "status": "not_configured", "error": ""}
    output_root.mkdir(parents=True, exist_ok=True)
    command = command_template.format(pdf=str(pdf_path.resolve()), output=str(output_root.resolve()))
    try:
        completed = subprocess.run(
            shlex.split(command, posix=os.name != "nt"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        return {
            "attempted": True,
            "status": "completed" if completed.returncode == 0 else "failed",
            "return_code": completed.returncode,
            "stdout_tail": completed.stdout[-2000:],
            "stderr_tail": completed.stderr[-2000:],
            "command": command,
        }
    except Exception as exc:
        return {"attempted": True, "status": "exception", "error": str(exc), "command": command}
