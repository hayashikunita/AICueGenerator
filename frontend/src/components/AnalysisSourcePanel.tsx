import type { JobTrack } from "../types";
import { fmtTime } from "../cues";

export function AnalysisSourcePanel({ track }: { track: JobTrack }) {
  const data = track.analysis;
  if (!data) return null;
  return <div className="analysis-source-info">
    <strong>{data.source === "REKORDBOX" ? "rekordbox の解析済みデータを使用" : "音源から独自解析"}</strong>
    {data.available ? <>
      <p className="field-help">BPM {data.bpm} · {data.beat_count} 拍 · {data.downbeat_count} 小節頭{data.key ? ` · キー ${data.key}` : ""}</p>
      {data.cue_mode === "INTRO_OUTRO" ? <p className="field-help">イントロアウトロ特化：Intro・Outroの区間と曲末の音量を確認し、保存済みの小節頭で間隔・手前の位置を計算します。歌い始めを選んだ場合は、声の開始やLRCの時刻を最寄りの拍へ合わせます。</p> : data.source === "REKORDBOX" && <p className="field-help">フレーズ境界：{data.phrase_used ? `${data.phrase_count} 件の区切りを利用` : "未取得（小節頭を基準に生成）"}。{data.section_labels_used ? "指定位置にはIntro・Chorus・Outroなどのラベルを利用します。" : "Cue の種別は音源の変化から推定します。"} rekordboxのVocal開始時刻は未取得です。</p>}
      {data.ai_model && <p className="field-help">AI補助：HTDemucsで音源分離{data.ai_cached ? "（分離結果を再利用）" : ""}。{data.vocal_start_sec != null ? `分離ボーカルの有音開始候補 ${fmtTime(data.vocal_start_sec * 1000)}。LRCがある場合は歌詞時刻を優先します。` : "分離ボーカルの開始位置は特定できませんでした。"} ボーカル成分には掛け声や話し声が含まれる場合があります。</p>}
      {data.ai_scope === "VOCAL" && data.vocal_analyzed_sec != null && <p className="field-help">ボーカルの確認範囲：先頭から{fmtTime(data.vocal_analyzed_sec * 1000)}まで。{data.vocal_scan_complete ? "曲末まで確認しました。" : "継続する声を確認できたため、以降の分離を省略しました。"}</p>}
      {data.vocal_end_requested && <p className="field-help">{data.vocal_end_sec != null ? `最後の継続するボーカルの終了候補 ${fmtTime(data.vocal_end_sec * 1000)}。Cueは最寄りの拍へ合わせています。` : "ボーカルの終わりを確認できなかったため、その候補は省略しました。"}</p>}
    </> : <p className={data.reason ? "error" : "field-help"} role="status">{data.reason || data.stage || "解析情報を取得しています…"}</p>}
    {data.warnings?.map((warning) => <p key={warning} className="field-help">{warning}</p>)}
    {!!data.existing_cues?.length && <details>
      <summary>rekordbox の既存 Cue：{data.existing_cues.length} 件</summary>
      <p className="field-help">参照用です。新しい候補の採用・書き出しには含めません。</p>
      <div className="table-scroll"><table><thead><tr><th>時刻</th><th>種別</th><th>コメント</th></tr></thead><tbody>{data.existing_cues.map((cue, i) => <tr key={i}><td>{fmtTime(cue.time_ms)}</td><td>{cue.kind === 0 ? "Memory Cue" : "Hot Cue"}</td><td>{cue.comment}</td></tr>)}</tbody></table></div>
    </details>}
  </div>;
}
