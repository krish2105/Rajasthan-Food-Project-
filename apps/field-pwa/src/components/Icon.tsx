/**
 * Inline SVG icons.
 *
 * Hand-rolled rather than pulled from an icon package, for the same reason
 * there is no UI framework: a dozen icons is a few hundred bytes inline
 * against tens of kilobytes for a library, and this app is parsed on a slow CPU
 * before a worker can photograph anything.
 *
 * Never emojis. They render differently on every Android skin, cannot be
 * recoloured to follow the theme, and read as junk to a screen reader.
 *
 * Every icon is `aria-hidden`. Icons here always sit beside a text label
 * (Section 9.1: the user may not be confident with apps, and an icon-only
 * control is unguessable), so announcing them would only duplicate the label.
 */

interface IconProps {
  size?: number;
  className?: string;
}

const base = (size: number) => ({
  width: size,
  height: size,
  viewBox: "0 0 24 24",
  fill: "none" as const,
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
  focusable: false,
});

export const HomeIcon = ({ size = 24, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <path d="M3 10.5 12 3l9 7.5" />
    <path d="M5 9.5V20a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1V9.5" />
  </svg>
);

export const CameraIcon = ({ size = 24, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <path d="M3 8a2 2 0 0 1 2-2h2l1.5-2h7L17 6h2a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />
    <circle cx="12" cy="13" r="3.5" />
  </svg>
);

export const ScaleIcon = ({ size = 24, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <rect x="3" y="4" width="18" height="17" rx="2" />
    <path d="M8 10a4 4 0 0 1 8 0" />
    <path d="M12 10 10.5 7" />
  </svg>
);

export const SyncIcon = ({ size = 24, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <path d="M21 12a9 9 0 0 1-15.3 6.4L3 16" />
    <path d="M3 12a9 9 0 0 1 15.3-6.4L21 8" />
    <path d="M3 21v-5h5" />
    <path d="M21 3v5h-5" />
  </svg>
);

export const SettingsIcon = ({ size = 24, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 7 19.4a1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0-1.2-2.9H1a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 2.6 7a1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 2.9-1.2V1a2 2 0 1 1 4 0v.1A1.7 1.7 0 0 0 17 2.6a1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0 1.2 2.9H23a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1.6Z" />
  </svg>
);

export const CheckIcon = ({ size = 24, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <path d="m4 12.5 5 5L20 6.5" />
  </svg>
);

export const ClockIcon = ({ size = 24, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5.5l3.5 2" />
  </svg>
);

export const AlertIcon = ({ size = 24, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <path d="M12 3.5 22 20H2Z" />
    <path d="M12 10v4.5" />
    <circle cx="12" cy="17.4" r="0.6" fill="currentColor" />
  </svg>
);

export const OfflineIcon = ({ size = 24, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <path d="M2 2l20 20" />
    <path d="M5 12.5a10 10 0 0 1 4-2.4" />
    <path d="M15 10.1a10 10 0 0 1 4 2.4" />
    <path d="M8.5 16a5 5 0 0 1 7 0" />
    <circle cx="12" cy="19.5" r="0.6" fill="currentColor" />
  </svg>
);

export const TrashIcon = ({ size = 24, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <path d="M4 6h16" />
    <path d="M9 6V4h6v2" />
    <path d="M6 6l1 14h10l1-14" />
  </svg>
);

export const SunIcon = ({ size = 24, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </svg>
);
