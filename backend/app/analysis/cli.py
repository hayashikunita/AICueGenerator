r"""解析コア評価 CLI（基本設計書 §18 アクション4）。

合成 EDM 信号または実音源ファイルに対して解析パイプラインを実行し、
種類別 Top-3 候補と信頼度・根拠を表示する。

使い方 (backend で):
    .\.venv\Scripts\python.exe -m app.analysis.cli --synth
    .\.venv\Scripts\python.exe -m app.analysis.cli --file "track.wav" --bpm 128
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from ..domain.models import AnalysisResult
from .pipeline import analyze_file, analyze_waveform
from .scoring import confidence_band
from .synth import synthesize_edm


def _to_dict(result: AnalysisResult) -> dict:
    return {
        "fingerprint": result.fingerprint,
        "duration_sec": round(result.duration_sec, 3),
        "bpm": result.beatgrid.bpm,
        "beat_source": result.beatgrid.source.value,
        "beat_count": result.beatgrid.beat_count,
        "warnings": list(result.warnings),
        "candidates": [
            {
                "cue_type": c.cue_type.value,
                "rank": c.rank,
                "time_sec": round(c.time_sec, 3),
                "beat_index": c.beat_index,
                "confidence": c.confidence,
                "band": confidence_band(c.confidence),
                "evidence": [asdict(e) for e in c.evidence],
            }
            for c in result.candidates
        ],
    }


def _print(result: AnalysisResult) -> None:
    print(
        f"bpm={result.beatgrid.bpm} source={result.beatgrid.source.value} "
        f"beats={result.beatgrid.beat_count} dur={result.duration_sec:.1f}s"
    )
    if result.warnings:
        print("warnings:", "; ".join(result.warnings))
    print(f"{'CUE':<12}{'rank':<5}{'time':>8}{'beat':>7}{'conf':>7}  band")
    for c in result.candidates:
        print(
            f"{c.cue_type.value:<12}{c.rank:<5}{c.time_sec:>8.2f}"
            f"{c.beat_index:>7}{c.confidence:>7.1f}  {confidence_band(c.confidence)}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="解析コア評価 CLI")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--synth", action="store_true", help="合成 EDM 信号で評価")
    src.add_argument("--file", help="実音源ファイルを解析")
    parser.add_argument("--bpm", type=float, default=None, help="既知 BPM（一様グリッド）")
    parser.add_argument("--seed", type=int, default=0, help="合成信号のシード")
    parser.add_argument("--json", help="レポート JSON 出力先")
    args = parser.parse_args(argv)

    if args.synth:
        track = synthesize_edm(bpm=args.bpm or 128.0, seed=args.seed)
        result = analyze_waveform(
            track.y, track.sr, bpm=track.bpm, fingerprint=f"synth:seed={args.seed}"
        )
    else:
        try:
            result = analyze_file(args.file, bpm=args.bpm)
        except (FileNotFoundError, RuntimeError) as exc:
            print(f"解析失敗: {exc}", file=sys.stderr)
            return 2

    _print(result)
    if args.json:
        from pathlib import Path

        Path(args.json).write_text(
            json.dumps(_to_dict(result), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"JSON: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
