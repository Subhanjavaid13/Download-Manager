"use client";

import type { InputHTMLAttributes, ReactNode } from "react";

export function Page({ children }: { children: ReactNode }) {
  return (
    <main className="mx-auto w-full max-w-md flex-1 px-4 pb-16 pt-6 sm:max-w-lg sm:pt-10">
      {children}
    </main>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-line bg-surface p-4 shadow-sm ${className}`}>
      {children}
    </section>
  );
}

export function Field({
  label,
  hint,
  ...input
}: { label: string; hint?: string } & InputHTMLAttributes<HTMLInputElement>) {
  const id = input.id ?? input.name;
  return (
    <label htmlFor={id} className="block">
      <span className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-muted">
        {label}
      </span>
      <input
        id={id}
        {...input}
        className="w-full rounded-lg border border-line bg-bg px-3 py-2.5 text-base text-ink placeholder:text-muted focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30"
      />
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

export function Button({
  children,
  tone = "primary",
  busy,
  className = "",
  ...rest
}: {
  children: ReactNode;
  tone?: "primary" | "secondary" | "danger";
  busy?: boolean;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const tones = {
    primary: "bg-accent text-white focus-visible:ring-accent",
    secondary: "border border-line text-ink-2 hover:bg-bg focus-visible:ring-accent/40",
    danger: "bg-danger text-white focus-visible:ring-danger",
  };
  return (
    <button
      {...rest}
      disabled={rest.disabled || busy}
      className={`rounded-lg px-4 py-2.5 text-sm font-semibold transition focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 ${tones[tone]} ${className}`}
    >
      {busy ? "Please wait…" : children}
    </button>
  );
}

export function Notice({
  tone = "info",
  children,
}: {
  tone?: "info" | "warn" | "error" | "ok";
  children: ReactNode;
}) {
  const tones = {
    info: "bg-accent-soft text-accent",
    warn: "bg-amber-soft text-amber",
    error: "bg-danger-soft text-danger",
    ok: "bg-ok-soft text-ok",
  };
  return <p className={`rounded-lg px-3 py-2 text-sm ${tones[tone]}`}>{children}</p>;
}

export function Divider({ label }: { label: string }) {
  return (
    <div className="my-4 flex items-center gap-3 text-xs uppercase tracking-wider text-muted">
      <span className="h-px flex-1 bg-line-soft" />
      {label}
      <span className="h-px flex-1 bg-line-soft" />
    </div>
  );
}
