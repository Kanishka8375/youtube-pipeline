"use client";

/**
 * The holographic dashboard centrepiece.
 *
 * Displays one number, large. Rings are `aria-hidden`; a screen reader gets
 * the label and the value and nothing about concentric circles.
 */
export function HoloRings({
  label,
  value,
  caption
}: {
  label: string;
  value: string;
  caption?: string;
}) {
  return (
    <div className="relative flex h-72 items-center justify-center overflow-hidden rounded-3xl border border-hairline bg-white/[0.03]">
      <div aria-hidden className="pointer-events-none absolute inset-0 flex items-center justify-center">
        <span className="absolute h-56 w-56 animate-spinSlow rounded-full border border-cyan/25" />
        <span
          className="absolute h-40 w-40 animate-spinSlow rounded-full border border-violet/25"
          style={{ animationDirection: "reverse" }}
        />
        <span className="absolute h-24 w-24 rounded-full border border-teal/35 shadow-[0_0_34px_rgba(45,212,191,0.2)]" />
        <span className="absolute h-px w-72 bg-gradient-to-r from-transparent via-cyan/50 to-transparent" />
        <span className="absolute h-72 w-px bg-gradient-to-b from-transparent via-violet/40 to-transparent" />
      </div>

      <div className="relative text-center">
        <p className="text-[11px] uppercase tracking-[0.3em] text-cyan/60">{label}</p>
        <p className="mt-2 text-4xl font-semibold tabular-nums text-white">{value}</p>
        {caption ? <p className="mt-1.5 text-xs text-slate-400">{caption}</p> : null}
      </div>
    </div>
  );
}
