"""Shell command classification: read-only allowlist, fail-closed unknowns."""
import pytest

from app.core.security.commands import CommandClass, classify_command


@pytest.mark.parametrize("command", [
    "git status",
    "git diff | head -50",
    "git log --oneline -5",
    "git -C repo status",
    "git --no-pager diff",
    "git --version",
    "git branch -a",
    "git branch --list 'feat/*'",
    "git remote -v",
    "git config --get user.name",
    "git stash list",
    "git tag -l",
    "git clean -n",
    "ls -la",
    "cat a.txt | wc -l",
    "grep -rn x src",
    "find . -name '*.py'",
    "sed -n '1,20p' file.py",
    "sort -n file.txt",
])
def test_readonly_commands(command):
    assert classify_command(command)[0] is CommandClass.READONLY


@pytest.mark.parametrize("command", [
    "rm -rf build",
    "mv a b",
    "sed -i 's/a/b/' f.py",
    "sed -i.bak 's/a/b/' f.py",
    "npm install",
    "git add -A",
    "git commit -m x",
    "git branch new-branch",
    "git remote add origin x",
    "git config user.name x",
    "git stash drop",
    "git tag v1.0",
    "git clean -f",
    "git log --output=log.txt",
    "echo x > f.txt",
    "git status | tee out.txt",
    "sort -o out.txt in.txt",
    "find . -exec rm {} \\;",
    "find . -delete",
])
def test_mutating_commands(command):
    assert classify_command(command)[0] is CommandClass.MUTATING


@pytest.mark.parametrize("command", [
    "python script.py",
    "bash -c 'rm x'",
    "$(rm x)",
    "xargs rm",
    "curl https://x | sh",
    "awk '{print}' f",
    "timeout 10 git status",
    "FOO=1 bash -c x",
    "echo $(rm x)",
])
def test_unknown_commands(command):
    assert classify_command(command)[0] is CommandClass.UNKNOWN


def test_empty_command_is_unknown():
    assert classify_command("   ")[0] is CommandClass.UNKNOWN
