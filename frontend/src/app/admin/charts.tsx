"use client";

/**
 * The dashboard's marks: stat tiles, a hero figure, stacked columns, bar lists,
 * a funnel and a meter. Plain HTML and CSS - no chart library, because the whole
 * page is a few hundred numbers and a dependency would cost more than it saves.
 *
 * Rules these follow, so every card reads as one system:
 *
 * - **Colour carries one job each.** Amber is audio and blue is video, the same
 *   pairing the download screen uses; green/amber is verified/unverified; red is
 *   reserved for failure and never used as "series 3"; the funnel is one blue
 *   hue in four steps because its stages are ordered. Every pairing that ends up
 *   adjacent in a stack was checked for colour-blind separation (deuteranopia
 *   and protanopia) against both themes' surfaces - which is why failures are
 *   not a red segment sitting on a green one anywhere on this page.
 * - **Identity is never colour alone.** Two or more series always get a legend,
 *   and every value is also reachable from the "Values" table under each chart
 *   and from the tooltip.
 * - **Thin marks, hairline grid, 2px of surface between touching fills.** The
 *   separation between stacked segments is a gap in the card colour, never a
 *   border drawn around the mark.
 * - **Both themes.** Everything is a design token from globals.css, so light and
 *   dark are the same code, and the dark values were picked by that pass rather
 *   than flipped automatically here.
 */

import { useState, type ReactNode } from "react";

import { longDay, shortDay } from "@/lib/admin-api";

/** The series colours, by the job each one does. */
export const HUE = {
  audio: "var(--amber)",
  video: "var(--accent)",
  verified: "var(--ok)",
  unverified: "var(--amber)",
  failure: "var(--danger)",
} as const;

/**
 * The funnel's four ordered stages: one hue, four monotone steps, mixed toward
 * the card so the ramp inverts correctly in dark mode. The lightest step still
 * clears 2:1 against the surface in both themes.
 */
export const FUNNEL_STEPS = [100, 78, 60, 45].map(
  (pct) => `color-mix(in srgb, var(--accent) ${pct}%, var(--surface))`,
);

export type Series = { key: string; label: string; color: string };

// ---------------------------------------------------------------------------
// Figures
// ---------------------------------------------------------------------------

/**
 * The one number the page leads with. Set in the body sans, not the display
 * face: a display face on a figure reads as decoration rather than data.
 */
export function Hero({
  label,
  value,
  note,
  aside,
}: {
  label: string;
  value: string;
  note: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <div className="flex items-end justify-between gap-4">
      <div className="min-w-0">
        <p className="text-label uppercase text-muted">{label}</p>
        <p className="mt-1 font-sans text-[3rem] font-semibold leading-none tracking-tight text-ink">
          {value}
        </p>
        <p className="mt-2 text-sm text-ink-2">{note}</p>
      </div>
      {aside}
    </div>
  );
}

export function StatTile({
  label,
  value,
  note,
  tone = "ink",
  children,
}: {
  label: string;
  value: string;
  note?: ReactNode;
  tone?: "ink" | "ok" | "warn" | "danger";
  children?: ReactNode;
}) {
  const tones = { ink: "text-ink", ok: "text-ok", warn: "text-amber", danger: "text-danger" };
  // dt/dd inside a wrapping div: these always sit in a <dl>, and a label/value
  // pair is exactly what a description list is for.
  return (
    <div className="overflow-hidden rounded-control border border-line-soft bg-bg/60 px-3 py-2.5">
      <dt className="text-label uppercase text-muted">{label}</dt>
      <dd
        className={`mt-1 whitespace-nowrap font-sans text-2xl font-semibold leading-none ${tones[tone]}`}
      >
        {value}
      </dd>
      {note && <dd className="mt-1.5 text-xs leading-snug text-muted">{note}</dd>}
      {children && <dd className="m-0">{children}</dd>}
    </div>
  );
}

/**
 * A ratio against a limit. The unfilled track is a lighter step of the fill's
 * own ramp, so the whole bar carries the state, not just the filled part.
 */
