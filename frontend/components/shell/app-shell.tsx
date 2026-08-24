"use client";

import clsx from "clsx";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api, setUnauthorizedHandler } from "@/lib/api";
import { clearToken, getToken } from "@/lib/auth";
import { Skeleton } from "@/components/ui/primitives";
import type { User } from "@/lib/types";

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/pipeline", label: "Pipeline" },
  { href: "/jobs", label: "Jobs" },
  { href: "/generation", label: "Generation" },
  { href: "/evaluation", label: "Evaluation" },
  { href: "/workspaces", label: "Workspaces" }
];

/**
 * Route protection.
 *
 * Client-side only, and that is a real limit worth naming: this hides a UI, it
 * does not protect data. Every route it guards is enforced again by the
 * backend's bearer-token dependency, which is where the actual authorization
 * lives. Middleware could redirect earlier, but it still would not be a
 * security boundary.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    setUnauthorizedHandler(() => router.replace("/login"));
    return () => setUnauthorizedHandler(null);
  }, [router]);

  useEffect(() => {
    let alive = true;
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    api
      .me()
      .then((me) => alive && setUser(me))
      .catch(() => alive && router.replace("/login"))
      .finally(() => alive && setChecking(false));
    return () => {
      alive = false;
    };
  }, [router]);

  if (checking || !user) {
    return (
      <div className="mx-auto max-w-3xl p-6">
        <Skeleton rows={6} />
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      <div aria-hidden className="tech-grid pointer-events-none fixed inset-0 opacity-[0.14]" />
      <div className="relative mx-auto grid max-w-[1600px] gap-4 p-4 lg:grid-cols-[248px_1fr]">
        <aside className="glass holo relative h-fit rounded-3xl p-4 lg:sticky lg:top-4">
          <div className="px-3 pb-5 pt-2">
            <p className="text-[10px] uppercase tracking-[0.32em] text-cyan/60">Anime Pipeline</p>
            <p className="mt-1.5 text-lg font-semibold text-white">Control</p>
          </div>
          <nav aria-label="Main">
            <ul className="space-y-1.5">
              {NAV.map((item) => {
                const active = pathname === item.href;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      aria-current={active ? "page" : undefined}
                      className={clsx(
                        "block rounded-2xl px-4 py-2.5 text-sm transition",
                        active
                          ? "bg-cyan/12 text-cyan shadow-glow"
                          : "text-slate-300 hover:bg-white/5 hover:text-white"
                      )}
                    >
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>
          <div className="mt-6 border-t border-hairline pt-4">
            <p className="truncate px-3 text-xs text-slate-400" title={user.email}>
              {user.email}
            </p>
            <button
              onClick={() => {
                clearToken();
                router.replace("/login");
              }}
              className="mt-2 w-full rounded-2xl px-3 py-2 text-left text-xs text-slate-400 hover:bg-white/5 hover:text-white"
            >
              Sign out
            </button>
          </div>
        </aside>
        <main>{children}</main>
      </div>
    </div>
  );
}
