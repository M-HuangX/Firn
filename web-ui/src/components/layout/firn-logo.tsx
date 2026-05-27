interface FirnLogoProps {
  size?: number;
  className?: string;
}

export function FirnLogo({ size = 28, className }: FirnLogoProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 28 28"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
    >
      {/* Top bar: ~35% width, accent at 40% opacity */}
      <rect x={9} y={5.5} width={10} height={3} rx={1.5} fill="#00D4AA" opacity={0.4} />
      {/* Middle bar: ~60% width, accent at 70% opacity */}
      <rect x={5.5} y={12.5} width={17} height={3} rx={1.5} fill="#00D4AA" opacity={0.7} />
      {/* Bottom bar: ~85% width, accent at 100% opacity */}
      <rect x={2} y={19.5} width={24} height={3} rx={1.5} fill="#00D4AA" opacity={1} />
    </svg>
  );
}
