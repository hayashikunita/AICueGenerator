import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useEffect } from "react";
import type { AnalysisInfo, CueTarget, RekordboxTrack } from "../types";
import { CUE_TARGETS } from "../cueTargets";
import { useToast } from "./Toast";
import { PlaylistBrowser } from "./PlaylistBrowser";
import { GridEditor } from "./GridEditor";

const cleanPath = (value: string) => value.trim().replace(/^"(.*)"$/, "$1");

export function NewJobForm({ onCreated }: { onCreated: (jobId: string) => void }) {
  const [source, setSource] = useState<"library" | "path">("library");
  const [libraryMode, setLibraryMode] = useState<"search" | "playlist">("search");
  const [path, setPath] = useState("");
  const [selected, setSelected] = useState<RekordboxTrack | null>(null);
  const [contentId, setContentId] = useState("");
  const [bpm, setBpm] = useState("");
  const [barsPerPhrase, setBarsPerPhrase] = useState("16");
  const [phraseUnit, setPhraseUnit] = useState<"beats" | "bars">("beats");
  const [topK, setTopK] = useState("3");
  const [targetMode, setTargetMode] = useState(false);
  const [cueTargets, setCueTargets] = useState<CueTarget[]>(CUE_TARGETS.map((target) => target.value));
  const [analysisBusy, setBusy] = useState(false);
  const [gridBusy, setGridBusy] = useState(false);
  const busy = analysisBusy || gridBusy;
  const [rbQuery, setRbQuery] = useState("");
  const [rbResults, setRbResults] = useState<RekordboxTrack[]>([]);
  const [rbSearching, setRbSearching] = useState(false);
  const [searchMessage, setSearchMessage] = useState("");
  const [error, setError] = useState("");
  const [analysisSource, setAnalysisSource] = useState<"REKORDBOX" | "AUDIO">("REKORDBOX");
  const [analysis, setAnalysis] = useState<AnalysisInfo | null>(null);
  const [checkingAnalysis, setCheckingAnalysis] = useState(false);
  const [analysisError, setAnalysisError] = useState("");
  const [analysisRefresh, setAnalysisRefresh] = useState(0);
  const toast = useToast();

  useEffect(() => {
    let active = true;
    setAnalysis(null);
    setAnalysisError("");
    if (analysisSource !== "REKORDBOX" || !contentId || !cleanPath(path)) {
      setCheckingAnalysis(false);
      return;
    }
    setCheckingAnalysis(true);
    api.rekordboxAnalysis(contentId, cleanPath(path))
      .then((result) => { if (active) { setAnalysis(result); if (!result.available) setAnalysisError(result.reason || "rekordbox で曲を解析してから再取得してください。"); } })
      .catch((e) => { if (active) setAnalysisError(`解析情報を確認できませんでした: ${e}`); })
      .finally(() => { if (active) setCheckingAnalysis(false); });
    return () => { active = false; };
  }, [analysisSource, contentId, path, analysisRefresh]);

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
    setSelected(track);
    setPath(track.path);
    setContentId(track.content_id);
    setBpm(track.bpm ? String(track.bpm) : "");
    setError("");
  };

  const changeSource = (next: "library" | "path") => {
    setAnalysisSource(next === "library" ? "REKORDBOX" : "AUDIO");
    setSource(next);
    setPath("");
    setSelected(null);
    setContentId("");
    setBpm("");
    setError("");
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    if (targetMode && !cueTargets.length) { setError("作りたいCueの位置を1つ以上選んでください。"); return; }
    if (analysisSource === "REKORDBOX" && (checkingAnalysis || !analysis?.available)) {
      setError("rekordbox の解析済みグリッドを確認してから開始してください。");
      return;
    }
    const filePath = cleanPath(path);
    if (!filePath) {
      setError("解析する曲を選ぶか、音源ファイルのパスを入力してください。");
      return;
    }
    if (bpm.trim() && (!Number.isFinite(Number(bpm)) || Number(bpm) <= 0)) {
      setError("BPM は 0 より大きい数値を入力するか、空欄にしてください。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const { job_id } = await api.createJob(
        {
          analysis_source: analysisSource,
          bpm: analysisSource === "REKORDBOX" ? analysis?.bpm ?? null : bpm.trim() ? Number(bpm) : null,
          ...(phraseUnit === "beats" ? { beats_per_phrase: Number(barsPerPhrase) * 4 } : { bars_per_phrase: Number(barsPerPhrase) }),
          top_k: Number(topK),
          ...(targetMode ? { cue_targets: cueTargets } : {}),
        },
        [{ content_id: contentId.trim() || filePath, path: filePath, format: filePath.split(".").pop()?.toUpperCase() || "WAV" }],
      );
      toast.push("success", "解析を開始しました。結果画面で進捗を確認できます。");
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
        <div className="library-switch" aria-label="ライブラリの表示方法">
          <button type="button" className="secondary tiny" aria-pressed={libraryMode === "search"} disabled={busy || rbSearching} onClick={() => setLibraryMode("search")}>曲を検索</button>
          <button type="button" className="secondary tiny" aria-pressed={libraryMode === "playlist"} disabled={busy || rbSearching} onClick={() => setLibraryMode("playlist")}>プレイリストから</button>
        </div>
        {libraryMode === "playlist" ? <PlaylistBrowser onPick={pickTrack} selectedId={selected?.content_id} disabled={busy} /> : (
        <form onSubmit={searchRekordbox}>
          <label htmlFor="track-search">曲名・アーティスト・アルバム</label>
          <div className="search-row">
            <input id="track-search" value={rbQuery} placeholder="曲名などを入力" onChange={(e) => setRbQuery(e.target.value)} disabled={busy || rbSearching} />
            <button type="submit" className="secondary" disabled={rbSearching || busy}>{rbSearching ? "検索中…" : "検索"}</button>
          </div>
          <p className="field-help" role="status">{searchMessage || "空欄で検索すると、ライブラリの曲を一覧表示します。"}</p>
          {rbResults.length > 0 && <div className="rb-results" aria-label="曲の検索結果">
            {rbResults.map((t) => <button type="button" key={t.content_id} className={`rb-item ${selected?.content_id === t.content_id ? "selected" : ""}`} disabled={!t.path || busy} aria-pressed={selected?.content_id === t.content_id} onClick={() => pickTrack(t)}>
              <span className="rb-title">{selected?.content_id === t.content_id ? "✓ " : ""}{t.title ?? "(無題)"}</span>
              <span className="rb-meta">{t.artist ?? "アーティスト不明"}{t.bpm ? ` · ${t.bpm} BPM` : ""}{!t.path ? " · 音源の場所が不明" : ""}</span>
            </button>)}
          </div>}
        </form>
        )}
        </>
      )}
      <form onSubmit={submit}>
        <fieldset disabled={busy}>
          {source === "path" && <>
            <label htmlFor="audio-path">音源ファイルのパス</label>
            <input id="audio-path" value={path} placeholder="C:\Music\track.wav" onChange={(e) => { setPath(e.target.value); setError(""); }} aria-describedby="path-help" required />
            <p id="path-help" className="field-help">エクスプローラーで音源を右クリック →「パスのコピー」を貼り付け。引用符付きでも使えます。</p>
          </>}
          {path && <div className="selected-track"><span className="eyebrow">選択中の曲</span><strong>{selected?.title || cleanPath(path).split(/[\\/]/).pop()}</strong>{selected?.artist && <span className="muted">{selected.artist}</span>}</div>}
          {analysisSource === "REKORDBOX" && path && <div className="analysis-source-info">
            <strong>rekordbox の解析情報</strong>
            {checkingAnalysis ? <p className="field-help" role="status">拍位置・小節頭を確認しています…</p> : analysis?.available ? <p className="field-help">BPM {analysis.bpm} · {analysis.beat_count} 拍 · {analysis.downbeat_count} 小節頭<br />フレーズ {analysis.phrase_count ?? 0} 件 · 既存 Cue {analysis.existing_cues?.length ?? 0} 件{analysis.key ? ` · キー ${analysis.key}` : ""}</p> : null}
            {analysisError && <p className="error" role="alert">{analysisError}</p>}
            {analysis?.warnings?.map((warning) => <p key={warning} className="field-help">{warning}</p>)}
            <button type="button" className="secondary tiny" disabled={checkingAnalysis} onClick={() => setAnalysisRefresh((n) => n + 1)}>解析情報を再取得</button>
            <GridEditor key={`${contentId}:${path}`} contentId={contentId} path={cleanPath(path)} onBusy={setGridBusy} onSaved={() => setAnalysisRefresh((n) => n + 1)} />
          </div>}
          <div className="cue-target-settings">
            <h3>作りたいCueの位置</h3>
            <div className="source-switch">
              <button type="button" className={targetMode ? "secondary" : ""} aria-pressed={!targetMode} onClick={() => setTargetMode(false)}>従来の候補</button>
              <button type="button" className={targetMode ? "" : "secondary"} aria-pressed={targetMode} onClick={() => setTargetMode(true)}>目的から選ぶ</button>
            </div>
            {targetMode && <>
              <div className="cue-target-options">{CUE_TARGETS.map((target) => <label key={target.value}><input type="checkbox" value={target.value} checked={cueTargets.includes(target.value)} onChange={(e) => setCueTargets((current) => e.target.checked ? [...current, target.value] : current.filter((value) => value !== target.value))} /><span>{target.label}</span></label>)}</div>
              <div className="row"><button type="button" className="secondary tiny" onClick={() => setCueTargets(CUE_TARGETS.map((target) => target.value))}>すべて選ぶ</button><button type="button" className="secondary tiny" onClick={() => setCueTargets([])}>選択を解除</button></div>
              <p className="field-help">自動候補を試聴・調整してから、Hot Cue／Memory Cue／両方で採用します。自動では採用・保存しません。</p>
              <p className="field-help">サビはChorusフレーズを優先。8小節前は実グリッドで計算します。歌い始めは同名LRCの歌詞時刻、なければVerse先頭の仮候補です。Vocalの開始時刻を取得できないため、試聴で確認してください。</p>
            </>}
          </div>
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
          <details className="advanced-settings">
            <summary>解析の詳細設定 <span className="muted">（任意）</span></summary>
            <label htmlFor="analysis-source">解析の基準</label>
            <select id="analysis-source" value={analysisSource} onChange={(e) => setAnalysisSource(e.target.value as "REKORDBOX" | "AUDIO")}><option value="REKORDBOX">rekordbox の解析済みデータ</option><option value="AUDIO">音源だけで独自解析</option></select>
            <label htmlFor="analysis-bpm">BPM</label>
            <input id="analysis-bpm" type="number" min="0.01" step="any" value={analysisSource === "REKORDBOX" ? analysis?.bpm ?? bpm : bpm} disabled={analysisSource === "REKORDBOX"} placeholder="空欄なら自動推定" onChange={(e) => setBpm(e.target.value)} />
            <div className="row">
              <div className="form-column"><label htmlFor="candidate-count">種別ごとの候補数</label><select id="candidate-count" value={topK} onChange={(e) => setTopK(e.target.value)}>{[1, 2, 3, 5, 10].map((n) => <option key={n} value={n}>{n} 件</option>)}</select></div>
            </div>
            <label htmlFor="content-id">コンテンツ ID</label>
            <input id="content-id" value={contentId} placeholder="通常は変更不要" onChange={(e) => setContentId(e.target.value)} />
          </details>
          {error && <p className="error" role="alert">{error}</p>}
          <p className={`analysis-readiness${cleanPath(path) && (!targetMode || cueTargets.length > 0) && (analysisSource === "AUDIO" || analysis?.available) && !checkingAnalysis ? " ready" : ""}`} role="status">{gridBusy ? "小節頭のデータを処理しています…" : !cleanPath(path) ? "↑ まず解析する曲を選んでください" : targetMode && !cueTargets.length ? "作りたいCueの位置を1つ以上選んでください" : checkingAnalysis ? "rekordbox の解析情報を確認中…" : analysisSource === "REKORDBOX" && !analysis?.available ? "rekordbox の解析情報を確認すると開始できます" : "✓ 解析を開始できます"}</p>
          <button className="start-analysis" type="submit" disabled={busy || (targetMode && !cueTargets.length) || !cleanPath(path) || (analysisSource === "REKORDBOX" && (checkingAnalysis || !analysis?.available))}>{analysisBusy ? "解析を開始しています…" : gridBusy ? "小節頭を処理しています…" : "解析を開始 →"}</button>
        </fieldset>
      </form>
    </section>
  );
}
