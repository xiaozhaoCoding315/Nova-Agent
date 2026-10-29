"""Shell command classification for permission gating.

The classifier is intentionally conservative: anything it cannot prove is
read-only is reported as ``unknown`` and blocked in readonly/ask modes.
The sandbox remains the real security boundary; this layer only keeps the
permission promise (no unapproved workspace mutations) honest.
"""
import re
import shlex
from enum import Enum


class CommandClass(str, Enum):
    READONLY = "readonly"
    MUTATING = "mutating"
    UNKNOWN = "unknown"


_SIMPLE_READONLY = {
    "ls", "cat", "head", "tail", "wc", "stat", "du", "df",
    "which", "type", "pwd", "whoami", "id", "uname",
    "true", "false", ":", "test", "[", "cd", "jq",
    "basename", "dirname", "realpath", "readlink", "nl", "column",
    "cut", "tr",
}
_ECHO = {"echo", "printf"}
_WRAPPERS = {"sudo", "env", "nohup", "nice", "timeout", "xargs", "command", "exec"}
_MUTATING = {
    "rm", "mv", "cp", "touch", "mkdir", "rmdir", "ln", "chmod", "chown",
    "chgrp", "dd", "truncate", "install", "tee", "kill", "pkill",
    "npm", "yarn", "pnpm", "pip", "pip3", "uv", "poetry", "gem",
    "cargo", "go", "make", "cmake",
}
_UNKNOWN = {
    "python", "python3", "node", "ruby", "perl", "php", "bash", "sh", "zsh",
    "fish", "awk", "curl", "wget", "nc", "netcat", "ssh", "scp", "rsync",
    "docker", "podman", "kubectl", "terraform", "helm", "systemctl", "service",
}
_READONLY_GIT = {
    "status", "diff", "log", "show", "blame", "rev-parse", "ls-files", "grep",
    "describe", "shortlog", "reflog", "cat-file", "show-ref", "for-each-ref",
    "diff-tree", "diff-index", "help", "version",
}
_GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
_GIT_EQUALS_OPTS = ("--git-dir", "--work-tree", "--namespace", "--exec-path")


def classify_command(command: str) -> tuple[CommandClass, str]:
    """Classify a shell command as readonly / mutating / unknown.

    Fail closed: unparseable or ambiguous input is UNKNOWN.
    """
    raw = (command or "").strip()
    if not raw:
        return CommandClass.UNKNOWN, "空命令"
    if "$(" in raw or "`" in raw or "<(" in raw or ">(" in raw:
        return CommandClass.UNKNOWN, "包含命令替换/进程替换"
    try:
        segments = _split_segments(raw)
    except ValueError as exc:
        return CommandClass.UNKNOWN, f"无法解析：{exc}"
    if not segments:
        return CommandClass.UNKNOWN, "空命令"
    for segment in segments:
        result = _classify_segment(segment)
        if result[0] is not CommandClass.READONLY:
            return result
    return CommandClass.READONLY, "只读命令"


