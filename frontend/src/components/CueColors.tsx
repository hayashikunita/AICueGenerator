import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { cueMeta, type CueMeta } from "../cues";

const STORAGE_KEY = "aicue.cueColors";

type ColorMap = Record<string, string>;

interface CueColorsValue {
  colors: ColorMap;
  meta: (type: string) => CueMeta;
  setColor: (type: string, color: string) => void;
  reset: (type?: string) => void;
}

const CueColorsContext = createContext<CueColorsValue | null>(null);

function load(): ColorMap {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as ColorMap) : {};
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

  const value = useMemo<CueColorsValue>(
    () => ({ colors, meta, setColor, reset }),
    [colors, meta, setColor, reset],
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
