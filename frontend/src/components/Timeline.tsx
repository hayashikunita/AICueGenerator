import { useEffect, useMemo, useRef, useState } from "react";
import type { Candidate } from "../types";
import { fmtTime } from "../cues";
import { useCueMeta } from "./CueColors";

// 音源を Web Audio API でデコードして波形ピークを算出するフック。
function useWaveform(url: string | null | undefined, buckets = 600) {
  const [peaks, setPeaks] = useState<number[] | null>(null);

  useEffect(() => {
    if (!url) {
      setPeaks(null);
      return;
    }
    let cancelled = false;
    setPeaks(null);
    (async () => {
      try {
        const res = await fetch(url);
        if (!res.ok) return;
        const buf = await res.arrayBuffer();
        const Ctx =
          window.AudioContext ||
          (window as unknown as { webkitAudioContext: typeof AudioContext })
            .webkitAudioContext;
        const ctx = new Ctx();
        const audio = await ctx.decodeAudioData(buf);
        const ch = audio.getChannelData(0);
        const block = Math.floor(ch.length / buckets) || 1;
        const out: number[] = [];
        let peak = 0;
        for (let i = 0; i < buckets; i++) {
          let max = 0;
          const start = i * block;
          for (let j = 0; j < block; j++) {
            const v = Math.abs(ch[start + j] || 0);
            if (v > max) max = v;
          }
          out.push(max);
          if (max > peak) peak = max;
        }
        void ctx.close();
        if (!cancelled) setPeaks(peak > 0 ? out.map((v) => v / peak) : out);
      } catch {
        if (!cancelled) setPeaks(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [url, buckets]);

  return peaks;
}

// 波形をキャンバス描画する。
function Waveform({ peaks }: { peaks: number[] }) {
  const ref = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const parent = canvas.parentElement;
    if (!parent) return;
    const w = parent.clientWidth;
    const h = parent.clientHeight;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);
    const mid = h / 2;
    const bw = w / peaks.length;
    ctx.fillStyle = "rgba(120,150,200,0.28)";
    for (let i = 0; i < peaks.length; i++) {
      const bh = Math.max(1, peaks[i] * (h * 0.9));
      ctx.fillRect(i * bw, mid - bh / 2, Math.max(1, bw - 0.5), bh);
    }
  }, [peaks]);

  return <canvas ref={ref} className="timeline-wave" />;
}

// 候補をトラック時間軸上にマーカー表示し、音源があれば再生できるようにする。
export function Timeline({
  candidates,
  audioUrl,
}: {
  candidates: Candidate[];
  audioUrl?: string | null;
}) {
  const [hover, setHover] = useState<Candidate | null>(null);
  const cueMeta = useCueMeta();
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [audioDurSec, setAudioDurSec] = useState(0);
  const [currentSec, setCurrentSec] = useState(0);
  const [playing, setPlaying] = useState(false);
  const peaks = useWaveform(audioUrl);

  // 音源を切り替えたら再生位置をリセットする。
  useEffect(() => {
    setCurrentSec(0);
    setPlaying(false);
    setAudioDurSec(0);
  }, [audioUrl]);

  const durationMs = useMemo(() => {
    if (audioDurSec > 0) return audioDurSec * 1000;
    const max = candidates.reduce((m, c) => Math.max(m, c.time_ms), 0);
    // 末尾に余白を持たせ、最低でも 1 分幅を確保する。
    return Math.max(max * 1.06, 60000);
  }, [audioDurSec, candidates]);

  const ticks = useMemo(() => {
    const step = durationMs > 240000 ? 60000 : 30000;
    const out: number[] = [];
    for (let t = 0; t <= durationMs; t += step) out.push(t);
    return out;
  }, [durationMs]);

  if (candidates.length === 0) return null;

  const seekTo = (sec: number) => {
    const a = audioRef.current;
    const clamped = Math.max(0, Math.min(sec, durationMs / 1000));
    if (a) a.currentTime = clamped;
    setCurrentSec(clamped);
  };

  const togglePlay = () => {
    const a = audioRef.current;
    if (!a) return;
    if (a.paused) void a.play();
    else a.pause();
  };

  const playCue = (c: Candidate) => {
    seekTo(c.time_ms / 1000);
    void audioRef.current?.play();
  };

  const onTrackClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!audioUrl) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const ratio = (e.clientX - rect.left) / rect.width;
    seekTo((ratio * durationMs) / 1000);
  };

  const playheadPct = Math.min(100, ((currentSec * 1000) / durationMs) * 100);

  return (
    <div className="timeline">
      {audioUrl && (
        <div className="timeline-transport">
          <button
            className="play-btn"
            onClick={togglePlay}
            aria-label={playing ? "一時停止" : "再生"}
          >
            {playing ? "⏸" : "▶"}
          </button>
          <span className="mono time-now">{fmtTime(currentSec * 1000)}</span>
          <span className="muted">/</span>
          <span className="mono muted">{fmtTime(durationMs)}</span>
          <span className="muted tiny" style={{ marginLeft: "auto" }}>
            バーをクリックでシーク・キューをクリックで再生
          </span>
        </div>
      )}

      <div
        className={`timeline-track${audioUrl ? " seekable" : ""}`}
        onClick={onTrackClick}
      >
        {peaks && <Waveform peaks={peaks} />}

        {ticks.map((t) => (
          <div key={t} className="timeline-tick" style={{ left: `${(t / durationMs) * 100}%` }}>
            <span className="timeline-tick-label">{fmtTime(t)}</span>
          </div>
        ))}

        {audioUrl && (
          <div className="timeline-playhead" style={{ left: `${playheadPct}%` }} />
        )}

        {candidates.map((c) => {
          const m = cueMeta(c.type);
          const left = (c.time_ms / durationMs) * 100;
          const h = 34 + (c.confidence / 100) * 42;
          return (
            <button
              key={c.id}
              className={`timeline-marker band-${c.band}`}
              style={{
                left: `${left}%`,
                height: `${h}%`,
                background: m.color,
                boxShadow: `0 0 10px ${m.glow}`,
              }}
              onClick={(e) => {
                e.stopPropagation();
                if (audioUrl) playCue(c);
              }}
              onMouseEnter={() => setHover(c)}
              onMouseLeave={() => setHover((h2) => (h2?.id === c.id ? null : h2))}
              aria-label={`${m.label} ${fmtTime(c.time_ms)}`}
            >
              <span className="timeline-marker-icon">{m.icon}</span>
            </button>
          );
        })}
      </div>

      {audioUrl && (
        <audio
          ref={audioRef}
          src={audioUrl}
          preload="metadata"
          onLoadedMetadata={(e) => {
            const d = e.currentTarget.duration;
            if (Number.isFinite(d) && d > 0) setAudioDurSec(d);
          }}
          onTimeUpdate={(e) => setCurrentSec(e.currentTarget.currentTime)}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onEnded={() => setPlaying(false)}
        />
      )}

      {hover && (
        <div className="timeline-tip">
          <span className="chip" style={{ background: cueMeta(hover.type).color }}>
            {cueMeta(hover.type).icon} {cueMeta(hover.type).label}
          </span>
          <span className="mono">{fmtTime(hover.time_ms)}</span>
          <span className="muted">信頼度 {hover.confidence}</span>
          <span className={`badge ${hover.band}`}>{hover.band}</span>
        </div>
      )}
    </div>
  );
}
