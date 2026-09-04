"use client";

/**
 * The dashboard itself: one page that answers "how many real users did I get
 * this week and what did they download".
 *
 * Reading order is deliberate. The answer comes first, in a sentence and a
 * single figure. Anything that needs a decision comes second, and only when
 * there is something - a card that is always there stops being read. Then the
 * detail, in the order the questions are usually asked: what they took, whether
 * it worked, who signed up, where they dropped out, who they are, and finally
 * whether the data hygiene promise is being kept.
 *
 * This component only renders; fetching, the range control and the access check
 * are in page.tsx.
 */

import type { ReactNode } from "react";

import { Card, Notice } from "@/components/ui";
import {
  bytes,
  compact,
  duration,
  longDay,
  percent,
  shortDate,
  type FormatRow,
  type Overview,
} from "@/lib/admin-api";
import {
  BarList,
  CardTitle,
  ColumnChart,
  Funnel,
  Hero,
  HUE,
  Legend,
  Meter,
  NoData,
  Sparkline,
  StatTile,
  ValuesTable,
  type Series,
} from "./charts";

const DOWNLOAD_SERIES: Series[] = [
  { key: "audio", label: "Audio", color: HUE.audio },
  { key: "video", label: "Video", color: HUE.video },
];

const SIGNUP_SERIES: Series[] = [
  { key: "verified", label: "Verified", color: HUE.verified },
  { key: "unverified", label: "Not verified", color: HUE.unverified },
];

/**
 * "MP3 192 kbps", "OPUS", "MP4 1080p". The quality is always included when there
 * is one: rows are grouped by mode, format *and* quality, so leaving it off gives
 * two rows with the same name and no way to tell them apart.
 */
function formatLabel(row: FormatRow): string {
  if (row.mode === "audio") {
    return row.quality ? `${row.format.toUpperCase()} ${row.quality} kbps` : row.format.toUpperCase();
  }
  return row.quality && row.quality !== "best" ? `MP4 ${row.quality}p` : "MP4 best";
}

type Attention = { key: string; tone: "warn" | "error"; text: ReactNode };

/** What an operator would want to be told without going looking for it. */
function attentionItems(data: Overview): Attention[] {
  const items: Attention[] = [];
  const { downloads, accounts, retention } = data;
  const rate = downloads.totals.success_rate;
  if (rate !== null && rate < 90 && downloads.totals.failed > 0) {
    const worst = downloads.errors[0];
    items.push({
      key: "failures",
      tone: rate < 70 ? "error" : "warn",
      text: (
        <>
          {downloads.totals.failed} of {downloads.totals.done + downloads.totals.failed} downloads
          failed ({percent(rate)} succeeded)
          {worst ? `, mostly "${worst.code}"` : ""}. Check the yt-dlp version on /health.
        </>
      ),
    });
  }
  if (accounts.totals.flagged > 0) {
    items.push({
      key: "flagged",
      tone: "warn",
      text: (
        <>
          {accounts.totals.flagged} account{accounts.totals.flagged === 1 ? "" : "s"} flagged by the
          email checks. They are listed under Accounts.
        </>
      ),
    });
  }
  if (retention.overdue > 0) {
    items.push({
      key: "retention",
      tone: "error",
      text: (
        <>
          {compact(retention.overdue)} events are older than {retention.keep_days} days. The nightly
          prune job has not run - check the prune-events workflow.
        </>
      ),
    });
  }
  return items;
}

