"""Docker sandbox security configuration."""
from dataclasses import dataclass


@dataclass
class SandboxConfig:
    # Container security
    network_disabled: bool = True           # --network none
    read_only_root: bool = True             # --read-only
    drop_all_capabilities: bool = True      # --cap-drop ALL
    no_new_privileges: bool = True          # no-new-privileges

    # Resource limits
    cpu_limit: str = "0.5"                  # 50% of one CPU core
    memory_limit: str = "256m"              # 256 MB RAM
    timeout_seconds: int = 30               # execution timeout
    disk_limit: str = "100m"                # writable layer limit

    # Docker image
    image: str = "python:3.12-slim"

    # File system
    work_dir: str = "/sandbox_workspace"
    max_output_size: int = 100_000          # 100KB output limit


SANDBOX_CONFIG = SandboxConfig()
