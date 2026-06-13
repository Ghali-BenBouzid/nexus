// Nexus brand mark and wordmark lockup, per the logo handoff.
//
// The mark is a "network N" monogram: four corner nodes connected by the two
// stems and the diagonal (the diagonal doubles as a citation "link"). It is pure
// monochrome geometry that inherits `currentColor`, so one component serves every
// context (ink on light, off-white on dark, white on a colored tile).

type MarkProps = { size?: number; className?: string };

// Standalone monogram (icon weight: stroke 2.6 / node 3.4). Full 64x64 viewBox.
export function NexusMark({ size = 24, className }: MarkProps) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <g fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
        <path d="M18 48 V 16" />
        <path d="M18 16 L 46 48" />
        <path d="M46 48 V 16" />
      </g>
      <g fill="currentColor">
        <circle cx="18" cy="16" r="3.4" />
        <circle cx="18" cy="48" r="3.4" />
        <circle cx="46" cy="16" r="3.4" />
        <circle cx="46" cy="48" r="3.4" />
      </g>
    </svg>
  );
}

type LockupProps = { size?: number; className?: string };

// Primary lockup: the monogram IS the capital N, followed by "exus" in the
// wordmark face. The mark uses the heavier lockup weight (stroke 3.2 / node 3.6)
// and a tight-crop viewBox so it fills its box like a real letter. The seating
// constants (mark = 0.958em, vertical-align -0.022em, kern -0.02em, tracking
// -0.019em) are expressed in em so the lockup holds at any `size` (font-size px).
export function NexusLockup({ size = 20, className }: LockupProps) {
  return (
    <span className={"nexus-lockup" + (className ? " " + className : "")} style={{ fontSize: size }}>
      <svg className="nexus-lockup-n" viewBox="12 11 41 41" fill="none" aria-hidden="true" focusable="false">
        <g fill="none" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 48 V 16" />
          <path d="M18 16 L 46 48" />
          <path d="M46 48 V 16" />
        </g>
        <g fill="currentColor">
          <circle cx="18" cy="16" r="3.6" />
          <circle cx="18" cy="48" r="3.6" />
          <circle cx="46" cy="16" r="3.6" />
          <circle cx="46" cy="48" r="3.6" />
        </g>
      </svg>
      <span className="nexus-lockup-text">exus</span>
    </span>
  );
}
