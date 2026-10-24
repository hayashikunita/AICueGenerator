"""Standalone local inference process; run with the separate AI interpreter.

Only compact energy envelopes leave this process. The original audio is opened
for reading; no stem audio is written and no audio is sent over the network.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import random


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio")
    parser.add_argument("--output", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--vocal-only", action="store_true")
    parser.add_argument("--vocal-end", action="store_true")
    args = parser.parse_args()
    os.environ["TORCH_HOME"] = args.model_dir
    import numpy as np
    import soundfile as sf
    import torch
    import julius
    from demucs_infer.pretrained import get_model
    from demucs_infer.apply import apply_model

    torch.set_num_threads(min(4, os.cpu_count() or 1))
    random.seed(0)
    torch.manual_seed(0)
    model = get_model("htdemucs").cpu().eval()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.prepare:
        output.write_text(json.dumps({"model": "htdemucs", "torch": torch.__version__, "prepared": True}), encoding="utf-8")
        return
    if not args.audio:
        parser.error("--audio is required unless --prepare is selected")
    if args.vocal_only:
        from vocal_scan import scan_vocals
        info = sf.info(args.audio)
        if info.frames <= 0 or info.samplerate <= 0:
            raise ValueError("Empty audio")

        def separate(start, end):
            # Include context on both sides, keeping only the core envelopes.
            # The file and model stay open across windows; no stem audio is saved.
            audio_start = max(0, start - 3)
            audio_end = min(info.duration, end + 3)
            block, source_sr = sf.read(args.audio, start=round(audio_start * info.samplerate),
                stop=round(audio_end * info.samplerate), dtype="float32", always_2d=True)
            if not len(block) or not np.all(np.isfinite(block)):
                raise ValueError("Invalid audio samples")
            wav = torch.from_numpy(block.T.copy())
            wav = wav.repeat(2, 1) if wav.shape[0] == 1 else wav[:2]
            if source_sr != model.samplerate:
                wav = julius.resample_frac(wav, source_sr, model.samplerate)
            reference = wav.mean(dim=0)
            mean, scale = reference.mean(), reference.std()
            if not torch.isfinite(scale) or scale < 1e-8:
                voice = torch.zeros_like(wav)
            else:
                with torch.inference_mode():
                    separated = apply_model(model, ((wav - mean) / scale)[None], device="cpu", shifts=1,
                        overlap=.25, split=True, progress=True, num_workers=0)[0]
                voice = separated[model.sources.index("vocals")] * scale
                del separated
            offset = round((start - audio_start) * model.samplerate)
            length = round((end - start) * model.samplerate)
            hop = round(model.samplerate * .1)
            count = int(np.ceil(end / .1)) - round(start / .1)

            def core_envelope(signal):
                core = signal[..., offset:offset + length]
                padded = torch.nn.functional.pad(core, (0, count * hop - core.shape[-1]))
                return torch.sqrt(padded.reshape(-1, count, hop).square().mean(dim=(0, 2))).tolist()

            return core_envelope(wav), core_envelope(voice)

        result = scan_vocals(info.duration, separate, require_end=args.vocal_end,
            on_window=lambda progress: print("AICUE_SCAN " + json.dumps(progress), flush=True))
        temporary = output.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
        temporary.replace(output)
        return
    data, sr = sf.read(args.audio, dtype="float32", always_2d=True)
    if not len(data) or not np.all(np.isfinite(data)):
        raise ValueError("The audio is empty or contains non-finite samples")
    wav = torch.from_numpy(data.T.copy())
    if wav.shape[0] == 1:
        wav = wav.repeat(2, 1)
    else:
        wav = wav[:2]
    if sr != model.samplerate:
        wav = julius.resample_frac(wav, sr, model.samplerate)
    sr = model.samplerate
    reference = wav.mean(dim=0)
    mean, scale = reference.mean(), reference.std()
    if not torch.isfinite(scale) or scale < 1e-8:
        sources = torch.zeros((len(model.sources), *wav.shape))
    else:
        with torch.inference_mode():
            sources = apply_model(model, ((wav - mean) / scale)[None], device="cpu", shifts=1,
                                  overlap=.25, split=True, progress=True, num_workers=0)[0]
        sources = sources * scale
    hop = max(1, int(sr * .1))

    def envelope(signal):
        # Channel energy avoids cancellation between stereo channels.
        count = (signal.shape[-1] + hop - 1) // hop
        padded = torch.nn.functional.pad(signal, (0, count * hop - signal.shape[-1]))
        return torch.sqrt(padded.reshape(-1, count, hop).square().mean(dim=(0, 2))).tolist()

    result = {"schema": 1, "model": "htdemucs", "hop_sec": hop / sr,
              "duration_sec": wav.shape[-1] / sr, "mix": envelope(wav),
              "stems": {name: envelope(sources[i]) for i, name in enumerate(model.sources)}}
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
    temporary.replace(output)


if __name__ == "__main__":
    main()
