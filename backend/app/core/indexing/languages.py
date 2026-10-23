"""Language detection and file classification for the repo indexer."""

CODE_EXT_LANG = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".jsx": "jsx", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "tsx",
    ".java": "java", ".kt": "kotlin", ".scala": "scala",
    ".go": "go", ".rs": "rust", ".swift": "swift",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp", ".cs": "csharp",
    ".rb": "ruby", ".php": "php", ".lua": "lua", ".pl": "perl",
    ".sql": "sql", ".sh": "shell", ".bash": "shell", ".zsh": "shell", ".ps1": "powershell",
    ".yaml": "yaml", ".yml": "yaml", ".json": "json", ".toml": "toml", ".ini": "ini",
    ".xml": "xml", ".html": "html", ".htm": "html", ".css": "css", ".scss": "scss", ".less": "less",
    ".vue": "vue", ".svelte": "svelte", ".gradle": "groovy", ".proto": "protobuf",
}

DOC_EXT_LANG = {
    ".md": "markdown", ".markdown": "markdown", ".txt": "text",
    ".rst": "rst", ".pdf": "pdf",
}

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env", "__pycache__",
    "dist", "build", "out", ".idea", ".vscode", ".next", ".nuxt", "target",
    "vendor", ".pytest_cache", ".mypy_cache", ".tox", ".gradle", "coverage",
    ".terraform", "site-packages",
}

MAX_BINARY_CHECK_BYTES = 2048


def detect_language(path: str) -> tuple[str, bool]:
    """Return (language, is_doc) for a path; ("", False) when unsupported."""
    lower = path.lower()
    for ext, lang in DOC_EXT_LANG.items():
        if lower.endswith(ext):
            return lang, True
    for ext, lang in CODE_EXT_LANG.items():
        if lower.endswith(ext):
            return lang, False
    return "", False


def is_supported(path: str) -> bool:
    lang, _ = detect_language(path)
    return bool(lang)


def looks_binary(data: bytes) -> bool:
    if b"\x00" in data[:MAX_BINARY_CHECK_BYTES]:
        return True
    try:
        data[:MAX_BINARY_CHECK_BYTES].decode("utf-8")
        return False
    except UnicodeDecodeError:
        return False  # may be another text encoding — let the caller try