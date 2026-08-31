"use client";

import { useState } from "react";
import { AppShell } from "@/components/shell/app-shell";
import { SystemMap } from "@/components/motion/system-map";
import {
  Button,
  EmptyState,
  ErrorState,
  Field,
  GlassPanel,
  Pill,
  SectionTitle,
  Skeleton,
  type Tone
} from "@/components/ui/primitives";
import { useApi } from "@/hooks/use-api";
import { api, ApiError } from "@/lib/api";
import type { AuditEntry, Member, Workspace } from "@/lib/types";

const ROLE_TONE: Record<Member["role"], Tone> = {
  owner: "info",
  editor: "ok",
  member: "idle",
  viewer: "idle"
};

export default function WorkspacesPage() {
  const workspaces = useApi<Workspace[]>(() => api.workspaces());
  const [selected, setSelected] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const members = useApi<Member[]>(
    () => (selected ? api.members(selected) : Promise.resolve([])),
    [selected]
  );
  const audit = useApi<AuditEntry[]>(
    () => (selected ? api.auditLog(selected) : Promise.resolve([])),
    [selected]
  );

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const created = await api.createWorkspace(name);
      setName("");
      await workspaces.refetch();
      setSelected(created.slug);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Something went wrong");
    }
  }

  return (
    <AppShell>
      <SectionTitle
        eyebrow="Access"
        title="Workspaces"
        subtitle="Membership decides who may approve a retcon or publish. Only workspaces you belong to appear here."
      />

      <div className="grid gap-4 xl:grid-cols-[340px_1fr]">
        <div className="space-y-4">
          <GlassPanel>
            <h2 className="mb-3 text-sm font-semibold text-white">Your workspaces</h2>
            {workspaces.loading ? (
              <Skeleton rows={3} />
            ) : workspaces.error ? (
              <ErrorState message={workspaces.error} onRetry={workspaces.refetch} />
            ) : (workspaces.data ?? []).length === 0 ? (
              <EmptyState title="You are not in any workspace yet." />
            ) : (
              <ul className="space-y-1.5">
                {(workspaces.data ?? []).map((w) => (
                  <li key={w.id}>
                    <button
                      onClick={() => setSelected(w.slug)}
                      aria-pressed={selected === w.slug}
                      className={
                        "w-full rounded-2xl border px-3.5 py-2.5 text-left transition " +
                        (selected === w.slug
                          ? "border-cyan/40 bg-cyan/10"
                          : "border-hairline bg-white/5 hover:bg-white/10")
                      }
                    >
                      <span className="block text-sm text-white">{w.name}</span>
                      <span className="mt-0.5 block font-mono text-xs text-slate-500">{w.slug}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </GlassPanel>

          <GlassPanel>
            <h2 className="mb-3 text-sm font-semibold text-white">New workspace</h2>
            <form onSubmit={create} className="space-y-3">
              <Field
                label="Name"
                name="workspace_name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                hint="You become its owner."
              />
              {error ? <p role="alert" className="text-xs text-bad">{error}</p> : null}
              <Button type="submit" className="w-full" disabled={!name.trim()}>
                Create
              </Button>
            </form>
          </GlassPanel>
        </div>

        <div className="space-y-4">
          {!selected ? (
            <GlassPanel>
              <EmptyState title="Select a workspace." hint="Members and its audit trail appear here." />
            </GlassPanel>
          ) : (
            <>
              <GlassPanel>
                <h2 className="mb-3 text-sm font-semibold text-white">Members</h2>
                {members.loading ? (
                  <Skeleton rows={3} />
                ) : (
                  <ul className="space-y-2">
                    {(members.data ?? []).map((m) => (
                      <li
                        key={m.user_id}
                        className="flex items-center justify-between gap-4 rounded-2xl border border-hairline bg-white/5 px-4 py-2.5"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-sm text-white">{m.full_name ?? m.email}</p>
                          <p className="truncate text-xs text-slate-500">{m.email}</p>
                        </div>
                        <Pill tone={ROLE_TONE[m.role]}>{m.role}</Pill>
                      </li>
                    ))}
                  </ul>
                )}
              </GlassPanel>

              <GlassPanel>
                <h2 className="mb-3 text-sm font-semibold text-white">Audit trail</h2>
                {audit.loading ? (
                  <Skeleton rows={4} />
                ) : (audit.data ?? []).length === 0 ? (
                  <EmptyState title="Nothing recorded yet." hint="Approvals and dispatches land here." />
                ) : (
                  <ul className="space-y-2">
                    {(audit.data ?? []).map((entry, index) => (
                      <li key={index} className="rounded-2xl border border-hairline bg-white/5 px-4 py-2.5">
                        <div className="flex flex-wrap items-center gap-2.5">
                          <span className="font-mono text-xs text-cyan">{entry.action}</span>
                          <span className="font-mono text-[10px] text-slate-600">
                            {entry.correlation_id?.slice(0, 8)}
                          </span>
                        </div>
                        <p className="mt-1.5 text-sm text-slate-300">{entry.message}</p>
                        <p className="mt-0.5 text-[10px] text-slate-600">{entry.created_at}</p>
                      </li>
                    ))}
                  </ul>
                )}
              </GlassPanel>

              <SystemMap
                nodes={[
                  { name: "Workspace", healthy: true, detail: selected },
                  { name: "Members", healthy: (members.data ?? []).length > 0, detail: `${(members.data ?? []).length}` },
                  { name: "Audit", healthy: !audit.error, detail: `${(audit.data ?? []).length} entries` }
                ]}
              />
            </>
          )}
        </div>
      </div>
    </AppShell>
  );
}
