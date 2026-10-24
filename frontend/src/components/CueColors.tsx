import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { CUE_ORDER, cueMeta, type CueMeta } from "../cues";
import { DEFAULT_KIND_COLORS, SINGLE_CUE_KINDS, type SingleCueKind } from "../cueKinds";
import type { CueKind } from "../types";

const STORAGE_KEY = "aicue.cueColors";

type ColorMap = Record<string, string>;

interface CueColorsValue {
  colors: ColorMap;
  meta: (type: string) => CueMeta;
  kindColor: (kind: SingleCueKind) => string;
  kindValue: (kind: SingleCueKind) => string;
  exportColor: (kind: SingleCueKind) => string | null;
  kindBackground: (kind: CueKind) => string;
  setColor: (type: string, color: string) => void;
  reset: (type?: string) => void;
}

const CueColorsContext = createContext<CueColorsValue | null>(null);

function load(): ColorMap {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const stored: unknown = raw ? JSON.parse(raw) : {};
    if (!stored || typeof stored !== "object" || Array.isArray(stored)) return {};
    return Object.fromEntries(Object.entries(stored).filter(([key, color]) =>
      [...CUE_ORDER, ...SINGLE_CUE_KINDS].some((known) => known === key) && typeof color === "string" && (/^#[0-9a-f]{6}$/i.test(color) || (key === "MEMORY" && color === "NONE")),
    ));
  } catch {
    return {};
  }
}

export function CueColorsProvider({ children }: { children: ReactNode }) {
  const [colors, setColors] = useState<ColorMap>(load);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(colors));
    } catch {
      /* ストレージ不可でも動作は継続 */
    }
  }, [colors]);

  const setColor = useCallback((type: string, color: string) => {
    if (!/^#[0-9a-f]{6}$/i.test(color) && !(type === "MEMORY" && color === "NONE")) return;
    setColors((prev) => ({ ...prev, [type]: color }));
  }, []);

  const reset = useCallback((type?: string) => {
    setColors((prev) => {
      if (!type) return {};
      const next = { ...prev };
      delete next[type];
      return next;
    });
  }, []);

  const meta = useCallback((type: string) => cueMeta(type, colors), [colors]);
  const kindValue = useCallback((kind: SingleCueKind) => colors[kind] ?? DEFAULT_KIND_COLORS[kind], [colors]);
  const kindColor = useCallback((kind: SingleCueKind) => kindValue(kind) === "NONE" ? "#9a9a9a" : kindValue(kind), [kindValue]);
  const exportColor = useCallback((kind: SingleCueKind) => kindValue(kind) === "NONE" ? null : kindValue(kind), [kindValue]);
  const kindBackground = useCallback((kind: CueKind) => kind === "BOTH"
    ? `linear-gradient(90deg, ${kindColor("MEMORY")} 0%, ${kindColor("MEMORY")} 50%, ${kindColor("HOT")} 50%, ${kindColor("HOT")} 100%)`
    : kindColor(kind), [kindColor]);

  const value = useMemo<CueColorsValue>(
    () => ({ colors, meta, kindColor, kindValue, exportColor, kindBackground, setColor, reset }),
    [colors, meta, kindColor, kindValue, exportColor, kindBackground, setColor, reset],
  );

  return <CueColorsContext.Provider value={value}>{children}</CueColorsContext.Provider>;
}

export function useCueColors(): CueColorsValue {
  const ctx = useContext(CueColorsContext);
  if (!ctx) throw new Error("useCueColors must be used within CueColorsProvider");
  return ctx;
}

export function useCueMeta(): (type: string) => CueMeta {
  return useCueColors().meta;
}
