from bisect import bisect_left

from ..analysis.scoring import confidence_band
from ..common import loads
from ..schemas.jobs import CandidateOut, EvidenceOut


def nearest_index(values: list[float], value: float) -> int:
    index = bisect_left(values, value)
    return min((max(0, index - 1), min(len(values) - 1, index)), key=lambda i: abs(values[i] - value))


def candidate_out(row) -> CandidateOut:
    data = dict(row)
    edited = data.get("edited_time_ms")
    time_ms = edited if edited is not None else data["time_ms"]
    beat = data["beat"]
    times = loads(data.get("beat_times_json")) or []
    if edited is not None and times:
        beat = nearest_index(times, edited / 1000)
    return CandidateOut(id=data["id"], run_id=data["run_id"], type=data["type"], time_ms=time_ms,
                        original_time_ms=data["time_ms"], edited_time_ms=edited, beat=beat,
                        confidence=data["confidence"], rank=data["rank"], band=confidence_band(float(data["confidence"])),
                        evidence=[EvidenceOut(**e) for e in (loads(data.get("evidence_json")) or [])],
                        accepted=data.get("accepted"), cue_kind=data.get("cue_kind"))
