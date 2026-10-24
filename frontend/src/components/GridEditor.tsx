import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { GridPlan, GridPreview } from "../types";
import { pauseOtherAudio } from "../audio";

function timeLabel(ms: number) {
  return `${Math.floor(ms / 60000)}:${(ms / 1000 % 60).toFixed(3).padStart(6, "0")}`;
}

export function GridEditor({ contentId, path, onSaved, onBusy }: {
  contentId: string; path: string; onSaved: () => void; onBusy: (busy: boolean) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [grid, setGrid] = useState<GridPreview | null>(null);
  const [firstBeat, setFirstBeat] = useState(1);
  const [plan, setPlan] = useState<GridPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<{ message: string; backup_dir: string } | null>(null);
  const [playing, setPlaying] = useState(false);
  const [audioError, setAudioError] = useState("");
  const [expiresAt, setExpiresAt] = useState(0);
  const [now, setNow] = useState(Date.now());
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const seekRef = useRef<number | null>(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    if (!plan) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [plan]);

  const selectBeat = (beat: number) => {
    setFirstBeat(beat); setPlan(null); setSaved(null); setError("");
  };
  const selectedBeat = grid?.beats.find((beat) => beat.before === firstBeat);
  const expired = !!plan && now >= expiresAt;
  const audition = () => {
    const audio = audioRef.current;
    if (!audio || !selectedBeat) return;
    setAudioError("");
    const seconds = selectedBeat.time_ms / 1000;
    seekRef.current = audio.readyState < 1 ? seconds : null;
    try {
      audio.currentTime = seconds;
      void audio.play().catch((error: unknown) => {
        if (error instanceof Error && error.name === "AbortError") return;
        if (mounted.current) setAudioError("試聴できませんでした。音源の保存場所とブラウザが対応する形式か確認してください。");
      });
    } catch {
      setAudioError("試聴できませんでした。もう一度お試しください。");
    }
  };

  const run = async (action: () => Promise<void>) => {
    if (busy) return;
    setBusy(true); onBusy(true); setError("");
    try { await action(); }
    catch (e) { if (mounted.current) { setError(e instanceof Error ? e.message : String(e)); setPlan(null); } }
    finally { if (mounted.current) setBusy(false); onBusy(false); }
  };

  const refresh = () => run(async () => {
    audioRef.current?.pause();
    seekRef.current = null; setPlaying(false);
    setPlan(null);
    setGrid(null);
    setAudioError("");
    setSaved(null);
    const result = await api.gridPreview(contentId, path);
    if (mounted.current) { setGrid(result); setFirstBeat(1); }
  });
  const toggle = () => {
    if (expanded) { audioRef.current?.pause(); seekRef.current = null; setPlaying(false); }
    setExpanded(!expanded);
    if (!expanded && !grid) refresh();
  };
  const confirm = () => run(async () => {
    setSaved(null);
    const result = await api.gridPlan(contentId, path, firstBeat);
    if (mounted.current) {
      setGrid(result); setPlan(result);
      setExpiresAt(Date.now() + result.expires_in * 1000); setNow(Date.now());
    }
  });
  const save = () => {
    if (!plan || expired) return;
    const planId = plan.plan_id;
    audioRef.current?.pause();
    seekRef.current = null; setPlaying(false);
    run(async () => {
      const result = await api.gridApply(contentId, planId);
      if (mounted.current) {
        setSaved(result); setPlan(null); setGrid(null); setFirstBeat(1); onSaved();
      }
    });
  };

  return <div className="grid-editor">
    <button type="button" className="secondary tiny" disabled={busy} aria-expanded={expanded} onClick={toggle}>小節頭を調整 {expanded ? "▴" : "▾"}</button>
    {expanded && <div>
      <p className="field-help">小節頭にしたい拍をクリックしてください。曲全体の1拍目が切り替わります。試聴と選択だけでは保存されません。</p>
      {grid && <>
        <label htmlFor="grid-first-beat">現在の何拍目を小節頭にしますか？</label>
        <select id="grid-first-beat" value={firstBeat} disabled={busy} onChange={(e) => selectBeat(Number(e.target.value))}>
          {[1, 2, 3, 4].map((n) => <option key={n} value={n}>{n === 1 ? "1拍目（変更なし）" : `${n}拍目 → 新しい1拍目`}</option>)}
        </select>
        <div className="grid-step-controls" aria-label="小節頭の移動">
          <button type="button" className="secondary tiny" disabled={busy} onClick={() => selectBeat((firstBeat + 2) % 4 + 1)}>← 1拍前</button>
          <button type="button" className="secondary tiny" disabled={busy} onClick={() => selectBeat(firstBeat % 4 + 1)}>1拍後 →</button>
          <button type="button" className="secondary tiny" disabled={busy || firstBeat === 1} onClick={() => selectBeat(1)}>元に戻す</button>
        </div>
        <p className="field-help">先頭8拍 · クリックして選択 · 赤い「1」が小節頭</p>
        <div className="grid-beats" aria-label="小節頭のプレビュー">{grid.beats.map((beat) => {
          const after = (beat.before - firstBeat + 4) % 4 + 1;
          return <button type="button" key={beat.time_ms} className={`grid-beat${after === 1 ? " downbeat" : ""}`} disabled={busy} aria-pressed={after === 1} aria-label={`${timeLabel(beat.time_ms)} 現在の${beat.before}拍目を小節頭にする`} onClick={() => selectBeat(beat.before)}>
            <span className="grid-beat-before">元 {beat.before}</span><strong>{after}</strong><span>{timeLabel(beat.time_ms)}</span>
          </button>;
        })}</div>
        <p className="grid-change-summary" role="status">{firstBeat === 1 ? "現在の小節頭のままです" : `現在の${firstBeat}拍目を新しい1拍目に変更`}{selectedBeat ? ` · ${timeLabel(selectedBeat.time_ms)} から試聴` : ""}</p>
        <div className="grid-audition">
          <button type="button" className="secondary tiny" disabled={busy || !selectedBeat} onClick={audition}>▶ 選んだ小節頭から試聴</button>
          <button type="button" className="secondary tiny" disabled={!playing} onClick={() => audioRef.current?.pause()}>停止</button>
          <audio ref={audioRef} src={api.libraryAudioUrl(contentId, path)} controls preload="none" aria-label="小節頭を確認する音源"
            onLoadedMetadata={(e) => { if (seekRef.current !== null) { e.currentTarget.currentTime = seekRef.current; seekRef.current = null; } }}
            onPlay={(e) => { pauseOtherAudio(e.currentTarget); setPlaying(true); }} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)}
            onError={() => { setPlaying(false); setAudioError("音源を読み込めませんでした。保存場所と音源の形式を確認してください。"); }} />
          {audioError && <p className="error" role="alert">{audioError}</p>}
        </div>
        <p className="field-help">拍時刻・BPMは維持します。保存前に rekordbox を終了してください。元の解析ファイルを自動バックアップします。</p>
        <button type="button" className="secondary tiny" disabled={busy || firstBeat === 1} onClick={confirm}>変更内容を確認</button>
      </>}
      <button type="button" className="secondary tiny grid-refresh" disabled={busy} onClick={refresh}>グリッドを再取得</button>
      {plan && <div className="grid-confirm" role="region" aria-label="小節頭の保存確認">
        <strong>{plan.title}</strong>
        <p className="field-help">曲全体（{plan.beat_count}拍）の現在の{plan.first_beat}拍目を、新しい1拍目に変更します。</p>
        <p className="field-help">曲名・音源・プレイリスト・既存Cue・フレーズは保持します。</p>
        <p className={expired ? "error" : "field-help"} role={expired ? "alert" : undefined}>{expired ? "確認の有効期限が切れました。「変更内容を確認」を押し直してください。" : `確認の有効期限：あと${Math.ceil(Math.max(0, expiresAt - now) / 60000)}分`}</p>
        {plan.blocked_reason && <p role="status" className="error">{plan.blocked_reason}</p>}
        <button type="button" disabled={busy || expired || !!plan.blocked_reason} onClick={save}>rekordbox へ小節頭を保存</button>
        <button type="button" className="secondary tiny" disabled={busy} onClick={() => setPlan(null)}>調整に戻る</button>
        {plan.blocked_reason && <p className="field-help">rekordbox を終了後、「変更内容を確認」を押してください。</p>}
      </div>}
      {busy && <p role="status" className="field-help">処理しています…</p>}
      {error && <p role="alert" className="error">{error}</p>}
      {saved && <div role="status"><p>{saved.message}</p><p className="field-help">バックアップ：{saved.backup_dir}</p><p className="field-help">新しい小節頭で候補を作るには、解析を開始してください。過去の結果は保持します。</p></div>}
    </div>}
  </div>;
}
