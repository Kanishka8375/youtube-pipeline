"use client";

import clsx from "clsx";

/**
 * The isometric system map: which subsystems are reachable right now.
 *
 * The skew is applied to the plane and unskewed on each label, so the tiles
 * sit in the isometric field while the text stays upright and readable.
 */
export function SystemMap({
  nodes
}: {
  nodes: Array<{ name: string; healthy: boolean; detail?: string }>;
}) {
  const positions = [
    { left: "14%", top: "26%" },
    { left: "34%", top: "50%" },
    { left: "52%", top: "28%" },
    { left: "70%", top: "54%" },
    { left: "86%", top: "32%" }
  ];

  return (
    <figure className="relative h-72 overflow-hidden rounded-3xl border border-hairline bg-white/[0.03]">
      <figcaption className="sr-only">
        Subsystem reachability: {nodes.map((n) => `${n.name} ${n.healthy ? "ok" : "unavailable"}`).join(", ")}
      </figcaption>
      <div aria-hidden className="tech-grid absolute inset-0 opacity-20 [transform:skewY(-11deg)_scale(1.12)]" />
      <svg aria-hidden className="absolute inset-0 h-full w-full opacity-40" viewBox="0 0 100 100" preserveAspectRatio="none">
        {positions.slice(0, Math.max(nodes.length - 1, 0)).map((_, index) => {
          const from = positions[index];
          const to = positions[index + 1];
          return (
            <line
              key={index}
              x1={parseFloat(from.left)}
              y1={parseFloat(from.top)}
              x2={parseFloat(to.left)}
              y2={parseFloat(to.top)}
              stroke="rgba(93,214,255,0.3)"
              strokeWidth="0.3"
              vectorEffect="non-scaling-stroke"
            />
          );
        })}
      </svg>

      {nodes.slice(0, positions.length).map((node, index) => (
        <div
          key={node.name}
          className="absolute [transform:translate(-50%,-50%)_skewY(-11deg)]"
          style={{ left: positions[index].left, top: positions[index].top }}
        >
          <div className="glass rounded-xl px-3.5 py-2.5 [transform:skewY(11deg)]">
            <p className="flex items-center gap-2 text-xs font-medium text-white">
              <span
                aria-hidden
                className={clsx("h-2 w-2 rounded-full", node.healthy ? "bg-ok" : "bg-bad")}
              />
              {node.name}
            </p>
            <p className="mt-0.5 text-[10px] text-slate-400">
              {node.detail ?? (node.healthy ? "reachable" : "unavailable")}
            </p>
          </div>
        </div>
      ))}
    </figure>
  );
}
