"""Docker sandbox runtime for secure code execution."""
import asyncio
import shutil
import tempfile
import structlog
from typing import Optional
from app.core.sandbox.config import SANDBOX_CONFIG

logger = structlog.get_logger()

# Docker availability flag
_docker_available = None


def is_docker_available() -> bool:
    """Check if Docker is installed and running."""
    global _docker_available
    if _docker_available is None:
        _docker_available = shutil.which("docker") is not None
        if _docker_available:
            try:
                import subprocess
                result = subprocess.run(
                    ["docker", "info"],
                    capture_output=True, timeout=5
                )
                _docker_available = result.returncode == 0
            except Exception:
                _docker_available = False
    return _docker_available


async def execute_in_sandbox(
    code: str,
    language: str = "python",
    inputs: str = "",
    timeout: int = None,
) -> dict:
    """
    Execute code in an isolated Docker container.
    Returns: {"stdout": str, "stderr": str, "exit_code": int, "timed_out": bool, "sandboxed": bool}
    """
    if not is_docker_available():
        logger.warning("Docker not available, falling back to direct execution")
        return await _execute_direct(code, language, inputs, timeout or SANDBOX_CONFIG.timeout_seconds)

    timeout = timeout or SANDBOX_CONFIG.timeout_seconds
    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="novatech_sandbox_")
        # Write code to file
        filename = "main.py" if language == "python" else f"main.{language}"
        code_path = f"{tmp_dir}/{filename}"
        with open(code_path, "w", encoding="utf-8") as f:
            f.write(code)
        if inputs:
            with open(f"{tmp_dir}/input.txt", "w", encoding="utf-8") as f:
                f.write(inputs)

        # Build Docker command with security flags
        cmd = [
            "docker", "run", "--rm",
            "--network", "none",
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--cpus", SANDBOX_CONFIG.cpu_limit,
            "--memory", SANDBOX_CONFIG.memory_limit,
            "-v", f"{tmp_dir}:{SANDBOX_CONFIG.work_dir}:rw",
            "-w", SANDBOX_CONFIG.work_dir,
            SANDBOX_CONFIG.image,
            "timeout", str(timeout),
            "python", filename,
        ]

        # Execute
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if inputs else None,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=inputs.encode() if inputs else None),
                timeout=timeout + 5  # Docker overhead buffer
            )
            return {
                "stdout": stdout.decode("utf-8", errors="replace")[:SANDBOX_CONFIG.max_output_size],
                "stderr": stderr.decode("utf-8", errors="replace")[:10000],
                "exit_code": proc.returncode,
                "timed_out": False,
                "sandboxed": True,
            }
        except asyncio.TimeoutError:
            # Kill the container
            try:
                await asyncio.create_subprocess_exec("docker", "kill", f"novatech-{proc.pid}")
            except Exception:
                pass
            return {
                "stdout": "",
                "stderr": "Execution timed out",
                "exit_code": -1,
                "timed_out": True,
                "sandboxed": True,
            }
    except Exception as e:
        logger.error("Sandbox execution failed", error=str(e))
        return {
            "stdout": "",
            "stderr": f"Sandbox error: {e}",
            "exit_code": -1,
            "timed_out": False,
            "sandboxed": True,
        }
    finally:
        if tmp_dir:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)


async def _execute_direct(code: str, language: str, inputs: str, timeout: int) -> dict:
    """Fallback: execute directly without Docker (less secure, for dev environments)."""
    import os, subprocess, tempfile
    tmp_dir = tempfile.mkdtemp(prefix="novatech_direct_")
    try:
        filename = "main.py" if language == "python" else f"main.{language}"
        filepath = os.path.join(tmp_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(code)

        proc = subprocess.run(
            ["python", filepath],
            input=inputs.encode() if inputs else None,
            capture_output=True,
            timeout=timeout,
        )
        return {
            "stdout": proc.stdout.decode("utf-8", errors="replace")[:SANDBOX_CONFIG.max_output_size],
            "stderr": proc.stderr.decode("utf-8", errors="replace")[:10000],
            "exit_code": proc.returncode,
            "timed_out": False,
            "sandboxed": False,
        }
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "Timed out", "exit_code": -1, "timed_out": True, "sandboxed": False}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "exit_code": -1, "timed_out": False, "sandboxed": False}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
