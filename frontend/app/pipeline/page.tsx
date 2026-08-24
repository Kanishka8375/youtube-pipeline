"use client";

import { AppShell } from "@/components/shell/app-shell";
import { PipelineGraph } from "@/components/motion/pipeline-graph";
import { ErrorState, GlassPanel, Pill, SectionTitle, Skeleton } from "@/components/ui/primitives";
import { useApi } from "@/hooks/use-api";
import { api } from "@/lib/api";
import type { PipelineStage } from "@/lib/types";

export default function PipelinePage() {
  const { data, loading, error, refetch } = useApi<PipelineStage[]>(() => api.pipelineStages());

  return (
    <AppShell>
      <SectionTitle
        eyebrow="Execution"
        title="Pipeline"
        subtitle="The stage graph as the orchestrator holds it — dependencies, approval gates and QC gates."
      />

      {loading ? (
        <Skeleton rows={8} />
      ) : error ? (
        <ErrorState message={error} onRetry={refetch} />
      ) : (
        <>
          <div className="mb-4">
            <PipelineGraph stages={data ?? []} />
          </div>

          <GlassPanel>
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <caption className="sr-only">Pipeline stages with agents and gates</caption>
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wider text-slate-400">
                    <th scope="col" className="pb-3 pr-4">Stage</th>
                    <th scope="col" className="pb-3 pr-4">Agent</th>
                    <th scope="col" className="pb-3 pr-4">Depends on</th>
                    <th scope="col" className="pb-3">Gates</th>
                  </tr>
                </thead>
                <tbody>
                  {(data ?? []).map((stage) => (
                    <tr key={stage.name} className="border-t border-hairline/60 align-top">
                      <td className="py-3 pr-4 font-medium text-white">{stage.name}</td>
                      <td className="py-3 pr-4 text-slate-300">{stage.agent}</td>
                      <td className="py-3 pr-4 text-xs text-slate-500">
                        {stage.depends_on.join(", ") || "—"}
                      </td>
                      <td className="py-3">
                        <span className="flex flex-wrap gap-1.5">
                          {stage.approval_required ? <Pill tone="warn">approval</Pill> : null}
                          {stage.qc_gate ? <Pill tone="info">QC: {stage.qc_gate}</Pill> : null}
                          {!stage.approval_required && !stage.qc_gate ? (
                            <span className="text-xs text-slate-600">—</span>
                          ) : null}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </GlassPanel>
        </>
      )}
    </AppShell>
  );
}
