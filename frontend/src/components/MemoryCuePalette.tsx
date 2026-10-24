import { useEffect, useRef, useState } from "react";
import { MEMORY_CUE_COLORS, memoryColorLabel } from "../memoryColors";

export function MemoryCuePalette({ value, onChange, label = "Memory Cue の色" }: { value: string; onChange: (value: string) => void; label?: string }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    root.current?.querySelector<HTMLElement>('[role="menuitemradio"][aria-checked="true"]')?.focus();
    const outside = (event: MouseEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", outside);
    return () => document.removeEventListener("mousedown", outside);
  }, [open]);
  const choices = MEMORY_CUE_COLORS.some((color) => color.value === value.toLowerCase() || color.value === value)
    ? [...MEMORY_CUE_COLORS] : [{ label: memoryColorLabel(value), value }, ...MEMORY_CUE_COLORS];
  const dot = (color: string) => <span className={`memory-palette-dot${color === "NONE" ? " unset" : ""}`} style={color === "NONE" ? undefined : { background: color }} aria-hidden="true" />;
  return <div className="memory-palette" ref={root}>
    <button type="button" ref={trigger} className="secondary memory-palette-trigger" value={value} aria-label={label} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((current) => !current)} onKeyDown={(event) => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); setOpen(true); }
    }}>{dot(value)}<span>{memoryColorLabel(value)}</span><span className="muted" aria-hidden="true">▾</span></button>
    {open && <div className="memory-palette-menu" role="menu" aria-label={`${label}を選択`} onKeyDown={(event) => {
      const options = Array.from(root.current?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]') ?? []);
      const index = options.indexOf(document.activeElement as HTMLButtonElement);
      if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        options[event.key === "Home" ? 0 : event.key === "End" ? options.length - 1 : (index + (event.key === "ArrowDown" ? 1 : -1) + options.length) % options.length]?.focus();
      }
      if (event.key === "Escape" || event.key === "Tab") { if (event.key === "Escape") event.preventDefault(); setOpen(false); trigger.current?.focus(); }
    }}>{choices.map((color) => <button type="button" role="menuitemradio" aria-checked={color.value.toLowerCase() === value.toLowerCase()} key={color.value} data-color={color.value} onClick={() => { onChange(color.value); setOpen(false); trigger.current?.focus(); }}>
      {dot(color.value)}<span>{color.label}</span><span className="palette-check" aria-hidden="true">{color.value.toLowerCase() === value.toLowerCase() ? "✓" : ""}</span>
    </button>)}</div>}
  </div>;
}