export function Dashboard({ data }: { data: Overview }) {
  const { summary, signups, active_users: active, downloads, timing, accounts, funnels } = data;
  const attention = attentionItems(data);
  const settled = downloads.totals.done + downloads.totals.failed;

  return (
    <div className="space-y-4">
      {/* ---------------------------------------------------------------- */}
      {/* The answer                                                       */}
      {/* ---------------------------------------------------------------- */}
      <Card>
        <Hero
          label={`People in the last ${data.range.days} days`}
          value={compact(summary.active_users)}
          note={
            <>
              <span className="font-medium text-ink">{summary.active_signed_in}</span> with an
              account,{" "}
              <span className="font-medium text-ink">
                {summary.active_users - summary.active_signed_in}
              </span>{" "}
              guest{summary.active_users - summary.active_signed_in === 1 ? "" : "s"} · they took{" "}
              <span className="font-medium text-ink">{compact(summary.downloads)}</span> download
              {summary.downloads === 1 ? "" : "s"}
            </>
          }
          aside={
            <Sparkline
              points={active.daily.map((d) => d.total)}
              label={`Daily people over the last ${data.range.days} days`}
            />
          }
        />
        <dl className="mt-4 grid grid-cols-2 gap-2">
          <StatTile
            label="Sign-ups"
            value={compact(summary.signups)}
            note={
              summary.signups
                ? `${summary.verified_signups} verified`
                : summary.refused_signups
                  ? `${summary.refused_signups} refused`
                  : "no new accounts"
            }
          />
          <StatTile
            label="Downloads"
            value={compact(summary.downloads)}
            note={`${summary.downloads_done} finished · ${bytes(summary.bytes)}`}
          />
          <StatTile
            label="Success rate"
            value={percent(summary.success_rate, "n/a")}
            tone={
              summary.success_rate === null
                ? "ink"
                : summary.success_rate >= 90
                  ? "ok"
                  : summary.success_rate >= 70
                    ? "warn"
                    : "danger"
            }
            note={settled ? `of ${settled} that ran to an end` : "nothing has run yet"}
          >
            {summary.success_rate !== null && (
              <Meter
                value={summary.success_rate}
                tone={
                  summary.success_rate >= 90 ? "ok" : summary.success_rate >= 70 ? "warn" : "danger"
                }
                label="Download success rate"
              />
            )}
          </StatTile>
          <StatTile
            label="Median wait"
            value={duration(summary.median_sec)}
            note={
              timing.samples
                ? `${timing.samples} file${timing.samples === 1 ? "" : "s"} · 90th ${duration(timing.p90_sec)}`
                : "nothing finished yet"
            }
          />
        </dl>
      </Card>

      {/* ---------------------------------------------------------------- */}
      {/* Anything that needs a decision                                   */}
      {/* ---------------------------------------------------------------- */}
      {attention.length > 0 ? (
        <section aria-labelledby="attention-heading" className="space-y-2">
          <h2 id="attention-heading" className="text-label uppercase text-muted">
            Needs attention
          </h2>
          {attention.map((item) => (
            <Notice key={item.key} tone={item.tone}>
              {item.text}
            </Notice>
          ))}
        </section>
      ) : (
        <p className="px-1 text-xs text-ok">
          Nothing needs attention: no failures worth chasing, no flagged accounts, retention on
          schedule.
        </p>
      )}

      {/* ---------------------------------------------------------------- */}
      {/* What they downloaded                                             */}
      {/* ---------------------------------------------------------------- */}
      <Card>
        <CardTitle
          title="Downloads per day"
          hint="Every job started, whether or not it finished."
        />
        <div className="mb-3">
          <Legend series={DOWNLOAD_SERIES} />
        </div>
        {downloads.totals.total === 0 ? (
          <NoData>Nobody downloaded anything in this range.</NoData>
        ) : (
          <ColumnChart
            points={downloads.daily.map((d) => ({
              day: d.day,
              values: [d.audio, d.video],
              extra: [
                ["Finished", String(d.done)],
                ["Failed", String(d.failed)],
                ["Cancelled", String(d.cancelled)],
              ],
            }))}
            series={DOWNLOAD_SERIES}
            unit="downloads"
          />
        )}
        <ValuesTable
          columns={["Day", "Audio", "Video", "Done", "Failed", "Cancelled"]}
          rows={downloads.daily.map((d) => [
            longDay(d.day),
            d.audio,
            d.video,
            d.done,
            d.failed,
            d.cancelled,
          ])}
        />
      </Card>

      <Card>
        <CardTitle title="What they took" hint="Mode, format and quality, most popular first." />
        <div className="mb-3">
          <Legend series={DOWNLOAD_SERIES} />
        </div>
        {downloads.by_format.length === 0 ? (
          <NoData>No downloads in this range.</NoData>
        ) : (
          <BarList
            unit="downloads"
            rows={downloads.by_format.slice(0, 8).map((row) => ({
              key: `${row.mode}-${row.format}-${row.quality ?? ""}`,
              label: formatLabel(row),
              value: row.total,
              color: row.mode === "audio" ? HUE.audio : HUE.video,
              note: row.bytes ? bytes(row.bytes) : undefined,
            }))}
          />
        )}
        <ValuesTable
          columns={["Format", "Started", "Finished", "Bytes"]}
          rows={downloads.by_format.map((r) => [
            formatLabel(r),
            r.total,
            r.done,
            bytes(r.bytes),
          ])}
        />
      </Card>

      {/* ---------------------------------------------------------------- */}
      {/* Whether it worked                                                */}
      {/* ---------------------------------------------------------------- */}
      <Card>
        <CardTitle
          title="When it goes wrong"
          hint="Failure codes come from the friendly-error mapping, not raw yt-dlp text."
        />
        {downloads.errors.length === 0 ? (
          <NoData>
            {settled
              ? "No failures in this range."
              : "Nothing has run to an end in this range yet."}
          </NoData>
        ) : (
          <BarList
            unit="failures"
            rows={downloads.errors.map((e) => ({
              key: e.code,
              label: <code className="font-mono text-xs">{e.code}</code>,
              value: e.count,
              color: HUE.failure,
            }))}
          />
        )}
        <dl className="mt-4 grid grid-cols-3 gap-2">
          <StatTile label="Fastest" value={duration(timing.fastest_sec)} />
          <StatTile label="Median" value={duration(timing.median_sec)} />
          <StatTile label="Slowest" value={duration(timing.slowest_sec)} />
        </dl>
        <p className="mt-2 text-xs text-muted">
          Time from the moment the job was created to the moment the file was ready, over{" "}
          {timing.samples} finished download{timing.samples === 1 ? "" : "s"}.
        </p>
      </Card>

      {/* ---------------------------------------------------------------- */}
      {/* Who signed up                                                    */}
      {/* ---------------------------------------------------------------- */}
      <Card>
        <CardTitle
          title="Sign-ups per day"
          hint="Verified means we have seen them sign in with a confirmed address."
        />
        <div className="mb-3">
          <Legend series={SIGNUP_SERIES} />
        </div>
        {signups.totals.total === 0 ? (
          <NoData>
            No accounts were created in this range.
            {signups.totals.refused > 0 && (
              <>
                {" "}
                {signups.totals.refused} attempt{signups.totals.refused === 1 ? " was" : "s were"}{" "}
                refused by the email checks.
              </>
            )}
          </NoData>
        ) : (
          <ColumnChart
            points={signups.daily.map((d) => ({
              day: d.day,
              values: [d.verified, d.unverified],
              extra: [["Refused", String(d.refused)]],
            }))}
            series={SIGNUP_SERIES}
            unit="sign-ups"
          />
        )}
        <dl className="mt-4 grid grid-cols-3 gap-2">
          <StatTile
            label="Refused"
            value={compact(signups.totals.refused)}
            note="never became accounts"
            tone={signups.totals.refused ? "warn" : "ink"}
          />
          <StatTile label="Disposable" value={compact(signups.totals.disposable)} />
          <StatTile label="No MX" value={compact(signups.totals.no_mx)} />
        </dl>
        <ValuesTable
          columns={["Day", "Verified", "Not verified", "Refused"]}
          rows={signups.daily.map((d) => [longDay(d.day), d.verified, d.unverified, d.refused])}
        />
      </Card>

      {/* ---------------------------------------------------------------- */}
      {/* Where they drop out                                              */}
      {/* ---------------------------------------------------------------- */}
      <Card>
        <CardTitle
          title="Funnel"
          hint={`Everyone who signed up between ${funnels.cohort.start} and ${funnels.cohort.end}, followed forward.`}
        />
        {funnels.steps[0].count === 0 ? (
          <NoData>Nobody signed up in this range, so there is no cohort to follow.</NoData>
        ) : (
          <Funnel
            rows={funnels.steps.map((s) => ({
              key: s.key,
              label: s.label,
              count: s.count,
              conversion:
                s.of_previous === null
                  ? ""
                  : `${s.of_previous}% of ${s.key === "returned" ? "those eligible" : "the step before"}`,
              note: s.note,
            }))}
          />
        )}
      </Card>

      {/* ---------------------------------------------------------------- */}
      {/* Who they are                                                     */}
      {/* ---------------------------------------------------------------- */}
      <Card>
        <CardTitle
          title="Accounts"
          hint="Addresses are masked: the domain is what an operator judges, the rest is not needed."
        />
        <dl className="mb-4 grid grid-cols-3 gap-2">
          <StatTile label="Total" value={compact(accounts.totals.accounts)} />
          <StatTile label="Verified" value={compact(accounts.totals.verified)} />
          <StatTile
            label="Flagged"
            value={compact(accounts.totals.flagged)}
            tone={accounts.totals.flagged ? "warn" : "ink"}
          />
        </dl>

        <h3 className="mb-2 text-label uppercase text-muted">Top email domains</h3>
        {accounts.domains.length === 0 ? (
          <NoData>No accounts were created in this range.</NoData>
        ) : (
          <BarList
            unit="accounts"
            rows={accounts.domains.map((d) => ({
              key: d.domain,
              label: d.domain,
              value: d.accounts,
              color: d.flagged ? HUE.failure : HUE.video,
              note: d.flagged ? `${d.flagged} flagged` : `${d.verified} verified`,
            }))}
          />
        )}

        <h3 className="mb-2 mt-5 text-label uppercase text-muted">Flagged accounts</h3>
        {accounts.flagged.length === 0 ? (
          <NoData>No account has ever failed an email check.</NoData>
        ) : (
          <ul className="space-y-2">
            {accounts.flagged.map((a) => (
              <li
                key={a.id}
                className="rounded-control border border-line-soft bg-bg/60 px-3 py-2 text-sm"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate font-medium text-ink">{a.email}</span>
                  <span className="shrink-0 rounded-full bg-amber-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber">
                    {a.risk.replace("_", " ")}
                  </span>
                </div>
                <p className="mt-1 text-xs text-muted">
                  {a.verified ? "verified" : "not verified"} · {a.downloads} download
                  {a.downloads === 1 ? "" : "s"}
                  {a.created_at ? ` · joined ${a.created_at.slice(0, 10)}` : ""}
                </p>
                <code className="mt-1 block truncate font-mono text-[10px] text-muted">{a.id}</code>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {/* ---------------------------------------------------------------- */}
      {/* Data hygiene                                                     */}
      {/* ---------------------------------------------------------------- */}
      <Card>
        <CardTitle
          title="Data hygiene"
          hint={`Raw events are deleted after ${data.retention.keep_days} days by prune_old_events(), called nightly by a GitHub Action.`}
        />
        <dl className="grid grid-cols-3 gap-2">
          <StatTile label="Events stored" value={compact(data.retention.events)} />
          <StatTile
            label="Oldest"
            value={shortDate(data.retention.oldest_event)}
            note={data.retention.oldest_event?.slice(0, 10)}
          />
          <StatTile
            label="Past retention"
            value={compact(data.retention.overdue)}
            tone={data.retention.overdue ? "danger" : "ok"}
            note={data.retention.overdue ? "prune job is behind" : "prune job is current"}
          />
        </dl>
      </Card>
    </div>
  );
}
