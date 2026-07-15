import {
  forwardRef,
  type ButtonHTMLAttributes,
} from "react";

export type ButtonVariant = "primary" | "quiet" | "danger" | "card";

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  fullWidth?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      variant = "primary",
      fullWidth = false,
      type = "button",
      ...props
    },
    ref,
  ) => {
    const classes = [
      "button",
      `button--${variant}`,
      fullWidth ? "button--full-width" : "",
      className ?? "",
    ]
      .filter(Boolean)
      .join(" ");

    return <button ref={ref} className={classes} type={type} {...props} />;
  },
);

Button.displayName = "Button";
