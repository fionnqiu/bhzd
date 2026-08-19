/**
 * 共享组件库统一出口。
 *
 * 页面一律从 "../components" 导入（而非逐个文件深路径），后续组件内部
 * 拆分/改名时不影响页面代码。
 */

export { default as Button } from "./Button";
export { default as IconButton } from "./IconButton";
export { default as Input } from "./Input";
export { default as Textarea } from "./Textarea";
export { default as Select } from "./Select";
export { default as Field } from "./Field";
export { default as Card } from "./Card";
export { default as PageHeader } from "./PageHeader";
export { default as DataTable } from "./DataTable";
export { default as StatusBadge } from "./StatusBadge";
export { default as Modal } from "./Modal";
export { default as ConfirmDialog } from "./ConfirmDialog";
export { default as Drawer } from "./Drawer";
export { default as Tabs } from "./Tabs";
export { default as EmptyState } from "./EmptyState";
export { default as Spinner } from "./Spinner";
export { default as ProgressBar } from "./ProgressBar";
export { ToastProvider, useToast } from "./Toast";
export { default as CitationCard } from "./CitationCard";
export {
  default as MasteryBadge,
  masteryStatusOf,
  MASTERED_THRESHOLD,
  WEAK_THRESHOLD,
} from "./MasteryBadge";
export { default as ErrorState } from "./ErrorState";
export { default as Tag } from "./Tag";
export { default as SearchInput } from "./SearchInput";
export { default as Pagination } from "./Pagination";
export { AgentAvatar } from "./agent/AgentPresentation";

export type { Column } from "./DataTable";
export type { SelectOption } from "./Select";
export type { ToastKind } from "./Toast";
