import clsx from "clsx";
import type { ReactNode } from "react";

export function GlassPanel({
  children,
  className,
  scan = false
}: {
  children: ReactNode;
  className?: string;
  scan?: boolean;
}) {
  return (
    <section
      className={clsx(
        "glass holo relative overflow-hidden rounded-3xl p-5",
        scan && "scan",
        className
      )}
    >
      {children}
    </section>
  );
}

export function SectionTitle({
  eyebrow,
  title,
  subtitle
}: {
  eyebrow?: string;
  title: string;
  subtitle?: string;
}) {
  return (
    <header className="mb-5">
      {eyebrow ? (
        <p className="mb-2 text-[11px] uppercase tracking-[0.3em] text-cyan/60">{eyebrow}</p>
      ) : null}
      <h1 className="text-2xl font-semibold text-white">{title}</h1>
      {subtitle ? <p className="mt-1.5 max-w-2xl text-sm text-slate-400">{subtitle}</p> : null}
    </header>
  );
}

const TONES = {
  ok: "border-ok/35 bg-ok/10 text-ok",
  warn: "border-warn/35 bg-warn/10 text-warn",
  bad: "border-bad/35 bg-bad/10 text-bad",
  info: "border-cyan/35 bg-cyan/10 text-cyan",
  idle: "border-idle/30 bg-idle/10 text-idle"
} as const;

export type Tone = keyof typeof TONES;

/**
 * A status chip. Always renders the word, never a bare colour — roughly 8% of
 * men cannot reliably separate the red one from the green one.
 */
export function Pill({ children, tone = "info" }: { children: ReactNode; tone?: Tone }) {
  return (
    <span
      className={clsx(
        // `shrink-0` and `whitespace-nowrap` together: inside a flex row a
        // pill would otherwise be compressed by a long sibling until its
        // label wrapped -- "no key" became "no / key" next to a long model
        // line. A status label that breaks mid-phrase reads as a rendering
        // fault, which is the opposite of what a status pill is for.
        "inline-flex shrink-0 items-center whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-medium",
        TONES[tone]
      )}
    >
      {children}
    </span>
  );
}

export function Button({
  children,
  className,
  tone = "info",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { tone?: Tone }) {
  return (
    <button
      {...props}
      className={clsx(
        "rounded-2xl border px-4 py-2.5 text-sm font-medium transition",
        "hover:brightness-125 disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:brightness-100",
        TONES[tone],
        className
      )}
    >
      {children}
    </button>
  );
}

export function Field({
  label,
  hint,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string }) {
  const id = props.id ?? props.name ?? label.toLowerCase().replace(/\s+/g, "-");
  return (
    <label htmlFor={id} className="block">
      <span className="mb-1.5 block text-xs uppercase tracking-wider text-slate-400">{label}</span>
      <input
        {...props}
        id={id}
        className="w-full rounded-2xl border border-hairline bg-white/5 px-4 py-2.5 text-sm text-white placeholder:text-slate-500"
      />
      {hint ? <span className="mt-1.5 block text-xs text-slate-500">{hint}</span> : null}
    </label>
  );
}

export function Skeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="glass rounded-3xl p-5" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading</span>
      <div className="animate-pulse space-y-3">
        {Array.from({ length: rows }).map((_, index) => (
          <div
            key={index}
            className={clsx("h-4 rounded-lg bg-white/8", index === 0 ? "w-2/5" : "w-full")}
          />
        ))}
      </div>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <GlassPanel>
      <h2 className="text-base font-semibold text-bad">Could not load this</h2>
      <p className="mt-2 text-sm text-slate-300">{message}</p>
      {onRetry ? (
        <Button tone="bad" className="mt-4" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </GlassPanel>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-hairline px-5 py-10 text-center">
      <p className="text-sm text-slate-300">{title}</p>
      {hint ? <p className="mt-1.5 text-xs text-slate-500">{hint}</p> : null}
    </div>
  );
}
