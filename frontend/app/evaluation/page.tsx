"use client";

import { useState } from "react";
import { AppShell } from "@/components/shell/app-shell";
import {
  Button,
  ErrorState,
  GlassPanel,
  Pill,
  SectionTitle,
  Skeleton
} from "@/components/ui/primitives";
import { useApi } from "@/hooks/use-api";
import { api, ApiError } from "@/lib/api";

type SuiteRun = Awaited<ReturnType<typeof api.runEvaluation>>;

export default function EvaluationPage() {
  const suite = useApi(() => api.evaluationSuite());
  const [run, setRun] = useState<SuiteRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function execute() {
    setBusy(true);
    setError(null);
    try {
      setRun(await api.runEvaluation());
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  const blocked = run?.by_polarity?.must_block;
  const quiet = run?.by_polarity?.must_pass;

  return (
    <AppShell>
      <SectionTitle
        eyebrow="Quality"
        title="Adversarial suite"
        subtitle="Half these cases assert nothing fires. A gate that blocks everything scores 100% on a suite made only of real problems."
      />

      {error ? <div className="mb-4"><ErrorState message={error} /></div> : null}

      <GlassPanel className="mb-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-sm text-white">{suite.data?.suite_code ?? "…"}</p>
            <p className="mt-0.5 text-xs text-slate-400">{suite.data?.case_count ?? 0} cases</p>
          </div>
          <Button onClick={execute} disabled={busy}>
            {busy ? "Running…" : "Run suite"}
          </Button>
        </div>
      </GlassPanel>

      {run ? (
        <div className="mb-4 grid gap-4 sm:grid-cols-3">
          <GlassPanel>
            <p className="text-xs uppercase tracking-[0.22em] text-slate-400">Pass rate</p>
            <p className="mt-2.5 text-3xl font-semibold tabular-nums text-white">
              {Math.round(run.pass_rate * 100)}%
            </p>
            <p className="mt-1.5 text-xs text-slate-500">
              {run.passed}/{run.total}
            </p>
          </GlassPanel>
          <GlassPanel>
            <p className="text-xs uppercase tracking-[0.22em] text-slate-400">Catches real problems</p>
            <p className="mt-2.5 text-3xl font-semibold tabular-nums text-white">
              {blocked ? `${blocked.passed}/${blocked.total}` : "—"}
            </p>
          </GlassPanel>
          <GlassPanel>
            <p className="text-xs uppercase tracking-[0.22em] text-slate-400">Leaves the rest alone</p>
            <p className="mt-2.5 text-3xl font-semibold tabular-nums text-white">
              {quiet ? `${quiet.passed}/${quiet.total}` : "—"}
            </p>
          </GlassPanel>
        </div>
      ) : null}

      <GlassPanel>
        <h2 className="mb-4 text-sm font-semibold text-white">
          {run ? "Results" : "Cases"}
        </h2>
        {suite.loading ? (
          <Skeleton rows={8} />
        ) : run && run.failures.length ? (
          <ul className="space-y-2">
            {run.failures.map((f) => (
              <li key={f.case_code} className="rounded-2xl border border-bad/30 bg-bad/5 p-4">
                <div className="flex items-center gap-2.5">
                  <Pill tone="bad">failed</Pill>
                  <span className="font-mono text-xs text-white">{f.case_code}</span>
                </div>
                <p className="mt-2 text-sm text-slate-300">{f.description}</p>
                <p className="mt-1.5 text-xs text-bad">{f.failure_reason}</p>
              </li>
            ))}
          </ul>
        ) : run ? (
          <p className="rounded-2xl border border-ok/30 bg-ok/5 p-4 text-sm text-ok">
            All {run.total} cases passed.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {(suite.data?.cases ?? []).map((c) => (
              <li
                key={c.case_code}
                className="flex items-start justify-between gap-4 rounded-2xl border border-hairline bg-white/5 px-4 py-2.5"
              >
                <div className="min-w-0">
                  <p className="font-mono text-xs text-white">{c.case_code}</p>
                  <p className="mt-0.5 text-xs text-slate-400">{c.description}</p>
                </div>
                <Pill tone={c.expects_block ? "warn" : "idle"}>
                  {c.expects_block ? "must block" : "must pass"}
                </Pill>
              </li>
            ))}
          </ul>
        )}
      </GlassPanel>
    </AppShell>
  );
}
