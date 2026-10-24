import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useEffect, useRef } from "react";
import type { AiStatus, AnalysisInfo, CueMode, CueTarget, RekordboxTrack } from "../types";
import { CUE_TARGETS } from "../cueTargets";
import { useToast } from "./Toast";
import { PlaylistBrowser } from "./PlaylistBrowser";
import { GridEditor } from "./GridEditor";
import { CuePresetFields } from "./CuePresetFields";
import { useCueColors } from "./CueColors";
import { CUE_PREFERENCES_KEY, loadCuePreferences } from "../cuePresets";
import type { CuePreset } from "../types";
import { BAR_FIELDS, INTRO_OUTRO_KEY, loadIntroOutro } from "../introOutro";
import { IntroOutroSettingsPanel } from "./IntroOutroSettingsPanel";

const cleanPath = (value: string) => value.trim().replace(/^"(.*)"$/, "$1");

export function NewJobForm({ onCreated }: { onCreated: (jobId: string) => void }) {
  const [source, setSource] = useState<"library" | "path">("library");
  const [libraryMode, setLibraryMode] = useState<"search" | "playlist">("search");
  const [path, setPath] = useState("");
  const [selected, setSelected] = useState<RekordboxTrack | null>(null);
  const [batchMode, setBatchMode] = useState(false);
  const [batchTracks, setBatchTracks] = useState<RekordboxTrack[]>([]);
  const [batchAnalysis, setBatchAnalysis] = useState<Record<string, AnalysisInfo>>({});
  const [batchChecking, setBatchChecking] = useState(false);
  const analysisCache = useRef(new Map<string, AnalysisInfo>());
  const [contentId, setContentId] = useState("");
  const [bpm, setBpm] = useState("");
  const [barsPerPhrase, setBarsPerPhrase] = useState("16");
  const [phraseUnit, setPhraseUnit] = useState<"beats" | "bars">("beats");
  const [topK, setTopK] = useState("3");
  const [cueMode, setCueMode] = useState<CueMode>("LEGACY");
  const [legacyVocal, setLegacyVocal] = useState(() => { try { return localStorage.getItem("aicue.legacyVocalStart") === "true"; } catch { return false; } });
  useEffect(() => { try { localStorage.setItem("aicue.legacyVocalStart", String(legacyVocal)); } catch { /* Optional preference. */ } }, [legacyVocal]);
  const [legacyVocalEnd, setLegacyVocalEnd] = useState(() => { try { return localStorage.getItem("aicue.legacyVocalEnd") === "true"; } catch { return false; } });
  useEffect(() => { try { localStorage.setItem("aicue.legacyVocalEnd", String(legacyVocalEnd)); } catch { /* Optional preference. */ } }, [legacyVocalEnd]);
  const targetMode = cueMode === "PURPOSE";
  const specialized = cueMode === "INTRO_OUTRO";
  const [introOutro, setIntroOutro] = useState(loadIntroOutro);
  const specializedVocal = specialized && introOutro.targets.some((target) => ["VOCAL_START", "VOCAL_END"].includes(target));
  useEffect(() => { try { localStorage.setItem(INTRO_OUTRO_KEY, JSON.stringify(introOutro)); } catch { /* Optional preferences. */ } }, [introOutro]);
  const [cueTargets, setCueTargets] = useState<CueTarget[]>(CUE_TARGETS.filter((target) => target.value !== "VOCAL_END").map((target) => target.value));
  const vocalRequested = specializedVocal || targetMode && cueTargets.some((target) => ["VOCAL_START", "VOCAL_END"].includes(target)) || cueMode === "LEGACY" && (legacyVocal || legacyVocalEnd);
  const vocalEndRequested = specialized ? introOutro.targets.includes("VOCAL_END") : targetMode ? cueTargets.includes("VOCAL_END") : legacyVocalEnd;
  const [cuePreferences, setCuePreferences] = useState(loadCuePreferences);
  const { exportColor } = useCueColors();
  const commonCue: CuePreset = cuePreferences.common ?? { cue_kind: "MEMORY", memory_color: exportColor("MEMORY"), hot_color: exportColor("HOT")! };
  useEffect(() => { try { localStorage.setItem(CUE_PREFERENCES_KEY, JSON.stringify(cuePreferences)); } catch { /* Settings remain usable without storage. */ } }, [cuePreferences]);
  const [analysisBusy, setBusy] = useState(false);
  const [gridBusy, setGridBusy] = useState(false);
  const [playlistBusy, setPlaylistBusy] = useState(false);
  const busy = analysisBusy || gridBusy || playlistBusy;
  const [rbQuery, setRbQuery] = useState("");
  const [rbResults, setRbResults] = useState<RekordboxTrack[]>([]);
  const [rbSearching, setRbSearching] = useState(false);
  const [searchMessage, setSearchMessage] = useState("");
  const [error, setError] = useState("");
  const [analysisSource, setAnalysisSource] = useState<"REKORDBOX" | "AUDIO">("REKORDBOX");
  const [analysisQuality, setAnalysisQuality] = useState<"STANDARD" | "AI">("STANDARD");
  const [aiStatus, setAiStatus] = useState<AiStatus | null>(null);
  const qualityChosen = useRef(false);
  useEffect(() => {
    let active = true;
    api.aiStatus().then((status) => {
      if (!active) return;
      setAiStatus(status);
      if (!qualityChosen.current) {
        let saved = "";
        try { saved = localStorage.getItem("aicue.analysisQuality") ?? ""; } catch { /* Optional preference. */ }
        setAnalysisQuality(status.available && saved !== "STANDARD" ? "AI" : "STANDARD");
      }
    }).catch(() => { if (active) setAiStatus({ available: false, model: "htdemucs", local_only: true, reason: "AI環境の状態を取得できませんでした。通常解析を使用できます。" }); });
    return () => { active = false; };
  }, []);
  const [analysis, setAnalysis] = useState<AnalysisInfo | null>(null);
  const [checkingAnalysis, setCheckingAnalysis] = useState(false);
  const [analysisError, setAnalysisError] = useState("");
  const [analysisRefresh, setAnalysisRefresh] = useState(0);
  const toast = useToast();

  useEffect(() => {
    let active = true;
    setAnalysis(null);
    setAnalysisError("");
    if (batchMode || analysisSource !== "REKORDBOX" || !contentId || !cleanPath(path)) {
      setCheckingAnalysis(false);
      return;
    }
    setCheckingAnalysis(true);
    api.rekordboxAnalysis(contentId, cleanPath(path))
      .then((result) => { if (active) { setAnalysis(result); if (!result.available) setAnalysisError(result.reason || "rekordbox で曲を解析してから再取得してください。"); } })
      .catch((e) => { if (active) setAnalysisError(`解析情報を確認できませんでした: ${e}`); })
      .finally(() => { if (active) setCheckingAnalysis(false); });
    return () => { active = false; };
  }, [analysisSource, contentId, path, analysisRefresh, batchMode]);

  useEffect(() => {
    let active = true;
    if (!batchMode || analysisSource !== "REKORDBOX" || !batchTracks.length) { setBatchChecking(false); return; }
    setBatchChecking(true);
    setBatchAnalysis({});
    let index = 0;
    const check = async () => {
      while (active && index < batchTracks.length) {
        const track = batchTracks[index++];
        const key = `${track.content_id}:${track.path}`;
        let info = analysisCache.current.get(key);
        if (!info) {
          try { info = await api.rekordboxAnalysis(track.content_id, track.path!); }
          catch (e) { info = { source: "REKORDBOX", available: false, reason: String(e) }; }
          if (active) analysisCache.current.set(key, info);
        }
        if (active) setBatchAnalysis((previous) => ({ ...previous, [track.content_id]: info! }));
      }
    };
    void Promise.all(Array.from({ length: Math.min(3, batchTracks.length) }, check)).finally(() => { if (active) setBatchChecking(false); });
    return () => { active = false; };
  }, [batchMode, batchTracks, analysisSource, analysisRefresh]);

  const searchRekordbox = async (event: FormEvent) => {
    event.preventDefault();
    if (rbSearching) return;
    setRbSearching(true);
    setSearchMessage("");
    setRbResults([]);
    try {
      const res = await api.searchRekordbox(rbQuery.trim(), 50);
      setRbResults(res.available ? res.tracks : []);
      setSearchMessage(!res.available
        ? `rekordbox に接続できません。ファイルパスからも解析できます。${res.reason ? ` (${res.reason})` : ""}`
        : res.tracks.length === 0 ? "見つかりませんでした。曲名やアーティスト名を変えて検索してください。"
        : `${res.tracks.length} 件を表示しています。解析する曲を選んでください。`);
    } catch (e) {
      setSearchMessage(`検索に失敗しました: ${e}`);
    } finally {
      setRbSearching(false);
    }
  };

  const pickTrack = (track: RekordboxTrack) => {
    if (!track.path) return;
    if (batchMode) {
      setBatchTracks((previous) => previous.some((t) => t.content_id === track.content_id) ? previous.filter((t) => t.content_id !== track.content_id) : previous.length < 200 ? [...previous, track] : previous);
      setError("");
      return;
    }
    setSelected(track);
    setPath(track.path);
    setContentId(track.content_id);
    setBpm(track.bpm ? String(track.bpm) : "");
    setError("");
  };

  const addTracks = (tracks: RekordboxTrack[]) => {
    const merged = [...batchTracks];
    for (const track of tracks) if (track.path && !merged.some((t) => t.content_id === track.content_id || t.path?.toLowerCase() === track.path?.toLowerCase())) merged.push(track);
    if (merged.length > 200) { setError("一度に解析できるのは200曲までです。選択曲を減らしてください。"); return; }
    setBatchTracks(merged);
    setError("");
  };

  const batchReady = batchTracks.length > 0 && !batchChecking && (analysisSource === "AUDIO" || batchTracks.every((t) => batchAnalysis[t.content_id]?.available));
  const missingTargets = targetMode ? !cueTargets.length : specialized && !introOutro.targets.length;
  const invalidBars = specialized && BAR_FIELDS.some((field) => !Number.isInteger(introOutro[field]) || introOutro[field] < 1 || introOutro[field] > 128);

  const changeSource = (next: "library" | "path") => {
    setAnalysisSource(next === "library" ? "REKORDBOX" : "AUDIO");
    setSource(next);
    setBatchMode(false);
    setBatchTracks([]);
    setPath("");
    setSelected(null);
    setContentId("");
    setBpm("");
    setError("");
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    if (missingTargets) { setError("作りたいCueの位置を1つ以上選んでください。"); return; }
    if (vocalEndRequested && !aiStatus?.vocal_end) {
      setError("ボーカルの終わりを追加するには、アプリを再起動して更新を反映してください。");
      return;
    }
    if (cueMode === "LEGACY" && legacyVocal && !aiStatus?.legacy_vocal_start) {
      setError("従来の候補へ歌い始めを追加するには、アプリを再起動して更新を反映してください。");
      return;
    }
    if (analysisQuality === "AI" && vocalRequested && !aiStatus?.vocal_scan) {
      setError("ボーカルの段階解析を利用するにはアプリの再起動が必要です。実行中の解析を終了してから更新を反映してください。");
      return;
    }
    if (invalidBars) { setError("小節数は1〜128の整数で入力してください。"); return; }
    if (batchMode ? !batchReady : analysisSource === "REKORDBOX" && (checkingAnalysis || !analysis?.available)) {
      setError("rekordbox の解析済みグリッドを確認してから開始してください。");
      return;
    }
    const filePath = cleanPath(path);
    if (!batchMode && !filePath) {
      setError("解析する曲を選ぶか、音源ファイルのパスを入力してください。");
      return;
    }
    if (!batchMode && bpm.trim() && (!Number.isFinite(Number(bpm)) || Number(bpm) <= 0)) {
      setError("BPM は 0 より大きい数値を入力するか、空欄にしてください。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const { job_id } = await api.createJob(
        {
          analysis_source: analysisSource,
          analysis_quality: analysisQuality === "AI" && vocalRequested ? "AI" : "STANDARD",
          ai_scope: "VOCAL",
          cue_mode: cueMode,
          ...(cueMode === "LEGACY" ? { legacy_vocal_start: legacyVocal, legacy_vocal_end: legacyVocalEnd, cue_settings: Object.fromEntries(Object.entries(cuePreferences.targets).filter(([target]) => target === "VOCAL_START" && legacyVocal || target === "VOCAL_END" && legacyVocalEnd)) } : {}),
          ...(specialized ? { intro_outro: introOutro, cue_settings: Object.fromEntries(Object.entries(cuePreferences.targets).filter(([target]) => introOutro.targets.includes(target as CueTarget))) } : {}),
          bpm: batchMode ? null : analysisSource === "REKORDBOX" ? analysis?.bpm ?? null : bpm.trim() ? Number(bpm) : null,
          ...(specialized ? { beats_per_phrase: 4 } : phraseUnit === "beats" ? { beats_per_phrase: Number(barsPerPhrase) * 4 } : { bars_per_phrase: Number(barsPerPhrase) }),
          top_k: Number(topK),
          ...(cuePreferences.common ? { cue_default: cuePreferences.common } : {}),
          ...(targetMode ? { cue_targets: cueTargets, end_alignment_bars: cuePreferences.endBars,
            cue_settings: Object.fromEntries(Object.entries(cuePreferences.targets).filter(([target]) => cueTargets.includes(target as CueTarget))) } : {}),
        },
        batchMode ? batchTracks.map((t) => ({ content_id: t.content_id, path: t.path!, format: t.path!.split(".").pop()?.toUpperCase() || "WAV" })) : [{ content_id: contentId.trim() || filePath, path: filePath, format: filePath.split(".").pop()?.toUpperCase() || "WAV" }],
      );
      toast.push("success", `${batchMode ? `${batchTracks.length}曲の一括` : ""}解析を開始しました。結果画面で進捗を確認できます。`);
      onCreated(job_id);
    } catch (e) {
      setError(`解析を開始できませんでした: ${e}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel" aria-labelledby="new-analysis-title">
      <h2 id="new-analysis-title">1. 解析する曲を選ぶ</h2>
      <div className="source-switch" aria-label="曲の選び方">
        <button type="button" className={source === "library" ? "" : "secondary"} aria-pressed={source === "library"} disabled={busy || rbSearching} onClick={() => changeSource("library")}>rekordbox から</button>
        <button type="button" className={source === "path" ? "" : "secondary"} aria-pressed={source === "path"} disabled={busy || rbSearching} onClick={() => changeSource("path")}>ファイルパスから</button>
      </div>
      {source === "library" && (
        <>
        <div className="library-switch" aria-label="解析する曲数">
          <button type="button" className="secondary tiny" aria-pressed={!batchMode} disabled={busy} onClick={() => setBatchMode(false)}>1曲ずつ</button>
          <button type="button" className="secondary tiny" aria-pressed={batchMode} disabled={busy} onClick={() => { setBatchMode(true); if (!batchTracks.length && selected) setBatchTracks([selected]); }}>複数曲を一括</button>
        </div>
        <div className="library-switch" aria-label="ライブラリの表示方法">
          <button type="button" className="secondary tiny" aria-pressed={libraryMode === "search"} disabled={busy || rbSearching} onClick={() => setLibraryMode("search")}>曲を検索</button>
          <button type="button" className="secondary tiny" aria-pressed={libraryMode === "playlist"} disabled={busy || rbSearching} onClick={() => setLibraryMode("playlist")}>プレイリストから</button>
        </div>
        {libraryMode === "playlist" ? <PlaylistBrowser onPick={pickTrack} selectedId={batchMode ? undefined : selected?.content_id} selectedIds={batchMode ? batchTracks.map((t) => t.content_id) : undefined} onPickMany={batchMode ? addTracks : undefined} onBusy={setPlaylistBusy} disabled={busy} /> : (
        <form onSubmit={searchRekordbox}>
          <label htmlFor="track-search">曲名・アーティスト・アルバム</label>
          <div className="search-row">
            <input id="track-search" value={rbQuery} placeholder="曲名などを入力" onChange={(e) => setRbQuery(e.target.value)} disabled={busy || rbSearching} />
            <button type="submit" className="secondary" disabled={rbSearching || busy}>{rbSearching ? "検索中…" : "検索"}</button>
          </div>
          <p className="field-help" role="status">{searchMessage || "空欄で検索すると、ライブラリの曲を一覧表示します。"}</p>
          {batchMode && rbResults.length > 0 && <button type="button" className="secondary tiny" disabled={busy} onClick={() => addTracks(rbResults)}>表示中の曲をまとめて選ぶ</button>}
          {rbResults.length > 0 && <div className="rb-results" aria-label="曲の検索結果">
            {rbResults.map((t) => <button type="button" key={t.content_id} className={`rb-item ${(batchMode ? batchTracks.some((item) => item.content_id === t.content_id) : selected?.content_id === t.content_id) ? "selected" : ""}`} disabled={!t.path || busy || (batchMode && batchTracks.length >= 200 && !batchTracks.some((item) => item.content_id === t.content_id))} aria-pressed={batchMode ? batchTracks.some((item) => item.content_id === t.content_id) : selected?.content_id === t.content_id} onClick={() => pickTrack(t)}>
              <span className="rb-title">{(batchMode ? batchTracks.some((item) => item.content_id === t.content_id) : selected?.content_id === t.content_id) ? "✓ " : batchMode ? "＋ " : ""}{t.title ?? "(無題)"}</span>
              <span className="rb-meta">{t.artist ?? "アーティスト不明"}{t.bpm ? ` · ${t.bpm} BPM` : ""}{!t.path ? " · 音源の場所が不明" : ""}</span>
            </button>)}
          </div>}
        </form>
        )}
        </>
      )}
      <form onSubmit={submit}>
        <fieldset disabled={busy}>
          {batchMode && <div className="batch-selection" aria-label="一括解析の選択曲">
            <div className="section-heading"><strong>選択中 {batchTracks.length} / 200曲</strong><button type="button" className="secondary tiny" disabled={!batchTracks.length} onClick={() => setBatchTracks([])}>全曲を外す</button></div>
            <p className="field-help">検索やプレイリストを切り替えて曲を追加できます。選んだ目的を全曲に適用します。</p>
            <ul className="batch-track-list">{batchTracks.map((t) => <li key={t.content_id}><div><strong>{t.title || t.path?.split(/[\\/]/).pop()}</strong><span className={`field-help ${batchAnalysis[t.content_id]?.available ? "ready" : ""}`}>{analysisSource === "AUDIO" ? "音源から独自解析" : !batchAnalysis[t.content_id] ? "確認中…" : batchAnalysis[t.content_id].available ? `✓ 解析済み · ${batchAnalysis[t.content_id].bpm} BPM` : batchAnalysis[t.content_id].reason || "解析済みグリッドがありません"}</span></div><button type="button" className="secondary tiny" aria-label={`${t.title || t.content_id}を選択から外す`} onClick={() => setBatchTracks((previous) => previous.filter((item) => item.content_id !== t.content_id))}>外す</button></li>)}</ul>
            {!!batchTracks.length && analysisSource === "REKORDBOX" && <div className="row"><button type="button" className="secondary tiny" disabled={batchChecking} onClick={() => { analysisCache.current.clear(); setAnalysisRefresh((n) => n + 1); }}>全曲の解析情報を再取得</button>{!batchChecking && batchTracks.some((t) => !batchAnalysis[t.content_id]?.available) && <button type="button" className="secondary tiny" onClick={() => setBatchTracks((previous) => previous.filter((t) => batchAnalysis[t.content_id]?.available))}>解析できない曲を外す</button>}</div>}
          </div>}
          {source === "path" && <>
            <label htmlFor="audio-path">音源ファイルのパス</label>
            <input id="audio-path" value={path} placeholder="C:\Music\track.wav" onChange={(e) => { setPath(e.target.value); setError(""); }} aria-describedby="path-help" required />
            <p id="path-help" className="field-help">エクスプローラーで音源を右クリック →「パスのコピー」を貼り付け。引用符付きでも使えます。</p>
          </>}
          {!batchMode && path && <div className="selected-track"><span className="eyebrow">選択中の曲</span><strong>{selected?.title || cleanPath(path).split(/[\\/]/).pop()}</strong>{selected?.artist && <span className="muted">{selected.artist}</span>}</div>}
          {!batchMode && analysisSource === "REKORDBOX" && path && <div className="analysis-source-info">
            <strong>rekordbox の解析情報</strong>
            {checkingAnalysis ? <p className="field-help" role="status">拍位置・小節頭を確認しています…</p> : analysis?.available ? <p className="field-help">BPM {analysis.bpm} · {analysis.beat_count} 拍 · {analysis.downbeat_count} 小節頭<br />フレーズ {analysis.phrase_count ?? 0} 件 · 既存 Cue {analysis.existing_cues?.length ?? 0} 件{analysis.key ? ` · キー ${analysis.key}` : ""}</p> : null}
            {analysisError && <p className="error" role="alert">{analysisError}</p>}
            {analysis?.warnings?.map((warning) => <p key={warning} className="field-help">{warning}</p>)}
            <button type="button" className="secondary tiny" disabled={checkingAnalysis} onClick={() => setAnalysisRefresh((n) => n + 1)}>解析情報を再取得</button>
            <GridEditor key={`${contentId}:${path}`} contentId={contentId} path={cleanPath(path)} onBusy={setGridBusy} onSaved={() => { analysisCache.current.clear(); setAnalysisRefresh((n) => n + 1); }} />
          </div>}
          <div className="cue-target-settings">
            <h3>作りたいCueの位置</h3>
            <div className="cue-common-preset">
              <strong>Cueの種類と書き出す色（共通設定）</strong>
              <CuePresetFields label="共通設定" value={commonCue} onChange={(value) => setCuePreferences((previous) => ({ ...previous, common: value }))} />
              {cuePreferences.common && <button type="button" className="secondary tiny" onClick={() => setCuePreferences((previous) => ({ ...previous, common: null }))}>共通の色設定に戻す</button>}
              <p className="field-help">従来の候補にも使えます。候補は確認後に「設定どおりに採用」で採用します。色はXMLにも記録します。</p>
            </div>
            <div className="source-switch cue-mode-switch" aria-label="Cue候補の作り方">
              <button type="button" className={cueMode === "LEGACY" ? "" : "secondary"} aria-pressed={cueMode === "LEGACY"} onClick={() => setCueMode("LEGACY")}>従来の候補</button>
              <button type="button" className={targetMode ? "" : "secondary"} aria-pressed={targetMode} onClick={() => setCueMode("PURPOSE")}>目的から選ぶ</button>
              <button type="button" className={specialized ? "" : "secondary"} aria-pressed={specialized} onClick={() => setCueMode("INTRO_OUTRO")}>イントロアウトロ特化</button>
            </div>
            {specialized && <IntroOutroSettingsPanel value={introOutro} onChange={setIntroOutro} preferences={cuePreferences} onPreferences={setCuePreferences} common={commonCue} />}
            {cueMode === "LEGACY" && <div className="cue-target-option legacy-vocal-option">
              <label><input type="checkbox" id="legacy-vocal-start" checked={legacyVocal} onChange={(event) => setLegacyVocal(event.target.checked)} /><span>歌い始めも追加する</span></label>
              <p className="field-help">Intro End・Break・Build・Drop・Outroの候補と一緒に歌い始めを探します。AI補助ではボーカルの段階解析を使い、未検出なら歌い始めを省略します。歌い始めは最寄りの拍へ合わせます。</p>
              {legacyVocal && <details className="cue-target-preset"><summary>{cuePreferences.targets.VOCAL_START ? "個別設定" : "共通設定"}：{(cuePreferences.targets.VOCAL_START ?? commonCue).cue_kind === "HOT" ? "Hot Cue" : (cuePreferences.targets.VOCAL_START ?? commonCue).cue_kind === "BOTH" ? "両方" : "Memory Cue"} · 種類・色を変更</summary>
                <CuePresetFields label="歌い始め" value={cuePreferences.targets.VOCAL_START ?? commonCue} onChange={(value) => setCuePreferences((previous) => ({ ...previous, targets: { ...previous.targets, VOCAL_START: value } }))} />
                {cuePreferences.targets.VOCAL_START && <button type="button" className="secondary tiny" onClick={() => setCuePreferences((previous) => { const targets = { ...previous.targets }; delete targets.VOCAL_START; return { ...previous, targets }; })}>この目的を共通設定に戻す</button>}
              </details>}
            </div>}
            {cueMode === "LEGACY" && <div className="cue-target-option legacy-vocal-end-option">
              <label><input type="checkbox" id="legacy-vocal-end" checked={legacyVocalEnd} onChange={(event) => setLegacyVocalEnd(event.target.checked)} /><span>ボーカルの終わりも追加する</span></label>
              <p className="field-help">AI補助で曲末まで確認し、最後の継続する声の終わりを最寄りの拍へ合わせます。途中の歌の休みでは終了しません。特定できない場合は省略します。</p>
              {legacyVocalEnd && <details className="cue-target-preset"><summary>{cuePreferences.targets.VOCAL_END ? "個別設定" : "共通設定"}：{(cuePreferences.targets.VOCAL_END ?? commonCue).cue_kind === "HOT" ? "Hot Cue" : (cuePreferences.targets.VOCAL_END ?? commonCue).cue_kind === "BOTH" ? "両方" : "Memory Cue"} · 種類・色を変更</summary>
                <CuePresetFields label="ボーカルの終わり" value={cuePreferences.targets.VOCAL_END ?? commonCue} onChange={(value) => setCuePreferences((previous) => ({ ...previous, targets: { ...previous.targets, VOCAL_END: value } }))} />
                {cuePreferences.targets.VOCAL_END && <button type="button" className="secondary tiny" onClick={() => setCuePreferences((previous) => { const targets = { ...previous.targets }; delete targets.VOCAL_END; return { ...previous, targets }; })}>この目的を共通設定に戻す</button>}
              </details>}
            </div>}
            {targetMode && <>
              <div className="cue-target-options">{CUE_TARGETS.map((target) => <div className="cue-target-option" key={target.value}>
                <label><input type="checkbox" value={target.value} checked={cueTargets.includes(target.value)} onChange={(e) => setCueTargets((current) => e.target.checked ? [...current, target.value] : current.filter((value) => value !== target.value))} /><span>{target.label}</span></label>
                {cueTargets.includes(target.value) && <details className="cue-target-preset"><summary>{cuePreferences.targets[target.value] ? "個別設定" : "共通設定"}：{(cuePreferences.targets[target.value] ?? commonCue).cue_kind === "HOT" ? "Hot Cue" : (cuePreferences.targets[target.value] ?? commonCue).cue_kind === "BOTH" ? "両方" : "Memory Cue"} · 種類・色を変更</summary>
                  <CuePresetFields label={target.label} value={cuePreferences.targets[target.value] ?? commonCue} onChange={(value) => setCuePreferences((previous) => ({ ...previous, targets: { ...previous.targets, [target.value]: value } }))} />
                  {cuePreferences.targets[target.value] && <button type="button" className="secondary tiny" onClick={() => setCuePreferences((previous) => { const targets = { ...previous.targets }; delete targets[target.value]; return { ...previous, targets }; })}>この目的を共通設定に戻す</button>}
                </details>}
              </div>)}</div>
              <div className="row"><button type="button" className="secondary tiny" onClick={() => setCueTargets(CUE_TARGETS.map((target) => target.value))}>すべて選ぶ</button><button type="button" className="secondary tiny" onClick={() => setCueTargets([])}>選択を解除</button></div>
              <label>イントロ／アウトロの終わりを合わせる単位<select aria-label="終わりの位置を合わせる小節数" value={cuePreferences.endBars} onChange={(event) => setCuePreferences((previous) => ({ ...previous, endBars: Number(event.target.value) as 1 | 4 | 8 | 16 }))}>{[1, 4, 8, 16].map((bars) => <option value={bars} key={bars}>{bars}小節{bars === 8 ? "（8 bar）" : ""}</option>)}</select></label>
              <p className="field-help">終わりは最初の小節頭から数え、指定した小節数の区切りで区間末尾以前の位置へ合わせます。小節頭や区切りが取れない場合は理由を表示します。</p>
              <p className="field-help">自動候補を試聴・調整してから、Hot Cue／Memory Cue／両方で採用します。自動では採用・保存しません。</p>
              <p className="field-help">サビはChorusフレーズを優先。8小節前は実グリッドで計算します。歌い始めは同名LRCの歌詞時刻を優先し、AI補助では分離ボーカルの開始も調べます。特定できない場合はVerse先頭の仮候補です。</p>
            </>}
          </div>
          <div hidden={specialized && !specializedVocal}>
          <label htmlFor="analysis-quality">候補の判定方法</label>
          <select id="analysis-quality" value={analysisQuality} onChange={(event) => {
            const next = event.target.value as "STANDARD" | "AI";
            qualityChosen.current = true;
            setAnalysisQuality(next);
            try { localStorage.setItem("aicue.analysisQuality", next); } catch { /* Optional preference. */ }
          }} aria-describedby="analysis-quality-help">
            <option value="AI" disabled={!aiStatus?.available}>AI補助（ボーカルを検出）</option>
            <option value="STANDARD">通常（フレーズ・音色・和音の変化を照合）</option>
          </select>
          <p id="analysis-quality-help" className="field-help">{analysisQuality === "AI" ? vocalEndRequested ? "PC内で30秒ずつ曲末までボーカルを確認します。最後の声を探すため、歌い始めを検出しても途中で分離を省略しません。拍位置・小節頭は選んだ解析の基準を使います。" : "歌い始めを選ぶと、PC内で先頭から30秒ずつボーカルを確認します。継続する声を確認できたら残りの分離を省略し、見つからなければ曲末まで調べます。ボーカルの項目が未選択なら音源分離を行いません。拍位置・小節頭は選んだ解析の基準を使います。" : specializedVocal ? "歌い始めは同名LRCの歌詞時刻から探します。歌詞時刻がない場合は省略するため、声を検出するにはAI補助を選んでください。ボーカルの終わりは通常解析では省略します。" : "フレーズ情報と音量・音色・和音の変化、離れた区間の繰り返しから候補を評価します。歌い始めはLRC、なければVerseの仮候補です。ボーカルの終わりはAI補助で検出します。"}</p>
          {aiStatus && !aiStatus.available && <p className="field-help">{aiStatus.reason}</p>}
          {vocalEndRequested && <p className="field-help">ボーカルの終わりにはAI補助が必要です。曲末までの全範囲を調べるため、歌い始めだけの解析より時間がかかります。全曲の分離結果が保存済みなら再利用します。通常解析では終わりを推測せず省略します。</p>}
          </div>
          <div hidden={specialized}>
          <label htmlFor="phrase-length">キュー候補を探す単位</label>
          <div className="beat-presets" aria-label="よく使う解析単位">
            {[4, 8, 16, 32, 64].map((beats) => <button key={beats} type="button" className="secondary tiny" aria-pressed={Number(barsPerPhrase) * 4 === beats} onClick={() => setBarsPerPhrase(String(beats / 4))}>{beats} Beat</button>)}
          </div>
          <div className="search-row">
            <select id="phrase-length" value={Number(barsPerPhrase) * (phraseUnit === "beats" ? 4 : 1)} onChange={(e) => setBarsPerPhrase(String(Number(e.target.value) / (phraseUnit === "beats" ? 4 : 1)))} aria-describedby="phrase-length-help">
              {[1, 2, 4, 8, 16, 32].map((bars) => <option key={bars} value={bars * (phraseUnit === "beats" ? 4 : 1)}>{phraseUnit === "beats" ? `${bars * 4} Beat（${bars} 小節）` : `${bars} 小節（${bars * 4} Beat）`}</option>)}
            </select>
            <select aria-label="解析単位の表示" className="phrase-unit" value={phraseUnit} onChange={(e) => setPhraseUnit(e.target.value as "beats" | "bars")}><option value="beats">Beat（拍）</option><option value="bars">小節</option></select>
          </div>
          <p id="phrase-length-help" className="field-help">4/4拍子で 4 Beat＝1 小節。細かな変化は 4・8 Beat、長い展開は 32・64 Beat で探せます。指定した間隔の境界から候補を選びます。</p>
          <p className="field-help">{analysisSource === "REKORDBOX" ? "先に rekordbox で BPM / Grid を解析してください。保存済みの拍位置・小節頭を基準に候補を生成します。" : "音源だけで独自解析します。rekordbox のグリッドに合わせる場合は、ライブラリから解析済みの曲を選んでください。"}</p>
          </div>
          <details className="advanced-settings">
            <summary>解析の詳細設定 <span className="muted">（任意）</span></summary>
            <label htmlFor="analysis-source">解析の基準</label>
            <select id="analysis-source" value={analysisSource} onChange={(e) => setAnalysisSource(e.target.value as "REKORDBOX" | "AUDIO")}><option value="REKORDBOX">rekordbox の解析済みデータ</option><option value="AUDIO">音源だけで独自解析</option></select>
            {!batchMode && <><label htmlFor="analysis-bpm">BPM</label>
            <input id="analysis-bpm" type="number" min="0.01" step="any" value={analysisSource === "REKORDBOX" ? analysis?.bpm ?? bpm : bpm} disabled={analysisSource === "REKORDBOX"} placeholder="空欄なら自動推定" onChange={(e) => setBpm(e.target.value)} /></>}
            {!specialized && <div className="row">
              <div className="form-column"><label htmlFor="candidate-count">種別ごとの候補数</label><select id="candidate-count" value={topK} onChange={(e) => setTopK(e.target.value)}>{[1, 2, 3, 5, 10].map((n) => <option key={n} value={n}>{n} 件</option>)}</select></div>
            </div>}
            {!batchMode && <><label htmlFor="content-id">コンテンツ ID</label>
            <input id="content-id" value={contentId} placeholder="通常は変更不要" onChange={(e) => setContentId(e.target.value)} /></>}
          </details>
          {error && <p className="error" role="alert">{error}</p>}
          <p className={`analysis-readiness${(batchMode ? batchReady : cleanPath(path) && (analysisSource === "AUDIO" || analysis?.available) && !checkingAnalysis) && !missingTargets && !invalidBars ? " ready" : ""}`} role="status">{gridBusy ? "小節頭のデータを処理しています…" : missingTargets ? "作りたいCueの位置を1つ以上選んでください" : invalidBars ? "小節数は1〜128の整数で入力してください" : batchMode ? !batchTracks.length ? "↑ 一括解析する曲を選んでください" : batchChecking ? "選択曲の解析情報を確認中…" : !batchReady ? "解析できない曲の理由を確認するか、選択から外してください" : `✓ ${batchTracks.length}曲をまとめて解析できます` : !cleanPath(path) ? "↑ まず解析する曲を選んでください" : checkingAnalysis ? "rekordbox の解析情報を確認中…" : analysisSource === "REKORDBOX" && !analysis?.available ? "rekordbox の解析情報を確認すると開始できます" : "✓ 解析を開始できます"}</p>
          <button className="start-analysis" type="submit" disabled={busy || missingTargets || invalidBars || (batchMode ? !batchReady : !cleanPath(path) || (analysisSource === "REKORDBOX" && (checkingAnalysis || !analysis?.available)))}>{analysisBusy ? "解析を開始しています…" : gridBusy ? "小節頭を処理しています…" : batchMode ? `${batchTracks.length}曲を一括解析 →` : "解析を開始 →"}</button>
        </fieldset>
      </form>
    </section>
  );
}
