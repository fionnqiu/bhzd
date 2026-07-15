import {
  forwardRef,
  type HTMLAttributes,
} from "react";

export type PanelTone = "dark" | "paper" | "quiet";

export interface PanelProps extends HTMLAttributes<HTMLElement> {
  tone?: PanelTone;
}

export const Panel = forwardRef<HTMLElement, PanelProps>(
  ({ className, tone = "quiet", ...props }, ref) => {
    const classes = ["panel", `panel--${tone}`, className ?? ""]
      .filter(Boolean)
      .join(" ");

    return <section ref={ref} className={classes} {...props} />;
  },
);

Panel.displayName = "Panel";
