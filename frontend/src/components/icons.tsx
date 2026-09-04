/**
 * The app's icon set. Line icons on a 24 grid, 1.75 stroke, drawn in
 * currentColor so a tone class on the parent is all they need.
 */

type IconProps = {
  className?: string;
  /** Icons are decorative by default; the label next to them carries the meaning. */
  title?: string;
};

function Svg({ className = "h-5 w-5", title, children }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
      focusable="false"
    >
      {title && <title>{title}</title>}
      {children}
    </svg>
  );
}

export function DownloadIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M12 3v11" />
      <path d="M7 10.5 12 15l5-4.5" />
      <path d="M4.5 19.5h15" />
    </Svg>
  );
}

export function HistoryIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1" />
      <path d="M3.2 4.6v4h4" />
      <path d="M12 7.8V12l3 1.8" />
    </Svg>
  );
}

export function AccountIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <circle cx="12" cy="8.2" r="3.6" />
      <path d="M4.8 19.6a7.4 7.4 0 0 1 14.4 0" />
    </Svg>
  );
}

export function AudioIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M9 17.5V5.2l10-1.8v12.1" />
      <circle cx="6.6" cy="17.8" r="2.4" />
      <circle cx="16.6" cy="15.5" r="2.4" />
    </Svg>
  );
}

export function VideoIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <rect x="3" y="5.5" width="13" height="13" rx="3" />
      <path d="M16 10.5 21 8v8l-5-2.5z" />
    </Svg>
  );
}

export function LinkIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M10.5 13.5a4 4 0 0 0 5.7 0l2.6-2.6a4 4 0 0 0-5.7-5.7l-1.2 1.2" />
      <path d="M13.5 10.5a4 4 0 0 0-5.7 0l-2.6 2.6a4 4 0 1 0 5.7 5.7l1.2-1.2" />
    </Svg>
  );
}

export function CheckIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M4.5 12.5 9.5 17.5 19.5 6.5" />
    </Svg>
  );
}

export function AlertIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.6V13" />
      <path d="M12 16.3h.01" />
    </Svg>
  );
}

export function OfflineIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M2 2 22 22" />
      <path d="M2 8.8a15 15 0 0 1 4.2-2.6" />
      <path d="M22 8.8a15 15 0 0 0-11.3-3.7" />
      <path d="M5 12.9a10 10 0 0 1 5.2-2.7" />
      <path d="M19 12.9a10 10 0 0 0-2-1.5" />
      <path d="M8.5 16.4a5 5 0 0 1 7 0" />
      <path d="M12 20h.01" />
    </Svg>
  );
}

export function InstallIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <rect x="6.5" y="2.8" width="11" height="18.4" rx="2.6" />
      <path d="M12 8v6" />
      <path d="M9.6 11.6 12 14l2.4-2.4" />
    </Svg>
  );
}

export function CloseIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M6 6l12 12M18 6 6 18" />
    </Svg>
  );
}

export function InboxIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M3.5 13.5 6 5.2A2 2 0 0 1 7.9 3.8h8.2A2 2 0 0 1 18 5.2l2.5 8.3" />
      <path d="M3.5 13.5h4l1.2 2.4h6.6l1.2-2.4h4" />
      <path d="M3.5 13.5v3.9a2.6 2.6 0 0 0 2.6 2.6h11.8a2.6 2.6 0 0 0 2.6-2.6v-3.9" />
    </Svg>
  );
}

export function TrashIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M4.5 6.5h15" />
      <path d="M9.5 6.5V5a1.5 1.5 0 0 1 1.5-1.5h2A1.5 1.5 0 0 1 14.5 5v1.5" />
      <path d="M6.5 6.5 7.3 19a1.5 1.5 0 0 0 1.5 1.4h6.4a1.5 1.5 0 0 0 1.5-1.4l.8-12.5" />
      <path d="M10.5 10v6.5M13.5 10v6.5" />
    </Svg>
  );
}
