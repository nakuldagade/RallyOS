// Small shared UI building blocks (cards, badges, states).
import type { ReactNode } from "react";

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Card({ title, children, className = "", actions }: { title?: ReactNode; children: ReactNode; className?: string; actions?: ReactNode }) {
  return (
    <section className={`card p-4 ${className}`}>
      {(title || actions) && (
        <div className="mb-3 flex items-center justify-between gap-2">
          {title && <h2 className="text-sm font-semibold">{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

const TONES = {
  neutral: "bg-fg/10 text-fg/80",
  green: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
  red: "bg-rose-500/15 text-rose-600 dark:text-rose-400",
  amber: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
  blue: "bg-sky-500/15 text-sky-700 dark:text-sky-400",
} as const;

export function Badge({ children, tone = "neutral", title }: { children: ReactNode; tone?: keyof typeof TONES; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${TONES[tone]}`}>
      {children}
    </span>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="rounded-lg border border-border p-3">
      <div className="label">{label}</div>
      <div className="mt-1 text-xl font-semibold tabular-nums">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted">{hint}</div>}
    </div>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="card border-rose-500/40 p-4 text-sm">
      <div className="font-medium text-rose-500">Something went wrong</div>
      <div className="mt-1 text-muted">{message}</div>
      {/failed to fetch|networkerror|not found|unreachable/i.test(message) && (
        <div className="mt-1 text-xs text-muted">Is the backend running and up to date? Start it with <code>uvicorn api.main:app --port 8000</code> and refresh.</div>
      )}
      {onRetry && (
        <button onClick={onRetry} className="btn-ghost mt-3">
          Retry
        </button>
      )}
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-10 text-sm text-muted" role="status" aria-live="polite">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-border border-t-accent" />
      {label}
    </div>
  );
}

export function MockBanner() {
  return (
    <div className="mb-4 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-300">
      Backend offline or mock mode: showing <code>/mock/match.json</code>. Start the API to see live data.
    </div>
  );
}

export function ConfidenceBar({ value, tone = "accent" }: { value: number; tone?: "accent" | "red" | "amber" }) {
  const color = tone === "red" ? "bg-rose-500" : tone === "amber" ? "bg-amber-500" : "bg-accent";
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-fg/10">
      <div className={`h-full ${color}`} style={{ width: `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%` }} />
    </div>
  );
}
