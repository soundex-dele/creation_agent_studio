"""Readable tool labels for events and older conversation history."""
import re
import shlex


def _command_label(command, depth=0):
    # This is a conservative display fallback, never a shell/security parser.
    if not isinstance(command, str) or depth > 3:
        return "shell"
    try:
        words = shlex.split(command)
    except ValueError:
        return "shell"
    if not words:
        return "shell"
    executable = words[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
    if executable in {"sh", "bash", "zsh"} and len(words) == 3:
        if words[1] in {"-c", "-lc", "-cl"}:
            return _command_label(words[2], depth + 1)
    # Avoid relabelling pipelines, writes, substitutions or compound commands
    # based solely on their first command.
    if any(character in command for character in "\n\r;|&<>`$"):
        return "shell"
    args = words[1:]
    if executable in {"cat", "head", "tail", "less", "more"}:
        return "read"
    if executable == "sed" and len(args) >= 2 and args[0] == "-n":
        if re.fullmatch(r"\d+(?:,\d+)?p", args[1]) and all(
            not arg.startswith("-") for arg in args[2:]
        ):
            return "read"
    if executable in {"ls", "dir", "tree"}:
        return "list"
    if executable in {"rg", "grep", "egrep", "fgrep"}:
        if any(arg == "--pre" or arg.startswith("--pre=") for arg in args):
            return "shell"
        return "list" if executable == "rg" and "--files" in args else "search"
    return "shell"


def tool_display_name(name, input_value=None, *, command_actions=None):
    """Keep concrete names; specialize Codex's generic execution categories."""
    if name == "file_change":
        return "edit"
    if name != "shell":
        return name
    if isinstance(command_actions, list) and command_actions:
        labels = []
        for action in command_actions:
            label = {
                "read": "read", "search": "search", "listFiles": "list",
            }.get(action.get("type")) if isinstance(action, dict) else None
            if label is None:
                return "shell"
            if label not in labels:
                labels.append(label)
        return " / ".join(labels)
    return _command_label(input_value)


def normalize_tool_metadata(metadata):
    """Label legacy calls without rewriting saved messages or mutating JSON."""
    if not isinstance(metadata, dict):
        return metadata
    result = dict(metadata)
    for key in ("agent", "graphflow"):
        agent = metadata.get(key)
        if not isinstance(agent, dict) or not isinstance(agent.get("tool_calls"), list):
            continue
        result[key] = {
            **agent,
            "tool_calls": [
                {
                    **call,
                    "name": tool_display_name(call.get("name"), call.get("input")),
                } if isinstance(call, dict) and call.get("name") in ("shell", "file_change") else call
                for call in agent["tool_calls"]
            ],
        }
    return result
