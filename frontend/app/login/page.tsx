"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { saveToken } from "@/lib/auth";
import { Button, Field, GlassPanel } from "@/components/ui/primitives";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [mode, setMode] = useState<"login" | "register">("login");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "register") {
        await api.register(email, name, password);
      }
      const { access_token } = await api.login(email, password);
      saveToken(access_token);
      router.replace("/dashboard");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <GlassPanel className="w-full max-w-md" scan>
        <p className="text-[11px] uppercase tracking-[0.3em] text-cyan/60">Anime Pipeline</p>
        <h1 className="mt-2.5 text-2xl font-semibold text-white">
          {mode === "login" ? "Sign in" : "Create an account"}
        </h1>
        <p className="mt-1.5 text-sm text-slate-400">
          {mode === "login"
            ? "Continuity gates, generation and the job queue."
            : "The first account created becomes the superuser."}
        </p>

        {/* method="post" matters even though onSubmit always preventDefaults: if the
            JS bundle fails to load, the browser falls back to a native submit, and
            a GET would put the password in the URL, the history and every proxy log
            along the way. */}
        <form method="post" onSubmit={submit} className="mt-6 space-y-4">
          {mode === "register" ? (
            <Field
              label="Full name"
              name="full_name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              autoComplete="name"
            />
          ) : null}
          <Field
            label="Email"
            name="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
          />
          <Field
            label="Password"
            name="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={mode === "register" ? 12 : undefined}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            hint={mode === "register" ? "At least 12 characters." : undefined}
          />

          {error ? (
            <p role="alert" className="rounded-2xl border border-bad/30 bg-bad/10 px-4 py-2.5 text-sm text-bad">
              {error}
            </p>
          ) : null}

          <Button type="submit" disabled={busy} className="w-full">
            {busy ? "Working…" : mode === "login" ? "Sign in" : "Create account"}
          </Button>
        </form>

        <button
          onClick={() => {
            setMode(mode === "login" ? "register" : "login");
            setError(null);
          }}
          className="mt-4 w-full text-center text-xs text-slate-400 hover:text-white"
        >
          {mode === "login" ? "No account? Create one" : "Already have an account? Sign in"}
        </button>
      </GlassPanel>
    </main>
  );
}
