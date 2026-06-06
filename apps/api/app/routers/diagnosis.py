"""SDS v1 Case 查询 API。"""

from fastapi import APIRouter, HTTPException

from app.diagnosis.registry import ALL_CASE_IDS, CASE_REGISTRY

router = APIRouter(prefix="/api/v1/diagnosis", tags=["diagnosis"])


@router.get("/cases")
async def list_cases(problem_space: str | None = None, escalation: str | None = None):
    items = []
    for case_id in ALL_CASE_IDS:
        c = CASE_REGISTRY[case_id]
        if problem_space and c.problem_space != problem_space:
            continue
        if escalation and c.escalation != escalation:
            continue
        items.append(
            {
                "case_id": c.case_id,
                "name": c.name,
                "problem_space": c.problem_space,
                "intents": list(c.intents),
                "escalation": c.escalation,
                "user_goal": c.user_goal,
                "rules": list(c.rules),
            }
        )
    return {"count": len(items), "cases": items}


@router.get("/cases/{case_id}")
async def get_case(case_id: str):
    c = CASE_REGISTRY.get(case_id)
    if not c:
        raise HTTPException(404, f"Case {case_id} 不存在")
    from app.diagnosis.matrices import CASE_ACTION_MATRIX, resolve_actions

    actions = resolve_actions(case_id)
    return {
        "case_id": c.case_id,
        "name": c.name,
        "problem_space": c.problem_space,
        "intents": list(c.intents),
        "escalation": c.escalation,
        "user_goal": c.user_goal,
        "rules": list(c.rules),
        "action_ids": CASE_ACTION_MATRIX.get(case_id, []),
        "recommended_actions": [
            {"action_id": a.action_id, "title": a.title, "tool": a.tool_name} for a in actions
        ],
    }


@router.get("/stats")
async def diagnosis_stats():
    by_ps: dict[str, int] = {}
    by_esc: dict[str, int] = {}
    for c in CASE_REGISTRY.values():
        by_ps[c.problem_space] = by_ps.get(c.problem_space, 0) + 1
        by_esc[c.escalation] = by_esc.get(c.escalation, 0) + 1
    return {
        "total_cases": len(CASE_REGISTRY),
        "by_problem_space": by_ps,
        "by_escalation": by_esc,
    }