export function Meter({
  value,
  max = 100,
  tone,
  label,
}: {
  value: number;
  max?: number;
  tone: "ok" | "warn" | "danger";
  label: string;
}) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  const hue = { ok: "var(--ok)", warn: "var(--amber)", danger: "var(--danger)" }[tone];
  return (
    <div
      className="mt-2 h-2 overflow-hidden rounded-full"
      style={{ background: `color-mix(in srgb, ${hue} 18%, var(--surface))` }}
      role="progressbar"
      aria-label={label}
      aria-valuenow={Math.round(value)}
      aria-valuemin={0}
      aria-valuemax={max}
    >
      <div className="h-full rounded-full" style={{ width: `${pct}%`, background: hue }} />
    </div>
  );
}

/**
 * A trend, not a chart: no axes, no labels, the current point picked out. Falls
 * back to a flat rule rather than an empty box when every value is zero.
 */
export function Sparkline({ points, label }: { points: number[]; label: string }) {
  const w = 96;
  const h = 30;
  if (points.length < 2) return null;
  const max = Math.max(...points, 1);
  const step = w / (points.length - 1);
  const y = (v: number) => h - 3 - (v / max) * (h - 6);
  const d = points.map((v, i) => `${i ? "L" : "M"}${(i * step).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
  const last = points[points.length - 1];
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      width={w}
      height={h}
      role="img"
      aria-label={label}
      className="shrink-0 overflow-visible"
    >
      <path d={d} fill="none" stroke="var(--line)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      <circle
        cx={w}
        cy={y(last)}
        r="4"
        fill="var(--accent)"
        stroke="var(--surface)"
        strokeWidth="2"
      />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Legend and tables
// ---------------------------------------------------------------------------

export function Legend({ series }: { series: Series[] }) {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
      {series.map((s) => (
        <li key={s.key} className="flex items-center gap-1.5 text-xs text-ink-2">
          <span
            aria-hidden
            className="h-2.5 w-2.5 shrink-0 rounded-[3px]"
            style={{ background: s.color }}
          />
          {s.label}
        </li>
      ))}
    </ul>
  );
}

/**
 * The WCAG-clean twin of every chart on this page. Collapsed, but always there:
 * a tooltip must never be the only way to read a value.
 */
export function ValuesTable({
  columns,
  rows,
  caption = "Values",
}: {
  columns: string[];
  rows: (string | number)[][];
  caption?: string;
}) {
  if (!rows.length) return null;
  return (
    <details className="mt-3 border-t border-line-soft pt-2">
      <summary className="cursor-pointer list-none text-xs font-medium text-muted transition-ui hover:text-ink-2">
        {caption} ({rows.length})
      </summary>
      <div className="mt-2 max-h-64 overflow-auto">
        <table className="w-full text-left text-xs tabular-nums">
          <thead className="sticky top-0 bg-surface text-label uppercase text-muted">
            <tr>
              {columns.map((c, i) => (
                <th
                  key={c}
                  scope="col"
                  className={`whitespace-nowrap py-1.5 pr-3 font-medium ${i ? "text-right" : ""}`}
                >
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="text-ink-2">
            {rows.map((row, i) => (
              <tr key={i} className="border-t border-line-soft">
                {row.map((cell, j) => (
                  <td
                    key={j}
                    className={`whitespace-nowrap py-1.5 pr-3 ${j ? "text-right" : "text-ink"}`}
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

// ---------------------------------------------------------------------------
// Stacked columns over time
// ---------------------------------------------------------------------------

export type ColumnPoint = { day: string; values: number[]; extra?: [string, string][] };

/**
 * One column per day, segments stacked in `series` order.
 *
 * Days with nothing in them are still drawn, so a gap in the data reads as a
 * quiet day rather than as a missing one. Every column is a focusable hit area
 * spanning the full plot height, so the tooltip is reachable by keyboard and by
 * a thumb, not only by landing on a two-pixel bar.
 */
export function ColumnChart({
  points,
  series,
  unit,
  height = 132,
}: {
  points: ColumnPoint[];
  series: Series[];
  unit: string;
  height?: number;
}) {
  const [active, setActive] = useState<number | null>(null);

  const totals = points.map((p) => p.values.reduce((a, b) => a + b, 0));
  const peak = Math.max(...totals, 1);
  // Round the top of the scale up to something a person would say out loud.
  const step = peak <= 4 ? 1 : peak <= 10 ? 2 : Math.pow(10, Math.floor(Math.log10(peak))) / 2;
  const max = Math.max(step, Math.ceil(peak / step) * step);

  // With more than a fortnight of columns, label only every few days.
  const every = points.length <= 8 ? 1 : points.length <= 16 ? 3 : Math.ceil(points.length / 6);
  const crowded = points.length > 8;
  const labelled = points.map((_, i) => i).filter((i) => i % every === 0);
  // The most recent day is the one people look at first, so label it too -
  // unless it would land on top of the label before it.
  const last = points.length - 1;
  if (last > 0 && last - labelled[labelled.length - 1] >= Math.max(1, Math.ceil(every / 2))) {
    labelled.push(last);
  }
  // Only draw the halfway gridline when it lands on a whole number: "0.5
  // downloads" is not a thing anybody counts.
  const ticks = max % 2 === 0 ? [max, max / 2] : [max];

  return (
    <div>
      <div className="relative" style={{ height }}>
        {ticks.map((v) => (
          <div
            key={v}
            aria-hidden
            className="absolute inset-x-0 flex items-center"
            style={{ bottom: `${(v / max) * 100}%` }}
          >
            <span className="mr-1.5 bg-surface pr-0.5 text-[10px] leading-none tabular-nums text-muted">
              {v}
            </span>
            <span className="h-px flex-1 bg-line-soft" />
          </div>
        ))}

        <div className="absolute inset-0 flex items-end gap-px">
          {points.map((point, i) => {
            const total = totals[i];
            const dim = active !== null && active !== i;
            return (
              <button
                key={point.day}
                type="button"
                aria-label={`${longDay(point.day)}: ${total} ${unit}${
                  total
                    ? `, ${series
                        .map((s, j) => `${point.values[j]} ${s.label.toLowerCase()}`)
                        .join(", ")}`
                    : ""
                }`}
                onMouseEnter={() => setActive(i)}
                onMouseLeave={() => setActive((c) => (c === i ? null : c))}
                onFocus={() => setActive(i)}
                onBlur={() => setActive((c) => (c === i ? null : c))}
                className="group relative flex h-full flex-1 cursor-default flex-col justify-end rounded-sm focus-visible:outline-offset-0"
              >
                <span
                  aria-hidden
                  className={`mx-auto flex w-full max-w-6 flex-col-reverse gap-0.5 transition-ui ${
                    dim ? "opacity-45" : "opacity-100"
                  }`}
                  style={{ height: `${(total / max) * 100}%` }}
                >
                  {series.map((s, j) => {
                    const value = point.values[j];
                    if (!value) return null;
                    const isTop = series.slice(j + 1).every((_, k) => !point.values[j + 1 + k]);
                    return (
                      <span
                        key={s.key}
                        className={isTop ? "rounded-t-sm" : ""}
                        style={{ height: `${(value / total) * 100}%`, background: s.color }}
                      />
                    );
                  })}
                </span>
                {total === 0 && (
                  <span aria-hidden className="mx-auto h-px w-full max-w-6 bg-line" />
                )}
              </button>
            );
          })}
        </div>

        <div aria-hidden className="absolute inset-x-0 bottom-0 h-px bg-line" />

        {active !== null && (
          <div
            aria-hidden
            className="pointer-events-none absolute bottom-full z-10 mb-1 w-max max-w-[13rem] rounded-control border border-line bg-surface px-2.5 py-2 text-xs shadow-pop"
            style={{
              left: `${((active + 0.5) / points.length) * 100}%`,
              transform: `translateX(${
                (active + 0.5) / points.length < 0.22
                  ? "0%"
                  : (active + 0.5) / points.length > 0.78
                    ? "-100%"
                    : "-50%"
              })`,
            }}
          >
            <p className="font-medium text-ink">{longDay(points[active].day)}</p>
            <ul className="mt-1 space-y-0.5">
              {series.map((s, j) => (
                <li key={s.key} className="flex items-center gap-1.5 text-ink-2">
                  <span
                    className="h-2 w-2 shrink-0 rounded-[2px]"
                    style={{ background: s.color }}
                  />
                  <span className="flex-1">{s.label}</span>
                  <span className="tabular-nums text-ink">{points[active].values[j]}</span>
                </li>
              ))}
              {(points[active].extra ?? []).map(([k, v]) => (
                <li key={k} className="flex gap-3 text-muted">
                  <span className="flex-1">{k}</span>
                  <span className="tabular-nums">{v}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* The axis is its own layer rather than one label per column: at 30 or 90
          days a column is a few pixels wide, and a label confined to it would be
          truncated to a single letter. Positioned labels can be wider than the
          column they name, and the two at the ends are pinned inside the plot. */}
      <div aria-hidden className="relative mt-1.5 h-3">
        {labelled.map((i) => {
          const at = (i + 0.5) / points.length;
          return (
            <span
              key={points[i].day}
              className={`absolute whitespace-nowrap text-[10px] leading-none ${
                active === i ? "text-ink" : "text-muted"
              }`}
              style={{
                left: `${at * 100}%`,
                // Centred on its column, except at the two ends of a crowded
                // axis, where half a centred label would hang off the plot.
                // With a week on screen the columns are wide enough that
                // pinning the ends only shoves them into their neighbours.
                transform: `translateX(${
                  !crowded ? "-50%" : at < 0.08 ? "0%" : at > 0.92 ? "-100%" : "-50%"
                })`,
              }}
            >
              {shortDay(points[i].day)}
            </span>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Horizontal bars
// ---------------------------------------------------------------------------

export type BarRow = { key: string; label: ReactNode; value: number; color: string; note?: string };

/**
 * Ranked bars for things that are not a time series: formats, error codes.
 *
 * The value sits outside the bar, in ink, always. Setting it inside the fill
 * looks tidier until the fill is a light amber in dark mode, where white digits
 * on it are unreadable and dark digits are unreadable in light mode - and a
 * short bar has nowhere to put it at all. Outside, it is legible on every fill
 * in both themes and no bar can ever clip its own label.
 */
export function BarList({ rows, unit }: { rows: BarRow[]; unit: string }) {
  const max = Math.max(...rows.map((r) => r.value), 1);
  const width = `${Math.max(2, String(max).length)}ch`;
  return (
    <ul className="space-y-2.5">
      {rows.map((row) => (
        <li key={row.key}>
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="min-w-0 truncate text-ink">{row.label}</span>
            {row.note && <span className="shrink-0 text-xs text-muted">{row.note}</span>}
          </div>
          <div className="mt-1 flex items-center gap-2">
            <div className="h-3 min-w-0 flex-1 rounded-r-sm bg-surface-2">
              <div
                className="h-full rounded-r-sm"
                style={{
                  width: `${Math.max((row.value / max) * 100, row.value ? 2 : 0)}%`,
                  background: row.color,
                }}
              />
            </div>
            <span
              className="shrink-0 text-right text-xs font-medium tabular-nums text-ink"
              style={{ minWidth: width }}
            >
              {row.value}
            </span>
            <span className="sr-only">{unit}</span>
          </div>
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// Funnel
// ---------------------------------------------------------------------------

export type FunnelRow = { key: string; label: string; count: number; conversion: string; note?: string | null };

/**
 * Ordered stages, so the colour is one hue getting lighter as the funnel
 * narrows. The width is the share of the first stage; the conversion figure
 * beside it is the share of the stage before, which is the number that says
 * where people are actually lost.
 */
export function Funnel({ rows }: { rows: FunnelRow[] }) {
  const start = Math.max(rows[0]?.count ?? 0, 1);
  return (
    <ol className="space-y-3">
      {rows.map((row, i) => (
        <li key={row.key}>
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-sm font-medium text-ink">{row.label}</span>
            <span className="shrink-0 text-sm tabular-nums text-ink">
              {row.count}
              {i > 0 && <span className="ml-1.5 text-xs text-muted">{row.conversion}</span>}
            </span>
          </div>
          <div className="mt-1 h-2.5 overflow-hidden rounded-r-sm bg-surface-2">
            <div
              className="h-full rounded-r-sm"
              style={{
                width: `${Math.max((row.count / start) * 100, row.count ? 2 : 0)}%`,
                background: FUNNEL_STEPS[Math.min(i, FUNNEL_STEPS.length - 1)],
              }}
            />
          </div>
          {row.note && <p className="mt-1 text-xs text-muted">{row.note}</p>}
        </li>
      ))}
    </ol>
  );
}

/** A card heading with an optional one-line explanation underneath. */
export function CardTitle({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="mb-3">
      <h2 className="font-display text-title text-ink">{title}</h2>
      {hint && <p className="mt-0.5 text-xs text-muted">{hint}</p>}
    </div>
  );
}

/** Nothing to draw, and why - better than an empty axis. */
export function NoData({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-control border border-dashed border-line px-3 py-6 text-center text-sm text-muted">
      {children}
    </p>
  );
}
