import { useEffect, type RefObject } from "react";

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "area[href]",
  "button:not([disabled])",
  'input:not([disabled]):not([type="hidden"])',
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[contenteditable="true"]',
  '[tabindex]:not([tabindex="-1"])',
].join(",");

function focusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (element) => element.tabIndex >= 0 && element.getAttribute("aria-hidden") !== "true",
  );
}

export function isTopmostFocusTrap(container: HTMLElement): boolean {
  const activeTraps = Array.from(
    document.querySelectorAll<HTMLElement>('[data-focus-trap="active"]'),
  );
  return activeTraps[activeTraps.length - 1] === container;
}

/**
 * Keeps keyboard navigation inside transient, aria-modal surfaces. Querying on
 * every Tab reflects controls that appear after async loading without storing
 * a stale list or introducing a dialog-specific dependency.
 */
export function useFocusTrap(containerRef: RefObject<HTMLElement | null>, enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Tab" || event.defaultPrevented) return;
      const container = containerRef.current;
      if (!container || !isTopmostFocusTrap(container)) return;

      const focusable = focusableElements(container);
      if (focusable.length === 0) {
        event.preventDefault();
        container.focus({ preventScroll: true });
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const activeElement = document.activeElement;
      const focusStartsInside = activeElement !== container && container.contains(activeElement);

      if (event.shiftKey) {
        if (!focusStartsInside || activeElement === first) {
          event.preventDefault();
          last.focus({ preventScroll: true });
        }
        return;
      }

      if (!focusStartsInside || activeElement === last) {
        event.preventDefault();
        first.focus({ preventScroll: true });
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [containerRef, enabled]);
}
