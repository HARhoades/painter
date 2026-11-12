"""Old flag-style command lines -> the phase 4 subcommands.

The golden scenarios were written for the old flags; this turns each into
the equivalent `painter <command>` line, which is what the transcripts now
record. It is also the old-flag -> new-command table in docs/manual.md.
"""
from __future__ import annotations

COMMANDS = {"list", "download", "roster", "organize", "grades", "quiz"}

WITH_VALUE = {
    "--base-url", "--course", "--assignment", "--out", "--student", "--section", "--tz",
    "--log-dir", "--post-grades", "--assignment-label", "--ay", "--term",
    "--grade-file-dir", "--roster-csv", "--organize", "--roster", "--organize-to",
    "--browser-profile", "--browser-channel", "--connect-browser", "--signin-timeout",
    "--page-timeout", "--delay", "--limit", "--export-timeout",
}
GLOBAL = {"--base-url", "--course", "--tz"}
RENAMED = {
    "--assignment-label": "--label", "--grade-file-dir": "--dir", "--organize-to": "--to",
    "--quiz-uploads": "--uploads", "--export-timeout": "--timeout",
    "--browser-profile": "--profile", "--browser-channel": "--channel",
    "--connect-browser": "--connect",
}
MODE_FLAGS = {"--post-grades", "--make-grade-files", "--roster-csv", "--organize",
              "--export-quiz", "--browser-uploads", "--list-assignments",
              "--list-sections", "--list-students"}


def translate(argv: list[str]) -> list[str]:
    if not argv or any(a in COMMANDS for a in argv):
        return list(argv)                     # already a new-style line (or empty)
    pairs, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a in WITH_VALUE and i + 1 < len(argv):
            pairs.append((a, argv[i + 1]))
            i += 2
        else:
            pairs.append((a, None))
            i += 1
    flags = {f for f, _ in pairs}
    globals_ = [x for f, v in pairs if f in GLOBAL for x in (f, v)]
    rest = [(f, v) for f, v in pairs if f not in GLOBAL and f not in MODE_FLAGS]

    if "--organize" in flags:
        head = ["organize", dict(pairs)["--organize"]]
    elif "--post-grades" in flags:
        head = ["grades", "post"] + [v for f, v in pairs if f == "--post-grades"]
    elif "--make-grade-files" in flags:
        head = ["grades", "new"]
    elif "--roster-csv" in flags:
        head = ["roster", dict(pairs)["--roster-csv"]]
    elif "--export-quiz" in flags:
        head = ["quiz", "export"]
    elif "--browser-uploads" in flags:
        head = ["quiz", "uploads"]
    elif "--list-sections" in flags:
        head = ["list", "sections"]
    elif "--list-students" in flags:
        head = ["list", "students"]
    elif "--list-assignments" in flags:
        head = ["list", "assignments"]
    else:
        head = ["download"]
    tail = []
    for f, v in rest:
        tail.append(RENAMED.get(f, f))
        if v is not None:
            tail.append(v)
    return globals_ + head + tail
