export function PulseIcon({ size = 22, color = "var(--c-primary)" }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        d="M3 12h3.5l2-5 3.5 10 2.5-6 1.5 3H21"
        style={{ stroke: color }}
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
