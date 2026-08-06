import { Fragment, useState } from "react";
import { api } from "../api";
import type { Candidate } from "../types";

function fmt(ms: number): string {
  const s = Math.round(ms / 1000);
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

function Evidence({ c }: { c: Candidate }) {
  return (
    <div className="log" style={{ marginTop: 6 }}>
      {c.evidence.map((e) => (
        <div key={e.name}>
          {e.name}: {(e.score * 100).toFixed(0)} (重み {e.weight}) {e.detail}
        </div>
      ))}
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
  const [err, setErr] = useState<string | null>(null);

  const decide = async (c: Candidate, accepted: boolean, cueKind: "MEMORY" | "HOT") => {
    setErr(null);
    try {
      await api.decide(c.id, { accepted, cue_kind: cueKind });
      setDecided((d) => ({ ...d, [c.id]: accepted ? `採用(${cueKind})` : "却下" }));
      onChanged();
    } catch (e) {
      setErr(String(e));
    }
  };

  if (candidates.length === 0) return <p className="muted">候補はまだありません。</p>;

  return (
    <>
      {err && <p className="error">{err}</p>}
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>種別</th>
            <th>時刻</th>
            <th>ビート</th>
            <th>信頼度</th>
            <th>判定</th>
            <th></th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((c) => (
            <Fragment key={c.id}>
              <tr>
                <td>{c.rank}</td>
                <td>{c.type}</td>
                <td className="mono">{fmt(c.time_ms)}</td>
                <td className="mono">{c.beat ?? "-"}</td>
                <td>{c.confidence}</td>
                <td>
                  <span className={`badge ${c.band}`}>{c.band}</span>
                </td>
                <td className="muted">{decided[c.id] ?? ""}</td>
                <td>
                  <div className="row">
                    <button onClick={() => decide(c, true, "MEMORY")}>MEM</button>
                    <button onClick={() => decide(c, true, "HOT")}>HOT</button>
                    <button className="secondary" onClick={() => decide(c, false, "MEMORY")}>
                      却下
                    </button>
                    <button
                      className="secondary"
                      onClick={() => setOpen(open === c.id ? null : c.id)}
                    >
                      根拠
                    </button>
                  </div>
                </td>
              </tr>
              {open === c.id && (
                <tr>
                  <td colSpan={8}>
                    <Evidence c={c} />
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </>
  );
}
