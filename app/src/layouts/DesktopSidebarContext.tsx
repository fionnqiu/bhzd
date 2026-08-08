import { createContext, useContext } from "react";

interface DesktopSidebarContextValue {
  /** True only while a desktop workbench rail is fully hidden. */
  showExpandControl: boolean;
  sidebarId: string;
  expandDesktopSidebar: () => void;
}

const defaultValue: DesktopSidebarContextValue = {
  showExpandControl: false,
  sidebarId: "shell-sidebar",
  expandDesktopSidebar: () => {},
};

/**
 * PageHeader consumes this narrow contract instead of knowing about ShellLayout.
 * That keeps the expand affordance in the real title row without coupling page
 * components to the shell's responsive state implementation.
 */
export const DesktopSidebarContext = createContext<DesktopSidebarContextValue>(defaultValue);

export function useDesktopSidebar(): DesktopSidebarContextValue {
  return useContext(DesktopSidebarContext);
}
