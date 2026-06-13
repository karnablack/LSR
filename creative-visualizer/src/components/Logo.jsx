/**
 * LSR emblem — an infrastructure "cell" (hexagon) crossed by a synaptic response
 * pulse. Pure inline SVG so it stays crisp at any size and ships no binary asset.
 * The `status` prop tints the pulse: green when healthy, red during an incident.
 */
function Logo({ size = 40, status = 'healthy' }) {
  const pulseColor = status === 'incident' ? '#ff4a4a' : '#10b981';
  const gid = `lsr-${status}`;

  return (
    <svg
      className="lsr-logo"
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role="img"
      aria-label="LSR emblem"
    >
      <defs>
        <linearGradient id={`${gid}-shell`} x1="8" y1="11" x2="56" y2="53" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#38bdf8" />
          <stop offset="1" stopColor="#6366f1" />
        </linearGradient>
        <radialGradient id={`${gid}-core`} cx="32" cy="32" r="22" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#6366f1" stopOpacity="0.35" />
          <stop offset="1" stopColor="#0a0c10" stopOpacity="0" />
        </radialGradient>
      </defs>
      <path
        d="M20 11.2 L44 11.2 L56 32 L44 52.8 L20 52.8 L8 32 Z"
        fill={`url(#${gid}-core)`}
        stroke={`url(#${gid}-shell)`}
        strokeWidth="2.6"
        strokeLinejoin="round"
      />
      <path
        d="M11 32 L23 32 L27 20 L33 44 L37 32 L53 32"
        fill="none"
        stroke={pulseColor}
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="32" cy="32" r="3.4" fill={pulseColor} />
    </svg>
  );
}

export default Logo;
