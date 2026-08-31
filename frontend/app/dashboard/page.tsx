"use client";

import { AppShell } from "@/components/shell/app-shell";
import { PipelineGraph } from "@/components/motion/pipeline-graph";
import { HoloRings } from "@/components/motion/holo-rings";
import { Conveyor, type ConveyorStep } from "@/components/motion/conveyor";
import { SystemMap } from "@/components/motion/system-map";
import { ErrorState, GlassPanel, Pill, SectionTitle, Skeleton } from "@/components/ui/primitives";
import { usePolling, useApi } from "@/hooks/use-api";
import { api } from "@/lib/api";
import type { Job, MediaProviderInfo, PipelineStage, ProviderInfo } from "@/lib/types";

function conveyorFromJobs(jobs: Job[]): ConveyorStep[] {
  const running = jobs.filter((j) => j.status === "running").length;
  const queued = jobs.filter((j) => j.status === "queued" || j.status === "retrying").length;
  const failed = jobs.filter((j) => j.status === "failed").length;
  const done = jobs.filter((j) => j.status === "completed").length;

  return [
    { label: "Script", state: done ? "done" : "waiting" },
    { label: "Continuity", state: failed ? "blocked" : done ? "done" : "waiting" },
    { label: "Generation", state: running ? "active" : queued ? "waiting" : done ? "done" : "waiting" },
    { label: "Visuals", state: queued ? "waiting" : "waiting" },
    { label: "QC", state: failed ? "blocked" : "waiting" },
    { label: "Delivery", state: "waiting" }
  ];
}

export default function DashboardPage() {
  const jobs = usePolling<Job[]>(() => api.jobs(), 5000);
  const stages = useApi<PipelineStage[]>(() => api.pipelineStages());
  const providers = useApi<{
    providers: Record<string, ProviderInfo>;
    media_providers: Record<string, MediaProviderInfo>;
  }>(() => api.providers());
  const readiness = usePolling<Record<string, string>>(() => api.readiness(), 15000);

  const rows = jobs.data ?? [];
  const failed = rows.filter((j) => j.status === "failed").length;
  const active = rows.filter((j) => j.status === "running" || j.status === "retrying").length;
  // Text and media together: the tile answers "can this deployment actually
  // make anything", and counting only half of it would overstate readiness.
  // Each carries its lane because both lanes have a provider called `mock`,
  // and an unqualified list renders as "mock, mock".
  const allProviders = [
    ...Object.values(providers.data?.providers ?? {}).map((p) => ({ ...p, lane: "" })),
    ...Object.values(providers.data?.media_providers ?? {}).map((p) => ({ ...p, lane: " (media)" }))
  ];
  const configured = allProviders.filter((p) => p.configured);

  return (
    <AppShell>
      <SectionTitle
        eyebrow="Operations"
        title="Dashboard"
        subtitle="Pipeline shape, queue depth and which providers can actually run right now."
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <GlassPanel>
          <p className="text-xs uppercase tracking-[0.22em] text-slate-400">Jobs tracked</p>
          <p className="mt-2.5 text-3xl font-semibold tabular-nums text-white">{rows.length}</p>
        </GlassPanel>
        <GlassPanel>
          <p className="text-xs uppercase tracking-[0.22em] text-slate-400">In flight</p>
          <p className="mt-2.5 text-3xl font-semibold tabular-nums text-white">{active}</p>
        </GlassPanel>
        <GlassPanel>
          <p className="text-xs uppercase tracking-[0.22em] text-slate-400">Failed</p>
          <p className="mt-2.5 text-3xl font-semibold tabular-nums text-white">{failed}</p>
          <div className="mt-2">
            <Pill tone={failed ? "bad" : "ok"}>{failed ? "needs attention" : "clear"}</Pill>
          </div>
        </GlassPanel>
        <GlassPanel>
          <p className="text-xs uppercase tracking-[0.22em] text-slate-400">Providers ready</p>
          <p className="mt-2.5 text-3xl font-semibold tabular-nums text-white">
            {configured.length}/{allProviders.length}
          </p>
          <p className="mt-1.5 text-xs text-slate-500">
            {configured.map((p) => `${p.provider_key}${p.lane}`).join(", ") || "none"}
          </p>
        </GlassPanel>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        {stages.loading ? (
          <Skeleton rows={6} />
        ) : stages.error ? (
          <ErrorState message={stages.error} onRetry={stages.refetch} />
        ) : (
          <PipelineGraph stages={stages.data ?? []} />
        )}

        <HoloRings
          label="Queue"
          value={String(rows.filter((j) => j.status === "queued").length)}
          caption={active ? `${active} running` : "idle"}
        />

        <SystemMap
          nodes={[
            { name: "API", healthy: !readiness.error },
            { name: "Database", healthy: readiness.data?.database === "ok" },
            { name: "Queue", healthy: !jobs.error },
            { name: "Providers", healthy: configured.length > 0, detail: `${configured.length} ready` },
            { name: "Canon", healthy: !stages.error }
          ]}
        />
      </div>

      <div className="mt-4">
        <Conveyor steps={conveyorFromJobs(rows)} />
      </div>
    </AppShell>
  );
}
