"use client";

import { AnimatePresence, m } from "motion/react";

type EmergencePreset =
  | "slide-down"
  | "slide-up"
  | "slide-left"
  | "slide-right"
  | "scale-up"
  | "fade-blur";

interface EmergenceContainerProps {
  visible: boolean;
  preset?: EmergencePreset;
  duration?: number;
  delay?: number;
  className?: string;
  children: React.ReactNode;
}

function getPresetVariants(preset: EmergencePreset, duration: number) {
  switch (preset) {
    case "slide-down":
      return {
        initial: { y: -20, opacity: 0 },
        animate: {
          y: 0,
          opacity: 1,
          transition: { type: "spring" as const, stiffness: 400, damping: 30, duration },
        },
        exit: {
          y: -20,
          opacity: 0,
          transition: { duration: duration * 0.8 },
        },
      };
    case "slide-up":
      return {
        initial: { y: 20, opacity: 0 },
        animate: {
          y: 0,
          opacity: 1,
          transition: { type: "spring" as const, stiffness: 400, damping: 30, duration },
        },
        exit: {
          y: 20,
          opacity: 0,
          transition: { duration: duration * 0.8 },
        },
      };
    case "slide-left":
      return {
        initial: { x: 20, opacity: 0 },
        animate: {
          x: 0,
          opacity: 1,
          transition: { type: "spring" as const, stiffness: 400, damping: 30, duration },
        },
        exit: {
          x: 20,
          opacity: 0,
          transition: { duration: duration * 0.8 },
        },
      };
    case "slide-right":
      return {
        initial: { x: -20, opacity: 0 },
        animate: {
          x: 0,
          opacity: 1,
          transition: { type: "spring" as const, stiffness: 400, damping: 30, duration },
        },
        exit: {
          x: -20,
          opacity: 0,
          transition: { duration: duration * 0.8 },
        },
      };
    case "scale-up":
      return {
        initial: { scale: 0.85, opacity: 0 },
        animate: {
          scale: 1,
          opacity: 1,
          transition: { type: "spring" as const, stiffness: 300, damping: 25 },
        },
        exit: {
          scale: 0.85,
          opacity: 0,
          transition: { duration: duration * 0.8 },
        },
      };
    case "fade-blur":
      return {
        initial: { opacity: 0, filter: "blur(4px)" },
        animate: {
          opacity: 1,
          filter: "blur(0px)",
          transition: { duration, ease: "easeOut" as const },
        },
        exit: {
          opacity: 0,
          filter: "blur(4px)",
          transition: { duration: duration * 0.8, ease: "easeIn" as const },
        },
      };
  }
}

export function EmergenceContainer({
  visible,
  preset = "fade-blur",
  duration = 0.3,
  delay = 0,
  className,
  children,
}: EmergenceContainerProps) {
  const variants = getPresetVariants(preset, duration);

  return (
    <AnimatePresence mode="wait">
      {visible && (
        <m.div
          initial={variants.initial}
          animate={{
            ...variants.animate,
            transition: {
              ...variants.animate.transition,
              delay,
            },
          }}
          exit={variants.exit}
          className={className}
        >
          {children}
        </m.div>
      )}
    </AnimatePresence>
  );
}
