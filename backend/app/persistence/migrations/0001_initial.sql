-- rekordbox AI Cue Generator - アプリSQLite 初期スキーマ
-- 基本設計書 v0.2 §4 に対応。音源本体は保存しない。時刻は UTC ISO8601 文字列。

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

-- rekordbox曲参照（音源複製なし）
CREATE TABLE IF NOT EXISTS track_ref (
    id            TEXT PRIMARY KEY,
    content_id    TEXT NOT NULL,
    rb_uuid       TEXT,
    path          TEXT NOT NULL,
    format        TEXT NOT NULL,
    duration_ms   INTEGER,
    sample_rate   INTEGER,
    metadata_json TEXT,
    writable      INTEGER NOT NULL DEFAULT 0,
    skip_reason   TEXT,
    created_at    TEXT NOT NULL,
    UNIQUE (content_id)
);

-- 解析ジョブ
CREATE TABLE IF NOT EXISTS analysis_job (
    id          TEXT PRIMARY KEY,
    status      TEXT NOT NULL,
    params_json TEXT NOT NULL,
    total       INTEGER NOT NULL DEFAULT 0,
    completed   INTEGER NOT NULL DEFAULT 0,
    failed      INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_track (
    job_id   TEXT NOT NULL REFERENCES analysis_job (id) ON DELETE CASCADE,
    track_id TEXT NOT NULL REFERENCES track_ref (id) ON DELETE CASCADE,
    status   TEXT NOT NULL,
    error_id TEXT,
    PRIMARY KEY (job_id, track_id)
);

-- 解析実行（再現性・キャッシュ判定）
CREATE TABLE IF NOT EXISTS analysis_run (
    id                TEXT PRIMARY KEY,
    track_id          TEXT NOT NULL REFERENCES track_ref (id) ON DELETE CASCADE,
    engine_version    TEXT NOT NULL,
    params_json       TEXT NOT NULL,
    audio_fingerprint TEXT NOT NULL,
    beat_source       TEXT NOT NULL,
    pssi_used         INTEGER NOT NULL DEFAULT 0,
    status            TEXT NOT NULL,
    error_id          TEXT,
    started_at        TEXT,
    finished_at       TEXT,
    UNIQUE (track_id, engine_version, audio_fingerprint, params_json)
);

-- 特徴量要約（画面表示・構造推定）
CREATE TABLE IF NOT EXISTS feature_summary (
    run_id              TEXT PRIMARY KEY REFERENCES analysis_run (id) ON DELETE CASCADE,
    bpm                 REAL,
    beat_times_json     TEXT,
    downbeats_json      TEXT,
    bars_json           TEXT,
    energy_json         TEXT,
    waveform_peaks_json TEXT
);

-- AI候補
CREATE TABLE IF NOT EXISTS cue_candidate (
    id            TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL REFERENCES analysis_run (id) ON DELETE CASCADE,
    type          TEXT NOT NULL,
    time_ms       INTEGER NOT NULL,
    beat          INTEGER,
    bar           INTEGER,
    confidence    INTEGER NOT NULL,
    rank          INTEGER NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

-- 利用者の判断
CREATE TABLE IF NOT EXISTS cue_decision (
    id             TEXT PRIMARY KEY,
    candidate_id   TEXT NOT NULL REFERENCES cue_candidate (id) ON DELETE CASCADE,
    accepted       INTEGER NOT NULL DEFAULT 0,
    edited_time_ms INTEGER,
    cue_kind       TEXT NOT NULL,
    slot           TEXT,
    color          TEXT,
    comment        TEXT,
    updated_at     TEXT NOT NULL,
    UNIQUE (candidate_id)
);

-- バックアップ証跡（write_plan から参照するため先に定義）
CREATE TABLE IF NOT EXISTS backup_record (
    id             TEXT PRIMARY KEY,
    path           TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    size_bytes     INTEGER NOT NULL,
    hash           TEXT NOT NULL,
    db_version     TEXT,
    restore_status TEXT
);

-- 書込計画（dry-run差分と実行同一性）
CREATE TABLE IF NOT EXISTS write_plan (
    id                TEXT PRIMARY KEY,
    job_id            TEXT,
    confirmation_hash TEXT NOT NULL,
    status            TEXT NOT NULL,
    backup_id         TEXT REFERENCES backup_record (id),
    created_at        TEXT NOT NULL,
    executed_at       TEXT
);

CREATE TABLE IF NOT EXISTS write_plan_item (
    id          TEXT PRIMARY KEY,
    plan_id     TEXT NOT NULL REFERENCES write_plan (id) ON DELETE CASCADE,
    track_id    TEXT NOT NULL REFERENCES track_ref (id),
    action      TEXT NOT NULL,
    cue_kind    TEXT NOT NULL,
    slot        TEXT,
    before_json TEXT,
    after_json  TEXT,
    reason      TEXT
);

-- 監査ログ（変更追跡・障害調査）
CREATE TABLE IF NOT EXISTS audit_event (
    id          TEXT PRIMARY KEY,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    target      TEXT,
    before_json TEXT,
    after_json  TEXT,
    result      TEXT NOT NULL,
    error_id    TEXT,
    job_id      TEXT,
    track_id    TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_analysis_run_track ON analysis_run (track_id);
CREATE INDEX IF NOT EXISTS idx_cue_candidate_run ON cue_candidate (run_id);
CREATE INDEX IF NOT EXISTS idx_audit_event_job ON audit_event (job_id);
