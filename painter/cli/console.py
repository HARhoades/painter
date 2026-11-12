"""The command line's Reporter: prints, exactly as the tool always has."""
from __future__ import annotations

from contextlib import contextmanager
import signal
import sys

from painter.services.grading import GradePlan, _preview
from painter.services.organize import OrganizePlan


class ConsoleReporter:
    """Prints. While a task runs inside stoppable(), the first Ctrl+C asks it
    to stop at its next safe point (logs and manifest still written); a
    second Ctrl+C stops at once."""

    def __init__(self):
        self._stop = False

    @contextmanager
    def stoppable(self):
        def first_press(signum, frame):
            self._stop = True
            print("\nStopping after the current step (Ctrl+C again to stop now) ...",
                  file=sys.stderr, flush=True)
            signal.signal(signal.SIGINT, signal.default_int_handler)
        try:
            old = signal.signal(signal.SIGINT, first_press)
        except ValueError:                  # not the main thread: leave Ctrl+C alone
            yield
            return
        try:
            yield
        finally:
            signal.signal(signal.SIGINT, old)
            self._stop = False

    def info(self, text: str = "", end: str = "\n") -> None:
        print(text, end=end, flush=not end)

    def warning(self, text: str) -> None:
        print(text, file=sys.stderr)

    def progress(self, done: int, total: int, label: str = "") -> None:
        pass            # the CLI prints its own per-item lines instead

    def event(self, e) -> None:
        pass            # typed events are for a GUI; the text lines say the same

    def cancelled(self) -> bool:
        return self._stop


def grade_plan_lines(plan: GradePlan) -> list[str]:
    """The plan for one grade file, as the console shows it."""
    lines: list[str] = []
    a, gf = plan.assignment, plan.source
    scale = a.get("grading_type") or ""
    if scale == "points" and a.get("points_possible") is not None:
        scale = f"points, out of {a['points_possible']:g}"
    lines.append(f"\n{gf.path.name}  (course {plan.course_id})")
    lines.append(f"  Assignment {a['id']}  {a.get('name', '')}  ({scale})")
    if plan.section:
        inst = f"  instructor {gf.instructor}" if gf.instructor else ""
        lines.append(f"  Section    {plan.section['id']}  {plan.section.get('name', '')}{inst}")
    for note in plan.notes:
        lines.append(f"  note: {note}")
    for it in plan.items:
        parts = []
        if "excuse" in it.fields:
            parts.append(f"grade {it.grade_before or '-'} -> EXCUSED")
        elif "posted_grade" in it.fields:
            parts.append(f"grade {it.grade_before or '-'} -> {it.fields['posted_grade']}")
        if "text_comment" in it.fields:
            parts.append(f"comment {_preview(it.fields['text_comment'])}")
        elif it.comment_skipped:
            parts.append("comment already on Canvas, not re-sent")
        if not it.fields:
            parts.append("(nothing to send)")
        lines.append(f"    {it.student} ({it.user_id}):  " + "   ".join(parts))
        for w in it.warnings:
            lines.append(f"      ! {w}")
    lines.append(f"  {len(plan.to_send)} student(s) to update")
    return lines


def organize_plan_lines(plan: OrganizePlan, dry_run: bool) -> tuple[list[str], list[str]]:
    """(stdout lines, stderr lines) describing an organize plan."""
    out = [f"{'Dry run: ' if dry_run else ''}{plan.verb.capitalize()} {plan.src_root} -> "
           f"{plan.dest_root} into {len(plan.section_dirs)} section folder(s)"]
    for it in plan.items:
        if it.uid is None:
            continue
        out.append(f"  {it.label} -> {it.target.relative_to(plan.dest_root)}"
                   f"{'  (by name)' if it.how == 'name' else ''}{it.note}"
                   f"{'  SKIPPED, exists' if it.exists else ''}")
    out.append("")
    for sec in sorted(plan.section_dirs, key=str.casefold):
        out.append(f"  {plan.section_dirs[sec]:<20} {plan.counts.get(sec, 0):>4} item(s)")
    err: list[str] = []
    unmatched = plan.unmatched
    if unmatched:
        err.append(f"\n{len(unmatched)} item(s) not matched to the roster, left in place:")
        err += [f"  {it.label}  ({it.how})" for it in unmatched]
    if plan.ambiguous:
        err.append(f"\nnote: {plan.ambiguous} student(s) are in more than "
                   "one section; pass --section to choose")
    return out, err
