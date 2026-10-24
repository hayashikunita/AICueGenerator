export const TERMINAL = new Set(["COMPLETED", "FAILED", "CANCELLED"]);

export function jobStatus(status: string, failed = 0): string {
  if (status === "COMPLETED" && failed > 0) return "完了（一部失敗）";
  return ({ PENDING: "待機中", QUEUED: "待機中", RUNNING: "解析中", COMPLETED: "解析完了", FAILED: "失敗", CANCELLED: "キャンセル済み" } as Record<string, string>)[status] ?? status;
}

export function trackName(path: string | null | undefined): string {
  return path?.split(/[\\/]/).pop() || "解析した曲";
}

export function jobDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString("ja-JP", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
