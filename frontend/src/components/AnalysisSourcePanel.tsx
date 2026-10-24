import type { JobTrack } from "../types";
import { fmtTime } from "../cues";

export function AnalysisSourcePanel({ track }: { track: JobTrack }) {
  const data = track.analysis;
  if (!data) return null;
  return <div className="analysis-source-info">
    <strong>{data.source === "REKORDBOX" ? "rekordbox の解析済みデータを使用" : "音源から独自解析"}</strong>
    {data.available ? <>
      <p className="field-help">BPM {data.bpm} · {data.beat_count} 拍 · {data.downbeat_count} 小節頭{data.key ? ` · キー ${data.key}` : ""}</p>
      {data.source === "REKORDBOX" && <p className="field-help">フレーズ境界：{data.phrase_used ? `${data.phrase_count} 件の区切りを利用` : "未取得（小節頭を基準に生成）"}。{data.section_labels_used ? "指定位置にはIntro・Chorus・Outroなどのラベルを利用します。" : "Cue の種別は音源の変化から推定します。"} Vocalの開始時刻は未取得です。</p>}
    </> : <p className={data.reason ? "error" : "field-help"} role="status">{data.reason || "解析情報を取得しています…"}</p>}
    {data.warnings?.map((warning) => <p key={warning} className="field-help">{warning}</p>)}
    {!!data.existing_cues?.length && <details>
      <summary>rekordbox の既存 Cue：{data.existing_cues.length} 件</summary>
      <p className="field-help">参照用です。新しい候補の採用・書き出しには含めません。</p>
      <div className="table-scroll"><table><thead><tr><th>時刻</th><th>種別</th><th>コメント</th></tr></thead><tbody>{data.existing_cues.map((cue, i) => <tr key={i}><td>{fmtTime(cue.time_ms)}</td><td>{cue.kind === 0 ? "Memory Cue" : "Hot Cue"}</td><td>{cue.comment}</td></tr>)}</tbody></table></div>
    </details>}
  </div>;
}
