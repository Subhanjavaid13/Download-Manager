"use client";

import type { InputHTMLAttributes, ReactNode } from "react";

import { AlertIcon } from "@/components/icons";

/**
 * The single column every screen lives in. `dock` reserves the right amount of
 * room at the bottom: the navigation bar alone, or the navigation bar plus the
 * home page's action bar.
 */
export function Page({
  children,
  dock = "nav",
}: {
  children: ReactNode;
  dock?: "nav" | "action";
}) {
  return (
    <main
      id="main"
      tabIndex={-1}
      className={`mx-auto w-full max-w-md flex-1 px-gutter pt-6 focus:outline-none sm:max-w-lg sm:pt-10 ${
        dock === "action" ? "pb-dock-action" : "pb-dock"
      }`}
    >
      {children}
    </main>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <section
      className={`rounded-card border border-line bg-surface p-card shadow-card ${className}`}
    >
      {children}
    </section>
  );
}

/** Small uppercase eyebrow above a group of controls. */
export function SectionLabel({ children, id }: { children: ReactNode; id?: string }) {
  return (
    <h2 id={id} className="mb-2 text-label uppercase text-muted">
      {children}
    </h2>
  );
}

export function Field({
  label,
  hint,
  error,
  ...input
}: {
  label: string;
  hint?: string;
  error?: string;
} & InputHTMLAttributes<HTMLInputElement>) {
  const id = input.id ?? input.name;
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-label uppercase text-muted">
        {label}
      </label>
      <input
        id={id}
        aria-describedby={[hintId, errorId].filter(Boolean).join(" ") || undefined}
        aria-invalid={error ? true : undefined}
        {...input}
        className={`tap w-full rounded-control border bg-bg px-3 py-2.5 text-base text-ink transition-ui placeholder:text-muted ${
          error ? "border-danger" : "border-line focus:border-accent"
        }`}
      />
      {hint && (
        <p id={hintId} className="mt-1 text-xs text-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className="mt-1 text-xs font-medium text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

export function Button({
  children,
  tone = "primary",
  busy,
  busyLabel = "Working…",
  className = "",
  ...rest
}: {
  children: ReactNode;
  tone?: "primary" | "secondary" | "danger" | "ok" | "audio";
  busy?: boolean;
  busyLabel?: string;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const tones = {
    primary: "bg-accent text-on-accent hover:opacity-90",
    audio: "bg-amber text-on-amber hover:opacity-90",
    ok: "bg-ok text-on-ok hover:opacity-90",
    danger: "bg-danger text-on-danger hover:opacity-90",
    secondary: "border border-line bg-surface text-ink-2 hover:bg-surface-2",
  };
  return (
    <button
      {...rest}
      disabled={rest.disabled || busy}
      aria-busy={busy || undefined}
      className={`tap inline-flex items-center justify-center gap-2 rounded-control px-4 py-2.5 text-sm font-semibold transition-ui disabled:cursor-not-allowed disabled:opacity-45 ${tones[tone]} ${className}`}
    >
      {busy ? busyLabel : children}
    </button>
  );
}

export function Notice({
  tone = "info",
  children,
  className = "",
}: {
  tone?: "info" | "warn" | "error" | "ok";
  children: ReactNode;
  className?: string;
}) {
  const tones = {
    info: "bg-accent-soft text-accent",
    warn: "bg-amber-soft text-amber",
    error: "bg-danger-soft text-danger",
    ok: "bg-ok-soft text-ok",
  };
  return (
    <p
      role={tone === "error" ? "alert" : undefined}
      className={`rounded-control px-3 py-2 text-sm ${tones[tone]} ${className}`}
    >
      {children}
    </p>
  );
}

export function Divider({ label }: { label: string }) {
  return (
    <div className="my-4 flex items-center gap-3 text-label uppercase text-muted">
      <span className="h-px flex-1 bg-line-soft" aria-hidden />
      {label}
      <span className="h-px flex-1 bg-line-soft" aria-hidden />
    </div>
  );
}

/** A shimmering placeholder. Give it a width/height so nothing shifts later. */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton rounded ${className}`} aria-hidden />;
}

/** Nothing here yet, and what to do about it. */
export function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon?: ReactNode;
  title: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-card border border-dashed border-line bg-surface/60 px-4 py-8 text-center">
      {icon && (
        <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-surface-2 text-muted">
          {icon}
        </div>
      )}
      <p className="text-title text-ink">{title}</p>
      <p className="mx-auto mt-1 max-w-xs text-sm text-muted">{body}</p>
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

/** Something went wrong, with a way out. */
export function ErrorState({
  title,
  body,
  onRetry,
  retryLabel = "Try again",
}: {
  title: string;
  body: string;
  onRetry?: () => void;
  retryLabel?: string;
}) {
  return (
    <div
      role="alert"
      className="rounded-card border border-danger/40 bg-danger-soft/60 px-4 py-6 text-center"
    >
      <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-danger-soft text-danger">
        <AlertIcon />
      </div>
      <p className="text-title text-ink">{title}</p>
      <p className="mx-auto mt-1 max-w-xs text-sm text-ink-2">{body}</p>
      {onRetry && (
        <div className="mt-4 flex justify-center">
          <Button type="button" tone="secondary" onClick={onRetry}>
            {retryLabel}
          </Button>
        </div>
      )}
    </div>
  );
}
