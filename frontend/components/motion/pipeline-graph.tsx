"use client";

import clsx from "clsx";
import { useMemo } from "react";
import type { PipelineStage } from "@/lib/types";

/**
 * The floating node graph — the real 15-stage pipeline, not a decorative one.
 *
 * Nodes are laid out by dependency depth, so the picture shows the actual
 * shape of the graph: what can run in parallel, and where the gates are. A
 * prettier arbitrary arrangement would be a lie about the system.
 */
export function PipelineGraph({ stages }: { stages: PipelineStage[] }) {
  const layout = useMemo(() => {
    const byName = new Map(stages.map((s) => [s.name, s]));
    const depthOf = new Map<string, number>();

    const depth = (name: string, seen = new Set<string>()): number => {
      if (depthOf.has(name)) return depthOf.get(name)!;
      if (seen.has(name)) return 0; // a cycle would hang this; the API validates against one
      seen.add(name);
      const stage = byName.get(name);
      const value = !stage?.depends_on.length
        ? 0
        : 1 + Math.max(...stage.depends_on.map((d) => depth(d, seen)));
      depthOf.set(name, value);
      return value;
    };

    stages.forEach((s) => depth(s.name));

    const columns = new Map<number, PipelineStage[]>();
    stages.forEach((s) => {
      const d = depthOf.get(s.name) ?? 0;
      columns.set(d, [...(columns.get(d) ?? []), s]);
    });

    const maxDepth = Math.max(...Array.from(columns.keys()), 0);
    const positions = new Map<string, { x: number; y: number }>();
    columns.forEach((group, d) => {
      group.forEach((stage, index) => {
        positions.set(stage.name, {
          x: maxDepth === 0 ? 50 : 6 + (d / maxDepth) * 88,
          y: group.length === 1 ? 50 : 16 + (index / (group.length - 1)) * 68
        });
      });
    });

    return { positions, byName };
  }, [stages]);

  if (!stages.length) {
    return <div className="h-72 rounded-3xl border border-hairline bg-white/5" />;
  }

  return (
    <figure className="relative h-72 overflow-hidden rounded-3xl border border-hairline bg-white/[0.03]">
      <figcaption className="sr-only">
        Pipeline dependency graph: {stages.length} stages arranged left to right by dependency depth.
      </figcaption>
      <div className="tech-grid absolute inset-0 opacity-25" />

      <svg className="absolute inset-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none">
        {stages.flatMap((stage) =>
          stage.depends_on.map((parent) => {
            const from = layout.positions.get(parent);
            const to = layout.positions.get(stage.name);
            if (!from || !to) return null;
            return (
              <line
                key={`${parent}->${stage.name}`}
                x1={from.x}
                y1={from.y}
                x2={to.x}
                y2={to.y}
                stroke="rgba(93,214,255,0.26)"
                strokeWidth="0.28"
                vectorEffect="non-scaling-stroke"
              />
            );
          })
        )}
      </svg>

      {stages.map((stage, index) => {
        const pos = layout.positions.get(stage.name);
        if (!pos) return null;
        const gated = Boolean(stage.qc_gate) || stage.approval_required;
        return (
          <div
            key={stage.name}
            className="absolute -translate-x-1/2 -translate-y-1/2 animate-drift"
            style={{
              left: `${pos.x}%`,
              top: `${pos.y}%`,
              animationDelay: `${(index % 6) * 0.45}s`
            }}
            title={`${stage.name} — ${stage.agent}${gated ? " (gated)" : ""}`}
          >
            <span
              className={clsx(
                "block h-2.5 w-2.5 animate-pulseNode rounded-full",
                gated ? "bg-violet shadow-[0_0_12px_rgba(167,139,250,0.6)]" : "bg-cyan shadow-glow"
              )}
              style={{ animationDelay: `${(index % 5) * 0.3}s` }}
            />
          </div>
        );
      })}

      <div className="absolute bottom-3 left-4 flex gap-4 text-[10px] uppercase tracking-widest text-slate-400">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-cyan" /> stage
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-violet" /> gated
        </span>
      </div>
    </figure>
  );
}
