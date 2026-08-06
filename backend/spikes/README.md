# P0 スパイク実行手順 (S1-S9)

基本設計書 §16 の Go/No-Go 判定を実機検証するためのハーネスです。
**必ず rekordbox ライブラリの「コピー」に対して実行してください。**

## 事前準備 (§16.1)

1. rekordbox を**完全終了**する（トレイ常駐も終了）。
2. クラウド同期（rekordbox Cloud / Dropbox 等）を**OFF**にする。
3. `master.db` を含むライブラリフォルダを**二重にバックアップ**する。
4. 検証用に `master.db` を別フォルダへ**コピー**する。
   - 既定の本番パスは `%APPDATA%\Pioneer\rekordbox\master.db`（v6）。
5. rekordbox は **1 バージョンのみ**インストールされている状態にする。

## 読取のみ検査（安全・既定）

```powershell
cd backend
.\.venv\Scripts\python.exe -m spikes.p0_spike `
  --db "C:\path\to\COPY\master.db" `
  --backup-dir "C:\path\to\spike-backups" `
  --json report.json
```

- 実行される検査: S1（復号オープン）, S5（バックアップ）, S9（互換）, S4（時間精度・手動）, S7（PQTZ）, S8（PSSI）。
- S2/S3/S6（書込系）は `--allow-write` 未指定のため **スキップ**されます。

## 書込検査（S2/S3/S6）

書込は全安全条件を満たした場合のみ実行されます（フェイルクローズ）。

- rekordbox が実行中 → **拒否**
- 対象が本番 `master.db` → **拒否**（コピーを指定）
- `--allow-write` 未指定 → **拒否**

```powershell
.\.venv\Scripts\python.exe -m spikes.p0_spike `
  --db "C:\path\to\COPY\master.db" `
  --backup-dir "C:\path\to\spike-backups" `
  --content-id <ContentID> `
  --allow-write `
  --json report.json
```

### S2 の最終判定は手動

ハーネスは「DB へメモリーキューを書込→USN 増加→キュー反映」までを自動確認します。
**S2 の合否（DB のみ書込が再起動後に反映されるか）** は次の手順で人手確認してください。

1. 上記書込検査を実行し `AICUE_SPIKE` コメントのキューが追加されたことを確認。
2. 書込済みの**コピー**を本番パスに戻す（バックアップ済みであること）。
3. rekordbox を起動し、対象曲に `AICUE_SPIKE` キューが表示されるか確認。
4. 表示されれば S2=Pass、表示・消失・破損があれば **No-Go**。

## 判定

- Blocker が 1 つでも `fail` → **NO-GO**
- それ以外 → **GO（手動確認項目あり）**

## 既知の環境事実（本ワークスペースで確認済み）

- `sqlcipher3` 利用可能 = **True**（復号可能）
- 鍵は pyrekordbox 0.4.4 内蔵の難読化ブロブから自動復元（別途ダウンロード不要）
- 実行時点で rekordbox が稼働中（pid 検出）→ 書込はガードにより拒否される
