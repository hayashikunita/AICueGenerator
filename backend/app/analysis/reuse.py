"""Shared reuse checks for the read-only preview and the analysis worker."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
import hashlib
from pathlib import Path

from ..common import ENGINE_VERSION, dumps
from ..config import get_settings
from ..persistence.repositories import Repository
from ..rekordbox.adapter import open_rekordbox
from ..rekordbox.reader import load_track_analysis
from .ai import load_cached_stems
from .fingerprint import AudioInput, file_analysis_inputs


@dataclass(frozen=True)
class VoiceOptions:
    specialized: bool
    targets: tuple[str, ...]
    needs_ai: bool
    vocal_only: bool

    @property
    def require_end(self) -> bool:
        return "VOCAL_END" in self.targets


def voice_options(params: dict) -> VoiceOptions:
    specialized = params.get("cue_mode") == "INTRO_OUTRO"
    targets = ((params.get("intro_outro") or {}).get("targets", []) if specialized else
               params.get("cue_targets") or [target for target, enabled in
               (("VOCAL_START", params.get("legacy_vocal_start")), ("VOCAL_END", params.get("legacy_vocal_end"))) if enabled])
    vocal_requested = bool({"VOCAL_START", "VOCAL_END"}.intersection(targets))
    return VoiceOptions(specialized, tuple(targets),
                        params.get("analysis_quality") == "AI" and (not specialized or vocal_requested),
                        params.get("ai_scope") == "VOCAL")


def with_source_fingerprint(fingerprint: str, source_fingerprint: str | None) -> str:
    if source_fingerprint:
        return "sha256:" + hashlib.sha256((fingerprint + source_fingerprint).encode("ascii")).hexdigest()
    return fingerprint


def find_reusable_run(
    repo: Repository, track_id: str, path: str, params: dict, *, audio_input: AudioInput,
    source_fingerprint: str | None = None, stem_analysis: dict | None = None,
    engine_version: str = ENGINE_VERSION,
):
    options = voice_options(params)
    if options.needs_ai and stem_analysis is None:
        return None
    fingerprint, _, _ = file_analysis_inputs(
        path, vocal_requested="VOCAL_START" in options.targets, stem_analysis=stem_analysis, audio_input=audio_input,
    )
    cached = repo.find_cached_run(
        track_id=track_id, engine_version=engine_version,
        fingerprint=with_source_fingerprint(fingerprint, source_fingerprint), params=params,
    )
    audio_input.verify(path)
    return cached


def preview_job(repo: Repository, tracks: list[dict], params: dict) -> dict:
    """Check saved results without creating jobs, decoding audio or running AI."""
    options = voice_options(params)
    results = []
    with ExitStack() as stack:
        database = None
        for track in tracks:
            result = {"content_id": track["content_id"], "state": "NEW", "reason": None}
            try:
                path = str(track["path"])
                if not Path(path).is_file():
                    raise ValueError("音源が見つかりません。ファイルの場所を確認してください。")
                saved = repo.get_track_by_content_id(str(track["content_id"]))
                # New tracks and new analysis settings need no audio reads.
                if saved is not None and repo.find_cached_run(
                    track_id=saved["id"], engine_version=ENGINE_VERSION, fingerprint=None, params=params,
                ) is not None:
                    audio_input = AudioInput.read(path)
                    stems = load_cached_stems(path, vocal_only=options.vocal_only, require_end=options.require_end,
                                              audio_input=audio_input) if options.needs_ai else None
                    source_fingerprint = None
                    if params.get("analysis_source") == "REKORDBOX":
                        if database is None:
                            settings = get_settings()
                            database = stack.enter_context(open_rekordbox(path=settings.rekordbox_db_path, key=settings.rekordbox_key))
                        snapshot = load_track_analysis(database, str(track["content_id"]), path)
                        source_fingerprint = hashlib.sha256(dumps(snapshot).encode("utf-8")).hexdigest()
                    if find_reusable_run(repo, saved["id"], path, params, audio_input=audio_input,
                                         source_fingerprint=source_fingerprint, stem_analysis=stems) is not None:
                        result["state"] = "CACHED"
            except Exception as exc:  # A bad file must not hide the other tracks.
                result.update(state="UNAVAILABLE", reason=str(exc))
            results.append(result)
    return {"total": len(results), "cached": sum(r["state"] == "CACHED" for r in results),
            "new": sum(r["state"] == "NEW" for r in results),
            "unavailable": sum(r["state"] == "UNAVAILABLE" for r in results), "tracks": results}
