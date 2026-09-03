/** Shared style tokens — every page pulls badge/button/card classes from
 * here instead of redefining its own STATUS_STYLES dict, so the same status
 * always looks the same everywhere it appears. */

export type BadgeVariant = "success" | "info" | "warning" | "danger" | "neutral";

const BADGE_VARIANTS: Record<BadgeVariant, string> = {
  success: "bg-green-100 text-green-700",
  info: "bg-blue-100 text-blue-700",
  warning: "bg-yellow-100 text-yellow-800",
  danger: "bg-red-100 text-red-700",
  neutral: "bg-gray-100 text-gray-600",
};

export function badgeClass(variant: BadgeVariant): string {
  return `inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${BADGE_VARIANTS[variant]}`;
}

export const buttonBase =
  "inline-flex items-center justify-center rounded-md px-3 py-1.5 text-sm font-medium transition-colors disabled:opacity-50 disabled:pointer-events-none";

export const buttonVariants = {
  primary: `${buttonBase} bg-blue-600 text-white hover:bg-blue-700`,
  secondary: `${buttonBase} border border-gray-300 text-gray-700 hover:bg-gray-50`,
  danger: `${buttonBase} border border-red-300 text-red-700 hover:bg-red-50`,
  ghost: `${buttonBase} text-gray-600 hover:bg-gray-100`,
} as const;

export const cardClass = "rounded-lg border border-gray-200 bg-white p-4";

export const inputClass =
  "w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500";

export const tableHeadRow = "border-b border-gray-200 text-left text-xs font-medium uppercase tracking-wide text-gray-500";
export const tableRow = "border-b border-gray-100 last:border-0";
export const tableCell = "py-3 pr-4";
