import { useState } from "react";
import { CUE_ORDER, defaultCueColor } from "../cues";
import { useCueColors } from "./CueColors";
import { CUE_KIND_LABEL, DEFAULT_KIND_COLORS, SINGLE_CUE_KINDS } from "../cueKinds";
import { CueKindSwatch } from "./CueKindSwatch";

export function CueColorSettings() {
  const { colors, meta, kindColor, setColor, reset } = useCueColors();
  const [open, setOpen] = useState(false);
  const customCount = CUE_ORDER.filter(
    (t) => colors[t] && colors[t] !== defaultCueColor(t),
  ).length + SINGLE_CUE_KINDS.filter((kind) => colors[kind] && colors[kind] !== DEFAULT_KIND_COLORS[kind]).length;

  return (
    <div className="panel">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ margin: 0 }}>🎨 キュー色設定</h2>
        <button className="tiny" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {open ? "閉じる" : customCount > 0 ? `変更中 (${customCount})` : "開く"}
        </button>
      </div>

      {open && (
        <div className="color-list" style={{ marginTop: 12 }}>
          <h3 className="color-section-title">Hot Cue / Memory Cue の色</h3>
          <p className="field-help">採用ボタン・判定・タイムラインと、次に書き出すXMLに反映します。設定はこのブラウザに自動保存します。</p>
          {SINGLE_CUE_KINDS.map((kind) => <div className="color-row" key={kind}>
            <span className="cue-kind-color-label"><CueKindSwatch kind={kind} />{CUE_KIND_LABEL[kind]}</span>
            <input type="color" className="color-input" aria-label={`${CUE_KIND_LABEL[kind]} の色`} value={kindColor(kind)} onChange={(e) => setColor(kind, e.target.value)} />
            <button type="button" className="tiny" disabled={kindColor(kind) === DEFAULT_KIND_COLORS[kind]} onClick={() => reset(kind)} aria-label={`${CUE_KIND_LABEL[kind]} を既定色に戻す`}>既定</button>
          </div>)}
          <p className="field-help"><CueKindSwatch kind="BOTH" />「両方」は2色で表示します。表示色の変更だけでは、既存の rekordbox Cue は変更されません。</p>
          <p className="field-help">Memory Cueの色がrekordboxで反映されるかは未確認です。XMLの取り込み後に確認してください。</p>
          <h3 className="color-section-title">楽曲の展開ごとの表示色</h3>
          {CUE_ORDER.map((t) => {
            const m = meta(t);
            const isCustom = colors[t] && colors[t] !== defaultCueColor(t);
            return (
              <div className="color-row" key={t}>
                <span
                  className="chip"
                  style={{ background: m.color, boxShadow: `0 0 10px ${m.glow}` }}
                >
                  {m.icon} {m.label}
                </span>
                <input
                  type="color"
                  className="color-input"
                  aria-label={`${m.label} の色`}
                  value={m.color}
                  onChange={(e) => setColor(t, e.target.value)}
                />
                <button
                  className="tiny"
                  disabled={!isCustom}
                  onClick={() => reset(t)}
                  title="既定色に戻す"
                >
                  既定
                </button>
              </div>
            );
          })}
          <button
            className="tiny"
            disabled={customCount === 0}
            onClick={() => reset()}
            style={{ marginTop: 4 }}
          >
            すべて既定に戻す
          </button>
        </div>
      )}
    </div>
  );
}
