"""Shared help panel text and chat aliases."""

from __future__ import annotations

HELP_PROMPTS: tuple[tuple[str, str], ...] = (
    (
        "\u5185\u5b58\u600e\u4e48\u6837",
        "\u67e5\u770b\u670d\u52a1\u5668\u548c nanobot \u5185\u5b58\uff0c\u4e0d\u8d70\u6a21\u578b",
    ),
    (
        "\u670d\u52a1\u72b6\u6001",
        "\u68c0\u67e5 sidecar / \u80fd\u529b\u5065\u5eb7",
    ),
    (
        "\u4eca\u5929\u5148\u770b\u4ec0\u4e48",
        "\u4eca\u65e5\u6587\u7ae0\u3001LOF\u3001\u4efb\u52a1\u5f02\u5e38\u6458\u8981",
    ),
    (
        "\u6a21\u578b\u82b1\u8d39",
        "\u67e5\u770b OBP \u6d88\u8017\u548c\u6765\u6e90\u7edf\u8ba1",
    ),
    (
        "LOF \u6709\u673a\u4f1a\u5417",
        "\u67e5\u770b LOF/QDII \u5b9e\u65f6\u770b\u677f\u548c\u62a5\u544a",
    ),
    (
        "\u4eca\u5929\u70ed\u70b9 / \u65b0\u95fb\u7b80\u62a5",
        "\u67e5\u770b\u8fc7\u6ee4\u540e\u7684\u70ed\u70b9\u65b0\u95fb",
    ),
    (
        "\u6536\u4e00\u4e0b <\u94fe\u63a5>",
        "\u6293\u53d6\u7f51\u9875\u8fdb\u77e5\u8bc6\u6536\u4ef6\u7bb1",
    ),
    (
        "\u8fd9\u4e2a\u503c\u5f97\u770b\u5417 <\u94fe\u63a5>",
        "\u751f\u6210\u8f7b\u91cf\u51b3\u7b56\u5305",
    ),
    (
        "\u8bb0\u4f4f <\u5185\u5bb9>",
        "\u5199\u5165\u672c\u5730\u8bb0\u5fc6",
    ),
    (
        "\u8bb0\u5fc6\u72b6\u6001 / \u641c\u8bb0\u5fc6 <\u5173\u952e\u8bcd>",
        "\u67e5\u770b\u6216\u68c0\u7d22\u8bb0\u5fc6",
    ),
    (
        "\u4f60\u6700\u8fd1\u8fdb\u5316\u4e86\u5417",
        "\u67e5\u770b\u8fdb\u5316\u65e5\u5fd7",
    ),
)

SLASH_COMMANDS: tuple[tuple[str, str], ...] = (
    ("/new", "\u5f00\u542f\u65b0\u4f1a\u8bdd"),
    ("/stop", "\u505c\u6b62\u5f53\u524d\u4efb\u52a1"),
    ("/restart", "\u91cd\u542f nanobot"),
    ("/status", "\u67e5\u770b\u8fd0\u884c\u72b6\u6001"),
    ("/model [preset]", "\u67e5\u770b\u6216\u5207\u6362\u6a21\u578b\u9884\u8bbe"),
    ("/history [n]", "\u67e5\u770b\u6700\u8fd1 n \u6761\u5bf9\u8bdd"),
    ("/goal <goal>", "\u5f00\u542f\u957f\u76ee\u6807\u4efb\u52a1"),
    ("/dream", "\u624b\u52a8\u89e6\u53d1\u8bb0\u5fc6\u6574\u7406"),
    ("/dream-log", "\u67e5\u770b\u6700\u8fd1\u8bb0\u5fc6\u53d8\u66f4"),
    ("/dream-restore", "\u56de\u6eda\u8bb0\u5fc6\u7248\u672c"),
    ("/skill", "\u5217\u51fa\u53ef\u7528\u6280\u80fd"),
    ("/help", "\u663e\u793a\u8fd9\u4e2a\u9762\u677f"),
    (
        "/pairing [list|approve <code>|deny <code>|revoke <user_id>]",
        "\u7ba1\u7406\u804a\u5929\u914d\u5bf9\u8bf7\u6c42",
    ),
)

HELP_ALIASES: tuple[str, ...] = (
    "help",
    "menu",
    "nanobot help",
    "\u5e2e\u52a9",
    "\u83dc\u5355",
    "\u6307\u4ee4",
    "\u6307\u4ee4\u5217\u8868",
    "\u4f7f\u7528\u8bf4\u660e",
    "\u600e\u4e48\u7528",
)

CAPABILITY_MENU_ALIASES: tuple[str, ...] = (
    "\u4f60\u4f1a\u4ec0\u4e48",
    "\u4f60\u80fd\u505a\u4ec0\u4e48",
    "\u4f60\u80fd\u5e72\u4ec0\u4e48",
    "\u6211\u80fd\u8ba9\u4f60\u505a\u4ec0\u4e48",
    "\u80fd\u529b\u5217\u8868",
    "\u80fd\u529b\u83dc\u5355",
    "\u529f\u80fd\u5217\u8868",
    "\u529f\u80fd\u83dc\u5355",
    "\u6280\u80fd\u5217\u8868",
    "\u6280\u80fd\u83dc\u5355",
    "nanobot\u4f1a\u4ec0\u4e48",
    "nanobot\u80fd\u505a\u4ec0\u4e48",
)

CAPABILITY_SUFFIXES: tuple[str, ...] = (
    "\u6709\u54ea\u4e9b",
    "\u662f\u4ec0\u4e48",
    "\u5217\u51fa\u6765",
)


def build_help_text() -> str:
    """Build the user-facing help panel shared across channels."""
    lines = [
        "\U0001f9ed Nanobot \u4f7f\u7528\u9762\u677f\uff08\u672a\u8c03\u7528 LLM\uff09",
        "",
        "\u4f60\u53ef\u4ee5\u76f4\u63a5\u8fd9\u6837\u95ee\uff1a",
        *[f"- {prompt} \u2014 {description}" for prompt, description in HELP_PROMPTS],
        "",
        "\u5feb\u6377\u547d\u4ee4\uff1a",
        *[f"{command} \u2014 {description}" for command, description in SLASH_COMMANDS],
        "",
        "\u7f51\u9875\u5165\u53e3\uff1ahttp://150.158.121.88:8093/sidecars",
    ]
    return "\n".join(lines)


def is_capability_menu_query(compact_text: str) -> bool:
    """Return True when compact text asks what nanobot can do."""
    if compact_text in CAPABILITY_MENU_ALIASES:
        return True
    return "\u80fd\u529b" in compact_text and compact_text.endswith(CAPABILITY_SUFFIXES)
