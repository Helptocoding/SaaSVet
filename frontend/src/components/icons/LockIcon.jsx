export function LockIcon({ size = 18 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <rect
        x="4.5"
        y="10.5"
        width="15"
        height="10"
        rx="2.2"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <path
        d="M8 10.5V8a4 4 0 018 0v2.5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}
