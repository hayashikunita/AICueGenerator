import { useState } from "react";
import type { CuePreferences } from "../cuePresets";
import type { CuePreset, IntroOutroSettings } from "../types";
import { BAR_FIELDS, INTRO_OUTRO_GROUPS, INTRO_OUTRO_TARGETS, introOutroLabel } from "../introOutro";
import { CuePresetFields } from "./CuePresetFields";

export function IntroOutroSettingsPanel({ value, onChange, preferences, onPreferences, common }: {
  value: IntroOutroSettings; onChange: (value: IntroOutroSettings) => void;
  preferences: CuePreferences; onPreferences: (value: CuePreferences) => void; common: CuePreset;
}) {
  const [allBars, setAllBars] = useState(8);
  return <div className="intro-outro-settings" aria-label="イントロアウトロ特化の設定">
    <p className="field-help">イントロ・アウトロと曲末の位置を探します。「歌い始め」を追加で選ぶと、声の開始も調べます。サビの解析は行いません。</p>
    <div className="intro-outro-bulk-bars"><label>小節数をまとめて入力<input type="number" min="1" max="128" step="1" aria-label="まとめて設定する小節数" value={allBars} onChange={(event) => setAllBars(Number(event.target.value))} /></label>
      <button type="button" className="secondary tiny" disabled={!Number.isInteger(allBars) || allBars < 1 || allBars > 128} onClick={() => onChange({ ...value, ...Object.fromEntries(BAR_FIELDS.map((field) => [field, allBars])) })}>すべての小節数に適用</button></div>
    {INTRO_OUTRO_GROUPS.map((group) => <section className="intro-outro-group" key={group.label}>
      <h4>{group.label}</h4>
      {group.targets.some((option) => option.field === "intro_position_bars") && <>
        <label className="intro-outro-bars" htmlFor="intro-position-bars">指定位置の基準<input id="intro-position-bars" type="number" min="1" max="128" step="1" value={value.intro_position_bars} onChange={(event) => onChange({ ...value, intro_position_bars: Number(event.target.value) })} /><span>小節目</span></label>
        <p className="field-help">この値・2倍・3倍の小節目を下で選べます。最初の小節を1小節目と数えます。</p>
      </>}
      {group.targets.map((option) => {
        const selected = value.targets.includes(option.value);
        const preset = preferences.targets[option.value] ?? common;
        return <div key={option.value} className="cue-target-option">
          <label className="intro-outro-choice"><input type="checkbox" value={option.value} checked={selected} onChange={(event) => onChange({ ...value, targets: event.target.checked ? [...value.targets, option.value] : value.targets.filter((target) => target !== option.value) })} /><span>{introOutroLabel(option.value, value)}{option.multiplier && <small>（基準×{option.multiplier}）</small>}</span></label>
          {selected && option.field && option.field !== "intro_position_bars" && <label className="intro-outro-bars">小節数<input type="number" min="1" max="128" step="1" aria-label={`${option.label}の小節数`} value={value[option.field]} onChange={(event) => onChange({ ...value, [option.field!]: Number(event.target.value) })} /><span>小節</span></label>}
          {selected && option.value === "VOCAL_START" && <p className="field-help">精度を優先する場合は「AI補助」を選んでください。短い単発音・弱い分離漏れを除き、継続する声を確認します。歌い始めは最寄りの拍に合わせます。検出できない場合は省略し、Verse先頭で代用しません。長い掛け声・話し声は試聴で確認してください。</p>}
          {selected && option.value === "VOCAL_END" && <p className="field-help">AI補助で曲末まで確認し、最後の継続する声の終わりを最寄りの拍へ合わせます。歌い始めだけの解析より時間がかかります。未検出なら省略します。掛け声・話し声や残響を含む可能性があるため試聴してください。</p>}
          {selected && <details className="cue-target-preset"><summary>{preferences.targets[option.value] ? "個別設定" : "共通設定"}：{preset.cue_kind === "BOTH" ? "両方" : preset.cue_kind === "HOT" ? "Hot Cue" : "Memory Cue"} · 種類・色を変更</summary>
            <CuePresetFields label={option.label} value={preset} onChange={(next) => onPreferences({ ...preferences, targets: { ...preferences.targets, [option.value]: next } })} />
            {preferences.targets[option.value] && <button type="button" className="secondary tiny" onClick={() => { const targets = { ...preferences.targets }; delete targets[option.value]; onPreferences({ ...preferences, targets }); }}>この目的を共通設定に戻す</button>}
          </details>}
        </div>;
      })}
    </section>)}
    <div className="row"><button type="button" className="secondary tiny" onClick={() => onChange({ ...value, targets: INTRO_OUTRO_TARGETS.map((option) => option.value) })}>すべて選ぶ</button><button type="button" className="secondary tiny" onClick={() => onChange({ ...value, targets: [] })}>選択を解除</button></div>
    <p className="field-help">間隔は区間の始まりから数えます。「○小節前」は終わりから実際の小節頭を戻します。区間より長い指定やフェードを検出できない曲では、理由を表示して候補を省略します。</p>
    <p className="field-help">終わりは基準位置以前の保存済み小節頭へ合わせます。曲の終わりはファイル末尾以前、フェードの終わりは音がほぼ聞こえなくなる位置が基準です。</p>
    <p className="field-help">候補は自動採用しません。Memory CueのXML出力は1曲10個までのため、間隔候補が多い場合も書き出す対象を確認できます。</p>
  </div>;
}
