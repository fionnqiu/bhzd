import { Sparkles } from "lucide-react";
import "./agent-presentation.css";

interface AgentAvatarProps {
  streaming?: boolean;
  className?: string;
  label?: string;
  decorative?: boolean;
}

/**
 * Shared assistant identity keeps the teacher and student streams recognisable
 * as one product while each host page still controls its local layout.
 */
export function AgentAvatar({
  streaming = false,
  className,
  label = "标航智导",
  decorative = false,
}: AgentAvatarProps) {
  return (
    <span
      className={["agent-avatar", className].filter(Boolean).join(" ")}
      data-streaming={streaming || undefined}
      role={decorative ? undefined : "img"}
      aria-label={decorative ? undefined : label}
      aria-hidden={decorative || undefined}
    >
      <Sparkles className="agent-avatar-spark" size={15} strokeWidth={2.25} aria-hidden="true" />
    </span>
  );
}
