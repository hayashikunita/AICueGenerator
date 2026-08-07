import { useState } from "react";
import { CUE_ORDER, defaultCueColor } from "../cues";
import { useCueColors } from "./CueColors";

export function CueColorSettings() {
  const { colors, meta, setColor, reset } = useCueColors();
  const [open, setOpen] = useState(false);
  const customCount = CUE_ORDER.filter(
    (t) => colors[t] && colors[t] !== defaultCueColor(t),
  ).length;

  return (
    <div className="panel">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ margin: 0 }}>🎨 キュー色設定</h2>
        <button className="tiny" onClick={() => setOpen((o) => !o)}>
          {open ? "閉じる" : customCount > 0 ? `変更中 (${customCount})` : "開く"}
        </button>
      </div>

      {open && (
        <div className="color-list" style={{ marginTop: 12 }}>
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
