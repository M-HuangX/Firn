import { cn } from "@/lib/utils";

type BadgeVariant = "running" | "complete" | "failed" | "unknown";

const variantStyles: Record<BadgeVariant, string> = {
  running: "bg-interactive/15 text-interactive border-interactive/30",
  complete: "bg-positive/15 text-positive border-positive/30",
  failed: "bg-negative/15 text-negative border-negative/30",
  unknown: "bg-text-secondary/15 text-text-secondary border-text-secondary/30",
};

const variantDots: Record<BadgeVariant, string> = {
  running: "bg-interactive animate-[pulse-dot_1.5s_ease-in-out_infinite]",
  complete: "bg-positive",
  failed: "bg-negative",
  unknown: "bg-text-secondary",
};

interface StatusBadgeProps {
  variant: string;
  label?: string;
  className?: string;
}

export function StatusBadge({ variant, label, className }: StatusBadgeProps) {
  const v = (variant in variantStyles ? variant : "unknown") as BadgeVariant;
  const displayLabel = label ?? v.charAt(0).toUpperCase() + v.slice(1);

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border",
        variantStyles[v],
        className
      )}
    >
      <span className={cn("w-1.5 h-1.5 rounded-full", variantDots[v])} />
      {displayLabel}
    </span>
  );
}
