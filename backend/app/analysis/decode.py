"""音源デコード（基本設計書 §9.2 decode）。

soundfile を優先し、失敗時は librosa/audioread にフォールバックしてモノラル化する。
重い依存は遅延 import。無音・クリップ検査を行う。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class DecodedAudio:
    y: np.ndarray  # モノラル float32/64, [-1,1]
    sr: int
    duration_sec: float
    is_silent: bool
    clip_ratio: float  # |x|>=0.999 のサンプル比率


def decode_mono(path: str | Path, *, target_sr: int | None = 22050) -> DecodedAudio:
    """音源をモノラルへデコードする。依存未導入時は RuntimeError。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"音源が見つかりません: {p}")

    y, sr = _load(p, target_sr)
    y = np.asarray(y, dtype=float)
    if y.ndim > 1:
        y = y.mean(axis=1)
    if target_sr and sr != target_sr:
        y = _resample(y, sr, target_sr)
        sr = target_sr

    peak = float(np.max(np.abs(y))) if y.size else 0.0
    clip_ratio = float(np.mean(np.abs(y) >= 0.999)) if y.size else 0.0
    return DecodedAudio(
        y=y,
        sr=sr,
        duration_sec=len(y) / sr if sr else 0.0,
        is_silent=peak < 1e-4,
        clip_ratio=clip_ratio,
    )


def _load(p: Path, target_sr: int | None) -> tuple[np.ndarray, int]:
    try:
        import soundfile as sf

        y, sr = sf.read(str(p), always_2d=False)
        return y, int(sr)
    except ImportError:
        pass
    try:
        import librosa

        y, sr = librosa.load(str(p), sr=target_sr, mono=True)
        return y, int(sr)
    except ImportError:
        pass
    if p.suffix.lower() == ".wav":
        return _load_wav_stdlib(p)
    raise RuntimeError(
        "soundfile/librosa が未導入で WAV 以外はデコードできません "
        '(pip install -e ".[analysis]")'
    )


def _load_wav_stdlib(p: Path) -> tuple[np.ndarray, int]:
    """依存なしで PCM WAV を読む（16/32bit 対応、8bit は簡易対応）。"""
    import wave

    with wave.open(str(p), "rb") as w:
        n = w.getnframes()
        sr = w.getframerate()
        ch = w.getnchannels()
        width = w.getsampwidth()
        raw = w.readframes(n)
    dtype = {1: np.uint8, 2: np.int16, 4: np.int32}.get(width)
    if dtype is None:
        raise RuntimeError(f"未対応の WAV ビット深度: {width * 8}bit")
    data = np.frombuffer(raw, dtype=dtype).astype(float)
    if ch > 1:
        data = data.reshape(-1, ch)
    if width == 1:  # 8bit は unsigned (0..255)
        data = (data - 128.0) / 128.0
    else:
        data = data / float(2 ** (8 * width - 1))
    return data, int(sr)


def _resample(y: np.ndarray, sr: int, target_sr: int) -> np.ndarray:
    try:
        import librosa

        return librosa.resample(y, orig_sr=sr, target_sr=target_sr)
    except ImportError:
        # 線形補間の簡易リサンプル（依存なしフォールバック）。
        n = int(round(len(y) * target_sr / sr))
        if n <= 0:
            return y
        xp = np.linspace(0.0, 1.0, num=len(y))
        x = np.linspace(0.0, 1.0, num=n)
        return np.interp(x, xp, y)
