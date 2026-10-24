from typing import Any


def cue_preset(params: dict[str, Any], cue_type: str) -> dict[str, Any] | None:
    return (params.get("cue_settings") or {}).get(cue_type) or params.get("cue_default")


def preferred_kind(params: dict[str, Any], cue_type: str) -> str:
    return (cue_preset(params, cue_type) or {}).get("cue_kind", "MEMORY")
