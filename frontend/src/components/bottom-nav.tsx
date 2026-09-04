"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { AccountIcon, DownloadIcon, HistoryIcon } from "@/components/icons";
import { useAuth } from "@/lib/auth";

/**
 * Everything that sticks to the bottom of the screen, in one fixed stack:
 * the page's action bar (optional) sits directly on top of the navigation,
 * so the two can never overlap. `Page`'s `dock` prop reserves the matching
 * amount of scroll room, and both bars clear the phone's home indicator.
 */
export function BottomDock({ action }: { action?: ReactNode }) {
  return (
    <div className="fixed inset-x-0 bottom-0 z-40">
      {action && (
        <div className="border-t border-line bg-surface shadow-dock backdrop-blur-lg supports-[backdrop-filter]:bg-dock">
          <div className="relative mx-auto flex h-[var(--action-h)] w-full max-w-md items-center gap-3 px-gutter sm:max-w-lg">
            {action}
          </div>
        </div>
      )}
      <BottomNav elevated={!action} />
    </div>
  );
}

const ACCOUNT_PATHS = ["/account", "/signin", "/signup", "/forgot", "/auth"];

function BottomNav({ elevated }: { elevated: boolean }) {
  const pathname = usePathname();
  const { user, me } = useAuth();

  const items = [
    { key: "download", href: "/", label: "Download", Icon: DownloadIcon, active: pathname === "/" },
    {
      key: "history",
      href: "/history",
      label: "History",
      Icon: HistoryIcon,
      active: pathname === "/history",
    },
    {
      key: "account",
      href: user ? "/account" : "/signin",
      label: "Account",
      Icon: AccountIcon,
      active: ACCOUNT_PATHS.some((p) => pathname.startsWith(p)),
    },
  ];

  const needsAttention = !!me && !me.email_verified;

  return (
    <nav
      aria-label="Primary"
      className={`border-t border-line bg-surface pb-safe backdrop-blur-lg supports-[backdrop-filter]:bg-dock ${
        elevated ? "shadow-dock" : ""
      }`}
    >
      <ul className="mx-auto flex h-[var(--nav-h)] w-full max-w-md sm:max-w-lg">
        {items.map(({ key, href, label, Icon, active }) => (
          <li key={key} className="flex-1">
            <Link
              href={href}
              aria-current={active ? "page" : undefined}
              className={`relative flex h-full flex-col items-center justify-center gap-0.5 transition-ui ${
                active ? "text-accent" : "text-muted hover:text-ink-2"
              }`}
            >
              <span
                aria-hidden
                className={`absolute inset-x-[22%] top-0 h-0.5 rounded-b-full transition-ui ${
                  active ? "bg-accent" : "bg-transparent"
                }`}
              />
              <span className="relative">
                <Icon className="h-[22px] w-[22px]" />
                {key === "account" && needsAttention && (
                  <span
                    aria-hidden
                    className="absolute -right-1 -top-0.5 h-2 w-2 rounded-full bg-amber ring-2 ring-surface"
                  />
                )}
              </span>
              <span className="text-[11px] font-medium leading-none">{label}</span>
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
