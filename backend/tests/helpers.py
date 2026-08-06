from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


def write_wav(path: Path, y: np.ndarray, sr: int) -> Path:
    """float [-1,1] のモノラル波形を 16bit PCM WAV で書き出す（テスト用）。"""
    y = np.asarray(y, dtype=float)
    clipped = np.clip(y, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path
