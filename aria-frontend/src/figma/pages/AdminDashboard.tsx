import { useCallback, useEffect, useState } from "react";
import { Activity, Database, RefreshCw, ShieldCheck, Users } from "lucide-react";
import { apiFetch } from "../../services/api";

interface AdminOverview {
  users_total: number;
  users_new_7d: number;
  analyses_total: number;
  analyses_7d: number;
  active_users_7d: number;
  last_activity: string | null;
  logins_total: number;
  logins_7d: number;
  page_visits_total: number;
  page_visits_7d: number;
  page_visits_by_page: Array<{ page: string; total: number; last_7d: number }>;
  recent_events: Array<{ event_type: string; page: string | null; occurred_at: string }>;
  system: Record<string, string>;
}

function formatLastActivity(value: string | null): string {
  if (!value) return "No saved analyses yet";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Activity recorded" : date.toLocaleString();
}

export default function AdminDashboard() {
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadOverview = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await apiFetch("/admin/overview");
      setOverview(result.overview as AdminOverview);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the admin overview.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  const cards = overview ? [
    {
      label: "Registered users",
      value: overview.users_total,
      detail: `${overview.users_new_7d} new in the last 7 days`,
      Icon: Users,
    },
    {
      label: "Active users",
      value: overview.active_users_7d,
      detail: "Users with a login or page visit in the last 7 days",
      Icon: Activity,
    },
    {
      label: "Saved analyses",
      value: overview.analyses_total,
      detail: `${overview.analyses_7d} in the last 7 days`,
      Icon: Database,
    },
    {
      label: "Successful logins",
      value: overview.logins_total,
      detail: `${overview.logins_7d} in the last 7 days`,
      Icon: ShieldCheck,
    },
    {
      label: "Page visits",
      value: overview.page_visits_total,
      detail: `${overview.page_visits_7d} in the last 7 days`,
      Icon: Activity,
    },
  ] : [];

  return (
    <main className="min-h-full bg-background px-6 py-6 md:px-8">
      <div className="mx-auto max-w-6xl">
        <div className="mb-7 flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/5 px-3 py-1 text-xs font-semibold text-primary">
              <ShieldCheck size={14} aria-hidden="true" />
              Administrator
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-foreground">Admin Dashboard</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Account activity and service status across this ARIA instance.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void loadOverview()}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-60"
          >
            <RefreshCw size={15} className={loading ? "animate-spin" : ""} aria-hidden="true" />
            Refresh
          </button>
        </div>

        {error && (
          <div role="alert" className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
            <span>{error}</span>
            <button type="button" onClick={() => void loadOverview()} className="font-semibold underline underline-offset-2">
              Try again
            </button>
          </div>
        )}

        {loading && !overview ? (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-label="Loading admin overview" aria-busy="true">
            {Array.from({ length: 3 }, (_, index) => (
              <div key={index} className="h-36 animate-pulse rounded-2xl border border-border bg-card" />
            ))}
          </div>
        ) : overview ? (
          <>
            <section aria-label="Usage overview" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {cards.map(({ label, value, detail, Icon }) => (
                <article key={label} className="rounded-2xl border border-border bg-card p-5 shadow-sm">
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-medium text-muted-foreground">{label}</p>
                    <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary/10 text-primary">
                      <Icon size={18} aria-hidden="true" />
                    </span>
                  </div>
                  <p className="mt-4 text-3xl font-bold tracking-tight text-foreground">{value.toLocaleString()}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
                </article>
              ))}
            </section>

            <section className="mt-5 grid gap-4 lg:grid-cols-2" aria-label="System status and page visits">
              <article className="rounded-2xl border border-border bg-card p-5 shadow-sm">
                <h2 className="text-sm font-semibold text-foreground">System status</h2>
                <p className="mt-1 text-xs text-muted-foreground">Live dependency checks and mail configuration.</p>
                <div className="mt-4 flex flex-wrap gap-3">
                  {Object.entries(overview.system).map(([name, status]) => {
                    const healthy = status === "available" || status === "configured";
                    const unknown = status === "not_configured" || status === "unknown";
                    return (
                      <div key={name} className="flex items-center gap-2 rounded-lg bg-secondary/70 px-3 py-2 text-sm">
                        <span
                          className={`h-2 w-2 rounded-full ${healthy ? "bg-emerald-500" : unknown ? "bg-amber-500" : "bg-destructive"}`}
                          aria-hidden="true"
                        />
                        <span className="font-medium capitalize text-foreground">{name.replaceAll("_", " ")}</span>
                        <span className="capitalize text-muted-foreground">{status.replaceAll("_", " ")}</span>
                      </div>
                    );
                  })}
                </div>
              </article>
              <article className="rounded-2xl border border-border bg-card p-5 shadow-sm">
                <h2 className="text-sm font-semibold text-foreground">Page visits by page</h2>
                <p className="mt-1 text-xs text-muted-foreground">All authenticated page visits; retained for 180 days.</p>
                {overview.page_visits_by_page.length ? (
                  <div className="mt-4 space-y-3">
                    {overview.page_visits_by_page.map((item) => {
                      const max = Math.max(...overview.page_visits_by_page.map((page) => page.total), 1);
                      return (
                        <div key={item.page}>
                          <div className="mb-1 flex justify-between gap-4 text-xs">
                            <span className="capitalize text-foreground">{item.page}</span>
                            <span className="text-muted-foreground">
                              {item.total.toLocaleString()} total · {item.last_7d.toLocaleString()} this week
                            </span>
                          </div>
                          <div className="h-1.5 overflow-hidden rounded-full bg-secondary">
                            <div className="h-full rounded-full bg-primary" style={{ width: `${(item.total / max) * 100}%` }} />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <p className="mt-5 text-sm text-muted-foreground">No page visits recorded yet.</p>
                )}
              </article>
            </section>

            <section className="mt-5 rounded-2xl border border-border bg-card p-5 shadow-sm" aria-label="Recent usage events">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="text-sm font-semibold text-foreground">Recent usage</h2>
                <p className="text-xs text-muted-foreground">
                  Last saved analysis: {formatLastActivity(overview.last_activity)}
                </p>
              </div>
              {overview.recent_events.length ? (
                <ul className="mt-4 divide-y divide-border">
                  {overview.recent_events.map((event, index) => (
                    <li key={`${event.event_type}-${event.occurred_at}-${index}`} className="flex flex-wrap justify-between gap-2 py-2.5 text-sm">
                      <span className="text-foreground">
                        {event.event_type === "login"
                          ? "Successful login"
                          : `Visited ${(event.page || "unknown").replaceAll("_", " ")}`}
                      </span>
                      <time className="text-xs text-muted-foreground" dateTime={event.occurred_at}>
                        {formatLastActivity(event.occurred_at)}
                      </time>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-4 text-sm text-muted-foreground">No logins or visits recorded yet.</p>
              )}
            </section>
          </>
        ) : null}
      </div>
    </main>
  );
}
