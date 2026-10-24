import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { RekordboxPlaylist, RekordboxTrack } from "../types";

export function PlaylistBrowser({ onPick, selectedId, selectedIds, onPickMany, onBusy, disabled }: {
  onPick: (track: RekordboxTrack) => void;
  selectedId: string | undefined;
  selectedIds?: string[];
  onPickMany?: (tracks: RekordboxTrack[]) => void;
  onBusy?: (busy: boolean) => void;
  disabled: boolean;
}) {
  const [playlists, setPlaylists] = useState<RekordboxPlaylist[]>([]);
  const [playlistId, setPlaylistId] = useState("");
  const [tracks, setTracks] = useState<RekordboxTrack[]>([]);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingTracks, setLoadingTracks] = useState(false);
  const [selectingAll, setSelectingAll] = useState(false);
  const [error, setError] = useState("");
  const trackRequest = useRef(0);
  useEffect(() => { onBusy?.(selectingAll); return () => onBusy?.(false); }, [selectingAll, onBusy]);

  const loadPlaylists = useCallback(async () => {
    setLoading(true);
    setError("");
    setPlaylistId("");
    setPlaylists([]);
    try {
      const result = await api.rekordboxPlaylists();
      if (!result.available) setError(result.reason || "rekordbox に接続できません。ファイルパスからも解析できます。");
      else setPlaylists(result.playlists);
    } catch (e) {
      setError(`プレイリストを取得できませんでした: ${e}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void loadPlaylists(); }, [loadPlaylists]);

  const loadTracks = useCallback(async (id: string, filter: string, offset = 0) => {
    const request = ++trackRequest.current;
    setLoadingTracks(true);
    setError("");
    if (!offset) { setTracks([]); setTotal(0); setHasMore(false); }
    try {
      const result = await api.rekordboxPlaylistTracks(id, filter, offset);
      if (request !== trackRequest.current) return;
      if (!result.available) { setError(result.reason || "曲を取得できませんでした。"); return; }
      setTracks((previous) => offset ? [...previous, ...result.tracks] : result.tracks);
      setTotal(result.total);
      setHasMore(result.has_more);
    } catch (e) {
      if (request === trackRequest.current) setError(`曲を取得できませんでした: ${e}`);
    } finally {
      if (request === trackRequest.current) setLoadingTracks(false);
    }
  }, []);

  useEffect(() => {
    if (playlistId) void loadTracks(playlistId, search);
    else { setTracks([]); setTotal(0); setHasMore(false); setLoadingTracks(false); }
    return () => { trackRequest.current += 1; };
  }, [playlistId, search, loadTracks]);

  const selectAll = async () => {
    if (!onPickMany || selectingAll) return;
    setSelectingAll(true);
    setError("");
    try {
      const all: RekordboxTrack[] = [];
      let offset = 0;
      while (true) {
        const result = await api.rekordboxPlaylistTracks(playlistId, search, offset);
        if (!result.available) throw new Error(result.reason || "曲を取得できませんでした。");
        all.push(...result.tracks.filter((t) => t.path));
        if (all.length > 200) throw new Error("一度に選べるのは200曲までです。プレイリストを絞り込んでください。");
        if (!result.has_more) break;
        if (!result.tracks.length) throw new Error("曲の一覧が変わりました。再取得してください。");
        offset += result.tracks.length;
      }
      onPickMany(all);
    } catch (e) { setError(String(e)); }
    finally { setSelectingAll(false); }
  };

  return <div className="playlist-browser">
    <label htmlFor="rekordbox-playlist">プレイリスト</label>
    <div className="search-row">
      <select id="rekordbox-playlist" value={playlistId} disabled={disabled || loading || selectingAll} onChange={(e) => { setPlaylistId(e.target.value); setQuery(""); setSearch(""); }}>
        <option value="">{loading ? "読み込み中…" : "プレイリストを選択"}</option>
        {playlists.map((p) => <option key={p.id} value={p.id} disabled={p.is_folder}>{p.is_folder ? "📁 " : ""}{p.path}{p.is_smart ? "（スマート）" : ""}</option>)}
      </select>
      <button type="button" className="secondary tiny" disabled={disabled || loading || loadingTracks || selectingAll} onClick={loadPlaylists}>再取得</button>
    </div>
    {!loading && !error && playlists.length === 0 && <p className="field-help">プレイリストはありません。</p>}
    {playlistId && <>
      <form onSubmit={(e) => { e.preventDefault(); if (query.trim() === search) void loadTracks(playlistId, search); else setSearch(query.trim()); }}>
        <label htmlFor="playlist-track-search">プレイリスト内の曲名・アーティスト</label>
        <div className="search-row"><input id="playlist-track-search" type="search" placeholder="プレイリスト内で絞り込み" value={query} onChange={(e) => setQuery(e.target.value)} disabled={disabled || selectingAll} /><button type="submit" className="secondary tiny" disabled={disabled || loadingTracks || selectingAll}>絞り込む</button></div>
      </form>
      <p className="field-help" role="status">{loadingTracks && !tracks.length ? "曲を読み込んでいます…" : `${total} 曲中 ${tracks.length} 曲を表示`}</p>
      {onPickMany && tracks.length > 0 && <div className="row"><button type="button" className="secondary tiny" disabled={disabled || loadingTracks || selectingAll} onClick={() => onPickMany(tracks)}>表示中の曲をまとめて選ぶ</button><button type="button" className="secondary tiny" disabled={disabled || loadingTracks || selectingAll} onClick={selectAll}>{selectingAll ? "全曲を取得中…" : search ? "絞り込んだ全曲を選ぶ" : "プレイリスト全曲を選ぶ"}</button></div>}
      {!loadingTracks && !error && tracks.length === 0 && <p className="field-help">{search ? "一致する曲はありません。検索語を変えてください。" : "このプレイリストに曲はありません。"}</p>}
      <div className="rb-results" aria-label="プレイリストの楽曲" aria-busy={loadingTracks}>
        {tracks.map((t, index) => <button key={`${t.content_id}-${index}`} type="button" className={`rb-item ${(selectedIds ? selectedIds.includes(t.content_id) : selectedId === t.content_id) ? "selected" : ""}`} disabled={disabled || selectingAll || !t.path || (!!selectedIds && selectedIds.length >= 200 && !selectedIds.includes(t.content_id))} aria-pressed={selectedIds ? selectedIds.includes(t.content_id) : selectedId === t.content_id} onClick={() => onPick(t)}>
          <span className="rb-title">{(selectedIds ? selectedIds.includes(t.content_id) : selectedId === t.content_id) ? "✓ " : selectedIds ? "＋ " : ""}{t.title || "(無題)"}</span><span className="rb-meta">{t.artist || "アーティスト不明"}{t.bpm ? ` · ${t.bpm} BPM` : ""}{!t.path ? " · 音源の場所が不明" : ""}</span>
        </button>)}
      </div>
      {hasMore && <button type="button" className="secondary tiny" disabled={disabled || loadingTracks} onClick={() => loadTracks(playlistId, search, tracks.length)}>{loadingTracks ? "読み込み中…" : "続きを表示"}</button>}
    </>}
    {error && <p className="error" role="alert">{error}</p>}
  </div>;
}
