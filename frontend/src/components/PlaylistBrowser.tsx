import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { RekordboxPlaylist, RekordboxTrack } from "../types";

export function PlaylistBrowser({ onPick, selectedId, disabled }: {
  onPick: (track: RekordboxTrack) => void;
  selectedId: string | undefined;
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
  const [error, setError] = useState("");
  const trackRequest = useRef(0);

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

  return <div className="playlist-browser">
    <label htmlFor="rekordbox-playlist">プレイリスト</label>
    <div className="search-row">
      <select id="rekordbox-playlist" value={playlistId} disabled={disabled || loading} onChange={(e) => { setPlaylistId(e.target.value); setQuery(""); setSearch(""); }}>
        <option value="">{loading ? "読み込み中…" : "プレイリストを選択"}</option>
        {playlists.map((p) => <option key={p.id} value={p.id} disabled={p.is_folder}>{p.is_folder ? "📁 " : ""}{p.path}{p.is_smart ? "（スマート）" : ""}</option>)}
      </select>
      <button type="button" className="secondary tiny" disabled={disabled || loading || loadingTracks} onClick={loadPlaylists}>再取得</button>
    </div>
    {!loading && !error && playlists.length === 0 && <p className="field-help">プレイリストはありません。</p>}
    {playlistId && <>
      <form onSubmit={(e) => { e.preventDefault(); if (query.trim() === search) void loadTracks(playlistId, search); else setSearch(query.trim()); }}>
        <label htmlFor="playlist-track-search">プレイリスト内の曲名・アーティスト</label>
        <div className="search-row"><input id="playlist-track-search" type="search" placeholder="プレイリスト内で絞り込み" value={query} onChange={(e) => setQuery(e.target.value)} disabled={disabled} /><button type="submit" className="secondary tiny" disabled={disabled || loadingTracks}>絞り込む</button></div>
      </form>
      <p className="field-help" role="status">{loadingTracks && !tracks.length ? "曲を読み込んでいます…" : `${total} 曲中 ${tracks.length} 曲を表示`}</p>
      {!loadingTracks && !error && tracks.length === 0 && <p className="field-help">{search ? "一致する曲はありません。検索語を変えてください。" : "このプレイリストに曲はありません。"}</p>}
      <div className="rb-results" aria-label="プレイリストの楽曲" aria-busy={loadingTracks}>
        {tracks.map((t, index) => <button key={`${t.content_id}-${index}`} type="button" className={`rb-item ${selectedId === t.content_id ? "selected" : ""}`} disabled={disabled || !t.path} aria-pressed={selectedId === t.content_id} onClick={() => onPick(t)}>
          <span className="rb-title">{selectedId === t.content_id ? "✓ " : ""}{t.title || "(無題)"}</span><span className="rb-meta">{t.artist || "アーティスト不明"}{t.bpm ? ` · ${t.bpm} BPM` : ""}{!t.path ? " · 音源の場所が不明" : ""}</span>
        </button>)}
      </div>
      {hasMore && <button type="button" className="secondary tiny" disabled={disabled || loadingTracks} onClick={() => loadTracks(playlistId, search, tracks.length)}>{loadingTracks ? "読み込み中…" : "続きを表示"}</button>}
    </>}
    {error && <p className="error" role="alert">{error}</p>}
  </div>;
}
