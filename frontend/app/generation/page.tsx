"use client";

import { useState } from "react";
import { AppShell } from "@/components/shell/app-shell";
import {
  Button,
  ErrorState,
  Field,
  GlassPanel,
  Pill,
  SectionTitle,
  Skeleton
} from "@/components/ui/primitives";
import { useApi } from "@/hooks/use-api";
import { api, ApiError } from "@/lib/api";
import type { MediaProviderInfo, PromptTemplate, ProviderInfo } from "@/lib/types";

export default function GenerationPage() {
  const templates = useApi<{ templates: PromptTemplate[] }>(() => api.templates());
  const providers = useApi<{
    providers: Record<string, ProviderInfo>;
    media_providers: Record<string, MediaProviderInfo>;
  }>(() => api.providers());

  const [selected, setSelected] = useState<string | null>(null);
  const [episode, setEpisode] = useState("EP01");
  const [provider, setProvider] = useState("mock");
  const [preview, setPreview] = useState<{ system: string; prompt: string; prompt_chars: number } | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Something went wrong");
      return null;
    } finally {
      setBusy(false);
    }
  }

  const providerList = Object.values(providers.data?.providers ?? {});
  const mediaList = Object.values(providers.data?.media_providers ?? {});

  return (
    <AppShell>
      <SectionTitle
        eyebrow="Generation"
        title="Prompts and providers"
        subtitle="Preview renders the real canon block for an episode without spending a token."
      />

      {error ? <div className="mb-4"><ErrorState message={error} /></div> : null}

      <div className="grid gap-4 xl:grid-cols-[340px_1fr]">
        <div className="space-y-4">
          {/* Text and media are listed apart because they are configured
              apart: a deployment can run a real LLM behind a mock image
              generator, and one merged list would hide that. */}
          <GlassPanel>
            <h2 className="mb-3 text-sm font-semibold text-white">Text providers</h2>
            {providers.loading ? (
              <Skeleton rows={3} />
            ) : (
              <ul className="space-y-2">
                {providerList.map((p) => (
                  <li key={p.provider_key} className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm text-white">{p.provider_key}</p>
                      <p className="truncate text-xs text-slate-500">{p.default_model ?? "no default model"}</p>
                    </div>
                    <Pill tone={p.configured ? "ok" : "idle"}>
                      {p.configured ? "ready" : "no key"}
                    </Pill>
                  </li>
                ))}
              </ul>
            )}
          </GlassPanel>

          <GlassPanel>
            <h2 className="mb-1 text-sm font-semibold text-white">Media providers</h2>
            <p className="mb-3 text-xs text-slate-500">
              Image, video and audio. Nothing in the episode workflow calls these yet.
            </p>
            {providers.loading ? (
              <Skeleton rows={2} />
            ) : (
              <ul className="space-y-2">
                {mediaList.map((p) => (
                  <li key={p.provider_key} className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm text-white">{p.provider_key}</p>
                      <p className="truncate text-xs text-slate-500">
                        {p.default_model ?? "no default model"} · {p.kinds.join(", ")}
                      </p>
                    </div>
                    <Pill tone={p.configured ? "ok" : "idle"}>
                      {p.configured ? "ready" : "no key"}
                    </Pill>
                  </li>
                ))}
              </ul>
            )}
          </GlassPanel>

          <GlassPanel>
            <h2 className="mb-3 text-sm font-semibold text-white">Templates</h2>
            {templates.loading ? (
              <Skeleton rows={5} />
            ) : (
              <ul className="space-y-1.5">
                {(templates.data?.templates ?? []).map((t) => (
                  <li key={t.key}>
                    <button
                      onClick={() => {
                        setSelected(t.key);
                        setPreview(null);
                        setResult(null);
                      }}
                      aria-pressed={selected === t.key}
                      className={
                        "w-full rounded-2xl border px-3.5 py-2.5 text-left transition " +
                        (selected === t.key
                          ? "border-cyan/40 bg-cyan/10"
                          : "border-hairline bg-white/5 hover:bg-white/10")
                      }
                    >
                      <span className="block text-sm text-white">{t.key}</span>
                      <span className="mt-0.5 block text-xs text-slate-400">{t.purpose}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </GlassPanel>
        </div>

        <div className="space-y-4">
          <GlassPanel>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Episode" name="episode" value={episode} onChange={(e) => setEpisode(e.target.value)} />
              <label className="block">
                <span className="mb-1.5 block text-xs uppercase tracking-wider text-slate-400">Provider</span>
                <select
                  value={provider}
                  onChange={(e) => setProvider(e.target.value)}
                  className="w-full rounded-2xl border border-hairline bg-white/5 px-4 py-2.5 text-sm text-white"
                >
                  {providerList.map((p) => (
                    <option key={p.provider_key} value={p.provider_key} className="bg-ink">
                      {p.provider_key}
                      {p.configured ? "" : " (no key)"}
                    </option>
                  ))}
                </select>
              </label>
              <div className="flex items-end gap-2">
                <Button
                  disabled={!selected || busy}
                  onClick={() =>
                    act(async () => {
                      const body = await api.previewPrompt(selected!, episode);
                      setPreview(body);
                      setResult(null);
                    })
                  }
                >
                  Preview
                </Button>
                <Button
                  tone="ok"
                  disabled={!selected || busy}
                  onClick={() =>
                    act(async () => {
                      const body = await api.runGeneration({
                        template_key: selected,
                        episode_code: episode,
                        provider_key: provider,
                        background: true
                      });
                      setResult(JSON.stringify(body, null, 2));
                    })
                  }
                >
                  Queue
                </Button>
              </div>
            </div>
          </GlassPanel>

          {preview ? (
            <GlassPanel>
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-semibold text-white">Rendered prompt</h2>
                <Pill tone="info">{preview.prompt_chars} chars</Pill>
              </div>
              {preview.system ? (
                <>
                  <p className="mb-1.5 text-xs uppercase tracking-wider text-slate-400">System</p>
                  <pre className="mb-4 overflow-x-auto whitespace-pre-wrap rounded-2xl border border-hairline bg-ink/60 p-4 text-xs text-slate-300">
                    {preview.system}
                  </pre>
                </>
              ) : null}
              <pre className="overflow-x-auto whitespace-pre-wrap rounded-2xl border border-hairline bg-ink/60 p-4 text-xs text-slate-200">
                {preview.prompt}
              </pre>
            </GlassPanel>
          ) : null}

          {result ? (
            <GlassPanel>
              <h2 className="mb-3 text-sm font-semibold text-white">Dispatched</h2>
              <pre className="overflow-x-auto rounded-2xl border border-hairline bg-ink/60 p-4 text-xs text-slate-200">
                {result}
              </pre>
            </GlassPanel>
          ) : null}
        </div>
      </div>
    </AppShell>
  );
}
