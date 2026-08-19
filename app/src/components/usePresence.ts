import { useEffect, useState } from "react";

export type MotionState = "open" | "closing";

// CSS surfaces use the same upper-bound duration so an exit never disappears
// before its visual transition has finished. Spring 曲线退出最长 200ms，留 40ms 余量。
export const MOTION_EXIT_MS = 240;

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

function systemPrefersReducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia(REDUCED_MOTION_QUERY).matches
    : false;
}

/** Keeps JavaScript lifecycle timing aligned with the system motion preference. */
export function useReducedMotion(): boolean {
  const [reducedMotion, setReducedMotion] = useState(systemPrefersReducedMotion);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mediaQuery = window.matchMedia(REDUCED_MOTION_QUERY);
    const syncPreference = () => setReducedMotion(mediaQuery.matches);

    syncPreference();
    mediaQuery.addEventListener("change", syncPreference);
    return () => mediaQuery.removeEventListener("change", syncPreference);
  }, []);

  return reducedMotion;
}

/**
 * Separates a surface's logical open state from its visual lifetime. This
 * prevents a React unmount from cutting off the matching CSS exit animation.
 */
export function usePresence(open: boolean, exitDurationMs = MOTION_EXIT_MS) {
  const reducedMotion = useReducedMotion();
  const [isPresent, setIsPresent] = useState(open);
  const [isClosing, setIsClosing] = useState(false);

  useEffect(() => {
    if (open) {
      setIsPresent(true);
      setIsClosing(false);
      return;
    }

    if (!isPresent) return;
    if (reducedMotion) {
      setIsPresent(false);
      setIsClosing(false);
      return;
    }

    setIsClosing(true);
    const timeoutId = window.setTimeout(() => {
      setIsPresent(false);
      setIsClosing(false);
    }, exitDurationMs);
    return () => window.clearTimeout(timeoutId);
  }, [exitDurationMs, isPresent, open, reducedMotion]);

  return {
    isPresent,
    motionState: (isClosing ? "closing" : "open") as MotionState,
  };
}
