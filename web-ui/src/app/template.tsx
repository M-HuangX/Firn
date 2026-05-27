'use client';

import { m } from 'motion/react';

const GLACIAL_EASE = [0.22, 1, 0.36, 1] as const;

export default function Template({ children }: { children: React.ReactNode }) {
  return (
    <m.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.15, ease: GLACIAL_EASE }}
    >
      {children}
    </m.div>
  );
}
