import { cn } from "@/lib/utils";

type SkeletonVariant = "text" | "card" | "chart";

const variantStyles: Record<SkeletonVariant, string> = {
  text: "h-4 w-full rounded",
  card: "h-32 w-full rounded-xl",
  chart: "h-48 w-full rounded-xl",
};

interface SkeletonProps {
  variant?: SkeletonVariant;
  className?: string;
}

export function Skeleton({ variant = "text", className }: SkeletonProps) {
  return (
    <div
      className={cn(
        "bg-surface animate-[shimmer_2s_linear_infinite] bg-[length:200%_100%]",
        "bg-gradient-to-r from-surface via-border/30 to-surface",
        variantStyles[variant],
        className
      )}
    />
  );
}
