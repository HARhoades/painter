"""How a planned grade reads on screen (pure functions, easy to test)."""
from __future__ import annotations

from painter.services.grading import GradePlan, GradePlanSet, PlannedGrade


def sent_grade(it: PlannedGrade) -> str:
    if "excuse" in it.fields:
        return "EXCUSED"
    return it.fields.get("posted_grade", "")


def comment_text(it: PlannedGrade) -> str:
    if it.fields.get("text_comment"):
        return it.fields["text_comment"]
    if it.comment_skipped:
        return "Already on Canvas, not re-sent"
    return ""


def plan_meta(plan: GradePlan) -> str:
    a = plan.assignment
    gt = (a.get("grading_type") or "points").replace("_", " ")
    out_of = f", out of {a['points_possible']:g}" if a.get("points_possible") else ""
    sec = (plan.section or {}).get("name") or plan.source.section_title or "no section"
    who = f" · instructor {plan.source.instructor}" if plan.source.instructor else ""
    return f"{a.get('name', plan.source.assignment_title)} · {gt}{out_of} · section {sec}{who}"


def manual_posting(plan: GradePlan) -> bool:
    return bool(plan.assignment.get("post_manually"))


def other_notes(plan: GradePlan) -> list[str]:
    return [n for n in plan.notes if "posted manually" not in n]


def warnings(plans: GradePlanSet) -> int:
    return sum(len(it.warnings) for p in plans.plans for it in p.to_send)


def summary(plans: GradePlanSet) -> dict:
    items = [it for p in plans.plans for it in p.to_send]
    return {
        "updates": len(items),
        "grades": sum("posted_grade" in it.fields or "excuse" in it.fields for it in items),
        "excused": sum("excuse" in it.fields for it in items),
        "comments": sum("text_comment" in it.fields for it in items),
        "changes": [(it.student, it.grade_before, sent_grade(it)) for it in items
                    if any(w.startswith("replaces existing grade") for w in it.warnings)],
        "assignments": sorted({p.assignment.get("name", "") for p in plans.plans}),
        "sections": sorted({(p.section or {}).get("name", "") for p in plans.plans} - {""}),
        "manual": any(manual_posting(p) for p in plans.plans),
        "files": len(plans.plans),
    }