def _split_segments(command: str) -> list[str]:
    segments: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(command):
        ch = command[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                if quote == '"':
                    backslashes = 0
                    j = i - 1
                    while j >= 0 and command[j] == "\\":
                        backslashes += 1
                        j -= 1
                    escaped = backslashes % 2 == 1
                else:
                    escaped = False
                if not escaped:
                    quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < len(command):
            buf.append(command[i:i + 2])
            i += 2
            continue
        if ch == "&":
            if i + 1 < len(command) and command[i + 1] == "&":
                segments.append("".join(buf))
                buf = []
                i += 2
                continue
            if i > 0 and command[i - 1] == ">":
                buf.append(ch)
                i += 1
                continue
            if i + 1 < len(command) and command[i + 1] in "12>":
                buf.append(ch)
                i += 1
                continue
            raise ValueError("不支持的后台执行 &")
        if ch in ("|", ";"):
            if ch == "|" and i + 1 < len(command) and command[i + 1] == "|":
                segments.append("".join(buf))
                buf = []
                i += 2
                continue
            segments.append("".join(buf))
            buf = []
            i += 1
            continue
        if ch == "\n":
            segments.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    if quote:
        raise ValueError("未闭合的引号")
    segments.append("".join(buf))
    return [segment.strip() for segment in segments if segment.strip()]


def _strip_quotes(text: str) -> str:
    return re.sub(r"'[^']*'|\"[^\"]*\"", "", text)


def _redirect_kind(segment: str) -> str | None:
    text = _strip_quotes(segment)
    if "<<" in text:
        return "heredoc"
    for match in re.finditer(r"(>>?)(\s*)([^\s|;]*)", text):
        target = match.group(3)
        if re.fullmatch(r"&\d+", target):
            continue
        return "file"
    return None


_SAFE_SED_SCRIPT = re.compile(r"^(?:\d+|\$)?(?:,\s*(?:\d+|\$))?p$")


def _has_option(args: list[str], names: set[str]) -> bool:
    for arg in args:
        if arg in names:
            return True
        if any(arg.startswith(name + "=") for name in names):
            return True
    return False


def _classify_sed(args: list[str]) -> tuple[CommandClass, str]:
    if any(
        arg.startswith("--in-place")
        or (arg.startswith("-") and not arg.startswith("--") and "i" in arg[1:])
        for arg in args
    ):
        return CommandClass.MUTATING, "sed -i 会写文件"
    if not any(arg in ("-n", "--quiet", "--silent") for arg in args):
        return CommandClass.MUTATING, "sed 未使用 -n，可能打印或改写文件"
    if any(arg in ("-f", "--file") or arg.startswith("--file=") for arg in args):
        return CommandClass.MUTATING, "sed -f 可执行任意脚本"

    scripts: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-e", "--expression"):
            if i + 1 < len(args):
                scripts.append(args[i + 1])
            i += 2
            continue
        if arg.startswith("--expression="):
            scripts.append(arg.split("=", 1)[1])
            i += 1
            continue
        if arg.startswith("-"):
            i += 1
            continue
        if not scripts:
            scripts.append(arg)
        i += 1

    if not scripts or not all(_SAFE_SED_SCRIPT.match(script) for script in scripts):
        return CommandClass.MUTATING, "sed 脚本包含非打印命令"
    return CommandClass.READONLY, "sed 只读打印"


def _classify_segment(segment: str) -> tuple[CommandClass, str]:
    redirect = _redirect_kind(segment)
    if redirect == "heredoc":
        return CommandClass.UNKNOWN, "包含 heredoc"
    if redirect == "file":
        return CommandClass.MUTATING, "重定向写入文件"
    try:
        tokens = shlex.split(segment, posix=True)
    except ValueError as exc:
        return CommandClass.UNKNOWN, f"无法解析：{exc}"
    if not tokens:
        return CommandClass.READONLY, "空段"
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
        return CommandClass.UNKNOWN, "包含环境变量前缀，无法静态判定"

    head = tokens[0]
    args = tokens[1:]
    if head in _WRAPPERS:
        return CommandClass.UNKNOWN, f"包装器 {head} 无法静态判定"
    if head == "git":
        return _classify_git(args)
    if head == "find":
        denied = {
            "-delete", "-exec", "-execdir", "-ok", "-okdir",
            "-fprint", "-fprint0", "-fprintf", "-fls",
        }
        if any(token in denied for token in args):
            return CommandClass.MUTATING, "find 带有删除/执行动作"
        return CommandClass.READONLY, "find 只读查询"
    if head == "sed":
        return _classify_sed(args)
    if head == "sort":
        if _has_option(args, {"-o", "--output", "--compress-program"}):
            return CommandClass.MUTATING, "sort 会写文件或执行外部程序"
        if any(
            token.startswith("-") and not token.startswith("--") and "o" in token[1:]
            for token in args
        ):
            return CommandClass.MUTATING, "sort -o 会写文件"
        return CommandClass.READONLY, "sort 只读"
    if head in ("grep", "rg"):
        if _has_option(args, {"--pre", "--pager"} if head == "rg" else {"--pager"}):
            return CommandClass.UNKNOWN, f"{head} 会执行外部程序"
        return CommandClass.READONLY, f"{head} 只读"
    if head == "file":
        if any(arg in ("-C", "--compile") for arg in args):
            return CommandClass.MUTATING, "file -C 会写文件"
        return CommandClass.READONLY, "file 只读"
    if head == "tree":
        if any(
            arg.startswith("-o") or arg.startswith("--output")
            for arg in args
        ):
            return CommandClass.MUTATING, "tree -o 会写文件"
        return CommandClass.READONLY, "tree 只读"
    if head == "date":
        if any(
            (arg.startswith("-s") and not arg.startswith("--"))
            or arg == "--set" or arg.startswith("--set=")
            for arg in args
        ):
            return CommandClass.MUTATING, "date -s 会修改系统时间"
        return CommandClass.READONLY, "date 只读"
    if head == "hostname":
        if args:
            return CommandClass.MUTATING, "hostname 带参数可能修改主机名"
        return CommandClass.READONLY, "hostname 只读"
    if head in _ECHO:
        return CommandClass.READONLY, "无重定向的输出命令"
    if head in _SIMPLE_READONLY:
        return CommandClass.READONLY, f"{head} 只读"
    if head in _MUTATING:
        return CommandClass.MUTATING, f"{head} 会修改文件或环境"
    if head in _UNKNOWN:
        return CommandClass.UNKNOWN, f"{head} 可执行任意代码或访问网络"
    return CommandClass.UNKNOWN, f"未识别的命令：{head}"


def _strip_git_globals(tokens: list[str]) -> list[str]:
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in _GIT_VALUE_OPTS:
            i += 2
            continue
        if any(token.startswith(option + "=") for option in _GIT_EQUALS_OPTS):
            i += 1
            continue
        if token in ("--no-pager", "--paginate", "-P"):
            i += 1
            continue
        break
    return tokens[i:]


def _git_writes_output(args: list[str]) -> bool:
    return any(arg == "--output" or arg.startswith("--output=") or arg == "-o" for arg in args)


def _git_global_options(tokens: list[str]) -> list[tuple[str, str]]:
    """Collect git global options before the subcommand."""
    options: list[tuple[str, str]] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"):
            value = tokens[i + 1] if i + 1 < len(tokens) else ""
            options.append((token, value))
            i += 2
            continue
        if any(token.startswith(option + "=") for option in _GIT_EQUALS_OPTS):
            name, value = token.split("=", 1)
            options.append((name, value))
            i += 1
            continue
        if token in ("--no-pager", "--paginate", "-P"):
            i += 1
            continue
        break
    return options


_GIT_EXEC_LONG_OPTS = ("--open-files-in-pager", "--ext-diff", "--textconv")


def _git_exec_option(arg: str) -> bool:
    """True for an exec-capable long option, including git's abbreviations."""
    name = arg.split("=", 1)[0]
    if len(name) < 3 or not name.startswith("--"):
        return False
    return any(option.startswith(name) for option in _GIT_EXEC_LONG_OPTS)


def _classify_git(args: list[str]) -> tuple[CommandClass, str]:
    globals_ = _git_global_options(args)
    if any(name == "-c" for name, _ in globals_):
        return CommandClass.UNKNOWN, "git -c 可注入可执行配置"
    if any(name == "--exec-path" for name, _ in globals_):
        return CommandClass.UNKNOWN, "--exec-path 会改变可执行程序路径"
    rest = _strip_git_globals(args)
    if not rest:
        return CommandClass.READONLY, "git 帮助"
    sub = rest[0]
    sub_args = rest[1:]
    if sub in ("--version", "-v", "--help", "-h"):
        return CommandClass.READONLY, f"git {sub}"

    if any(_git_exec_option(arg) for arg in sub_args):
        return CommandClass.UNKNOWN, "git 选项会执行外部程序"
    if sub == "grep" and any(
        arg.startswith("-") and not arg.startswith("--") and "O" in arg[1:]
        for arg in sub_args
    ):
        return CommandClass.UNKNOWN, "git grep -O 会执行外部程序"

    if sub == "reflog":
        if sub_args and sub_args[0] in ("expire", "delete", "drop"):
            return CommandClass.MUTATING, "git reflog 会改写引用日志"
        return CommandClass.READONLY, "git reflog 只读"

    if sub in _READONLY_GIT:
        if _git_writes_output(sub_args):
            return CommandClass.MUTATING, "git 写输出文件"
        return CommandClass.READONLY, f"git {sub} 只读"

    if sub == "branch":
        if not sub_args:
            return CommandClass.READONLY, "git branch 列表"
        if any(arg in ("-d", "-D", "-m", "-M", "--delete", "--move") for arg in sub_args):
            return CommandClass.MUTATING, "git branch 会删除/重命名分支"
        if any(arg in ("--list", "-l") for arg in sub_args):
            return CommandClass.READONLY, "git branch --list"
        list_flags = {
            "-a", "-r", "-v", "-vv", "--all", "--remotes", "--verbose",
            "--show-current",
        }
        if sub_args and all(arg in list_flags for arg in sub_args):
            return CommandClass.READONLY, "git branch 列表"
        return CommandClass.MUTATING, "git branch 可能创建分支"

    if sub == "remote":
        if not sub_args or sub_args[0] in ("-v", "--verbose", "show", "get-url"):
            return CommandClass.READONLY, "git remote 只读"
        return CommandClass.MUTATING, "git remote 会修改配置"

    if sub == "config":
        read_flags = {"--get", "--get-all", "--list", "-l"}
        write_flags = {
            "--unset", "--unset-all", "--add", "--replace-all",
            "--rename-section", "--remove-section",
        }
        if any(arg in read_flags for arg in sub_args) and not any(
            arg in write_flags or ("=" in arg and not arg.startswith("-"))
            for arg in sub_args
        ):
            return CommandClass.READONLY, "git config 读取"
        return CommandClass.MUTATING, "git config 可能写入"

    if sub == "stash":
        if sub_args and sub_args[0] in ("list", "show"):
            return CommandClass.READONLY, f"git stash {sub_args[0]}"
        return CommandClass.MUTATING, "git stash 会修改状态"

    if sub == "tag":
        mutation_flags = {
            "-a", "-d", "-m", "-f", "-s",
            "--delete", "--annotate", "--message", "--force", "--sign",
        }
        if any(arg in mutation_flags for arg in sub_args):
            return CommandClass.MUTATING, "git tag 会创建/删除标签"
        if not sub_args or any(arg in ("-l", "--list") for arg in sub_args):
            return CommandClass.READONLY, "git tag 列表"
        if all(
            arg in ("-n", "--contains", "--points-at", "--merged", "--no-merged")
            for arg in sub_args
        ):
            return CommandClass.READONLY, "git tag 列表"
        return CommandClass.MUTATING, "git tag 可能创建标签"

    if sub == "clean":
        if any(arg in ("-n", "--dry-run") for arg in sub_args):
            return CommandClass.READONLY, "git clean 演练"
        return CommandClass.MUTATING, "git clean 会删除文件"

    return CommandClass.MUTATING, f"git {sub} 会修改仓库"
