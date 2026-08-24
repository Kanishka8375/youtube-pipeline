"use client";

import clsx from "clsx";
import { Pill } from "@/components/ui/primitives";

export type ConveyorStep = { label: string; state: "done" | "active" | "waiting" | "blocked" };

const STATE_TONE = { done: "ok", active: "info", waiting: "idle", blocked: "bad" } as const;

/**
 * The pipeline conveyor.
 *
 * The moving band runs only under the active step. A belt that animates
 * everywhere reads as "all of this is happening", which is exactly the wrong
 * thing to say about a queue where one stage is running and five are waiting.
 */
export function Conveyor({ steps }: { steps: ConveyorStep[] }) {
  return (
    <div className="relative overflow-hidden rounded-3xl border border-hairline bg-white/[0.03] p-5">
      <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {steps.map((step) => (
          <li
            key={step.label}
            className={clsx(
              "relative overflow-hidden rounded-2xl border border-hairline bg-white/5 p-4",
              step.state === "active" && "shadow-glow"
            )}
          >
            <p className="text-sm font-medium text-white">{step.label}</p>
            <div className="mt-2.5">
              <Pill tone={STATE_TONE[step.state]}>{step.state}</Pill>
            </div>
            {step.state === "active" ? (
              <span
                aria-hidden
                className="absolute inset-x-0 bottom-0 h-[3px] animate-conveyor"
                style={{
                  backgroundImage:
                    "repeating-linear-gradient(90deg, rgba(93,214,255,0.85) 0 14px, transparent 14px 48px)"
                }}
              />
            ) : null}
          </li>
        ))}
      </ol>
    </div>
  );
}
