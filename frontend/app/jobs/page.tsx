"use client";

import { useState } from "react";
import { AppShell } from "@/components/shell/app-shell";
import {
  Button,
  EmptyState,
  ErrorState,
  GlassPanel,
  Pill,
  SectionTitle,
  Skeleton,
  type Tone
} from "@/components/ui/primitives";
import { usePolling } from "@/hooks/use-api";
import { api } from "@/lib/api";
import type { Job, JobStatus } from "@/lib/types";

const TONE: Record<JobStatus, Tone> = {
  completed: "ok",
  failed: "bad",
  running: "info",
  retrying: "warn",
  queued: "idle"
};

export default function JobsPage() {
  const { data, loading, error, refetch } = usePolling<Job[]>(() => api.jobs(), 4000);
  const [draining, setDraining] = useState(false);

  async function drain() {
    setDraining(true);
    try {
      await api.drain();
      await refetch();
    } finally {
      setDraining(false);
    }
  }

  if (loading && !data) {
    return (
      <AppShell>
        <SectionTitle eyebrow="Queue" title="Jobs" />
        <Skeleton rows={8} />
      </AppShell>
    );
  }

  const jobs = data ?? [];

  return (
    <AppShell>
      <SectionTitle
        eyebrow="Queue"
        title="Jobs"
        subtitle="Deferred work, its retry budget, and why anything failed. Polls while this tab is visible."
      />

      {error ? <ErrorState message={error} onRetry={refetch} /> : null}

      <GlassPanel>
        <div className="mb-4 flex items-center justify-between">
          <p className="text-sm text-slate-300">
            {jobs.length} job{jobs.length === 1 ? "" : "s"}
          </p>
          <Button onClick={drain} disabled={draining}>
            {draining ? "Running…" : "Drain queue"}
          </Button>
        </div>

        {jobs.length === 0 ? (
          <EmptyState title="Nothing queued." hint="Dispatch a generation to see work arrive here." />
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <caption className="sr-only">Background jobs with status and retry counts</caption>
              <thead>
                <tr className="text-left text-xs uppercase tracking-wider text-slate-400">
                  <th scope="col" className="pb-3 pr-4">Type</th>
                  <th scope="col" className="pb-3 pr-4">Status</th>
                  <th scope="col" className="pb-3 pr-4">Attempts</th>
                  <th scope="col" className="pb-3 pr-4">Correlation</th>
                  <th scope="col" className="pb-3">Error</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr key={job.id} className="border-t border-hairline/60 align-top">
                    <td className="py-3 pr-4 font-medium text-white">{job.job_type}</td>
                    <td className="py-3 pr-4">
                      <Pill tone={TONE[job.status]}>{job.status}</Pill>
                    </td>
                    <td className="py-3 pr-4 tabular-nums text-slate-300">
                      {job.attempt_count}/{job.max_attempts}
                    </td>
                    <td className="py-3 pr-4 font-mono text-xs text-slate-500">
                      {job.correlation_id?.slice(0, 8) ?? "—"}
                    </td>
                    <td className="py-3 max-w-sm text-xs text-bad">{job.error_message ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>
    </AppShell>
  );
}
