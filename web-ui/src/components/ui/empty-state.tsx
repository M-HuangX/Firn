import { cn } from "@/lib/utils";

interface EmptyStateProps {
  icon?: string;
  title: string;
  description?: string;
  action?: {
    label: string;
    onClick: () => void;
  };
  className?: string;
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center py-12",
        className,
      )}
    >
      {icon && <span className="text-3xl opacity-30 mb-3">{icon}</span>}
      <p className="text-sm text-text-secondary font-medium">{title}</p>
      {description && (
        <p className="text-xs text-white/30 mt-1">{description}</p>
      )}
      {action && (
        <button
          onClick={action.onClick}
          className="mt-3 text-xs text-accent hover:underline cursor-pointer"
        >
          {action.label}
        </button>
      )}
    </div>
  );
}
