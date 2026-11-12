"""The command line's Reporter: prints, exactly as the tool always has."""
from __future__ import annotations

import sys

from painter.services.grading import GradePlan, _preview


class ConsoleReporter:
    def info(self, text: str = "", end: str = "\n") -> None:
        print(text, end=end, flush=not end)

    def warning(self, text: str) -> None:
        print(text, file=sys.stderr)

    def progress(self, done: int, total: int, label: str = "") -> None:
        pass            # the CLI prints its own per-item lines instead

    def cancelled(self) -> bool:
        return False    # Ctrl-C raises KeyboardInterrupt instead


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
