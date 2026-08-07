import { Fragment, useState } from "react";
import { api } from "../api";
import { fmtTime } from "../cues";
import type { Candidate } from "../types";
import { useCueMeta } from "./CueColors";
import { useToast } from "./Toast";

function Evidence({ c }: { c: Candidate }) {
  return (
    <div style={{ display: "grid", gap: 7, padding: "4px 2px" }}>
      {c.evidence.map((e) => {
        const pct = Math.round(e.score * 100);
        const band = pct >= 66 ? "high" : pct >= 40 ? "review" : "reject";
        return (
          <div key={e.name} className="row" style={{ gap: 10, flexWrap: "nowrap" }}>
            <span className="mono" style={{ minWidth: 130, fontSize: 12 }}>
              {e.name}
            </span>
            <div className="meter-wrap" style={{ flex: 1 }}>
              <div className={`meter ${band}`} style={{ flex: 1 }}>
                <span style={{ width: `${pct}%` }} />
              </div>
              <span className="meter-val">{pct}</span>
            </div>
            <span className="muted" style={{ fontSize: 11, minWidth: 60 }}>
              重み {e.weight}
            </span>
            {e.detail && <span className="muted" style={{ fontSize: 11 }}>{e.detail}</span>}
          </div>
        );
      })}
    </div>
  );
}

export function CandidateTable({
  candidates,
  onChanged,
}: {
  candidates: Candidate[];
  onChanged: () => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const [decided, setDecided] = useState<Record<string, string>>({});
  const cueMeta = useCueMeta();
  const toast = useToast();

  const decide = async (c: Candidate, accepted: boolean, cueKind: "MEMORY" | "HOT") => {
    try {
      await api.decide(c.id, { accepted, cue_kind: cueKind });
      const label = accepted ? `採用 (${cueKind})` : "却下";
      setDecided((d) => ({ ...d, [c.id]: label }));
      const meta = cueMeta(c.type);
      toast.push(
        accepted ? "success" : "info",
        `${meta.label} ${fmtTime(c.time_ms)} を${label}しました`,
      );
      onChanged();
    } catch (e) {
      toast.push("error", `判定に失敗: ${e}`);
    }
  };

  if (candidates.length === 0)
    return (
      <div className="empty">
        <span className="emoji">🔍</span>
        候補はまだありません。解析が完了すると表示されます。
      </div>
    );

  return (
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>種別</th>
          <th>時刻</th>
          <th>ビート</th>
          <th style={{ minWidth: 120 }}>信頼度</th>
          <th>判定</th>
          <th style={{ textAlign: "right" }}>操作</th>
        </tr>
      </thead>
      <tbody>
        {candidates.map((c) => {
          const meta = cueMeta(c.type);
          const isDecided = decided[c.id];
          return (
            <Fragment key={c.id}>
              <tr>
                <td className="mono muted">{c.rank}</td>
                <td>
                  <span className="chip" style={{ background: meta.color }}>
                    {meta.icon} {meta.label}
                  </span>
                </td>
                <td className="mono">{fmtTime(c.time_ms)}</td>
                <td className="mono muted">{c.beat ?? "-"}</td>
                <td>
                  <div className="meter-wrap">
                    <div className={`meter ${c.band}`}>
                      <span style={{ width: `${c.confidence}%` }} />
                    </div>
                    <span className="meter-val">{c.confidence}</span>
                    <span className={`badge ${c.band}`}>{c.band}</span>
                  </div>
                </td>
                <td>
                  {isDecided ? (
                    <span className="muted" style={{ fontSize: 12 }}>
                      {isDecided}
                    </span>
                  ) : (
                    <span className="muted" style={{ fontSize: 12, opacity: 0.5 }}>
                      未判定
                    </span>
                  )}
                </td>
                <td>
                  <div className="row" style={{ justifyContent: "flex-end", flexWrap: "nowrap" }}>
                    <button className="tiny" onClick={() => decide(c, true, "MEMORY")}>
                      MEM
                    </button>
                    <button className="tiny" onClick={() => decide(c, true, "HOT")}>
                      HOT
                    </button>
                    <button className="secondary tiny" onClick={() => decide(c, false, "MEMORY")}>
                      却下
                    </button>
                    <button
                      className="secondary tiny"
                      onClick={() => setOpen(open === c.id ? null : c.id)}
                    >
                      {open === c.id ? "▲" : "根拠"}
                    </button>
                  </div>
                </td>
              </tr>
              {open === c.id && (
                <tr>
                  <td colSpan={7} style={{ background: "rgba(0,0,0,0.18)" }}>
                    <Evidence c={c} />
                  </td>
                </tr>
              )}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}
