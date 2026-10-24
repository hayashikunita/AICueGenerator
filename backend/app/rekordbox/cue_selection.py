from ..domain.cue_kinds import CUE_LIMITS, expand_cue_kind


def select_export_cues(rows, memory_candidate_ids: list[str] | None = None) -> list[dict]:
    """Select XML entries without changing any saved candidate decisions."""
    decisions = [dict(row) for row in rows]
    selected = None if memory_candidate_ids is None else set(memory_candidate_ids)
    if selected is None:
        groups: dict[str, list[dict]] = {}
        for decision in decisions:
            if decision["cue_kind"] in {"MEMORY", "BOTH"}:
                groups.setdefault(decision["track_id"], []).append(decision)
        selected = set()
        for group in groups.values():
            group.sort(key=lambda d: (-int(d.get("confidence") or 0), int(d.get("rank") or 1),
                                      d["edited_time_ms"] if d.get("edited_time_ms") is not None else d["orig_time_ms"], d["candidate_id"]))
            selected.update(d["candidate_id"] for d in group[:CUE_LIMITS["MEMORY"]])
    else:
        allowed = {d["candidate_id"] for d in decisions if d["cue_kind"] in {"MEMORY", "BOTH"}}
        if len(selected) != len(memory_candidate_ids) or not selected.issubset(allowed):
            raise ValueError("Memory Cueの書き出し対象が変更されています。結果を再取得して選び直してください。")
    output = []
    for decision in decisions:
        for kind in expand_cue_kind(decision["cue_kind"]):
            if kind == "MEMORY" and decision["candidate_id"] not in selected:
                continue
            output.append({**decision, "cue_kind": kind})
    return output
