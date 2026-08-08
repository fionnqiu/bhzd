import { useState } from "react";
import Button from "./Button";
import Modal from "./Modal";

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  /** 操作后果说明（中文；删除/归档等不可逆操作必须讲清后果） */
  description?: string;
  confirmText?: string;
  cancelText?: string;
  /** 危险操作（删除/归档/驳回）用红色确认键 */
  danger?: boolean;
  onConfirm: () => void | Promise<void>;
  onCancel: () => void;
}

/**
 * 二次确认对话框。
 * 注意：这是 UI 层的确认（防误点），与后端的确认门（pending_confirmations）
 * 是两回事——后者由业务页面用专门卡片实现，不要用本组件替代。
 */
export default function ConfirmDialog({
  open,
  title,
  description,
  confirmText = "确认",
  cancelText = "取消",
  danger = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const [busy, setBusy] = useState(false);

  const handleConfirm = async () => {
    setBusy(true);
    try {
      await onConfirm();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      title={title}
      onClose={onCancel}
      footer={
        <>
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            {cancelText}
          </Button>
          <Button
            variant={danger ? "danger" : "primary"}
            loading={busy}
            onClick={handleConfirm}
          >
            {confirmText}
          </Button>
        </>
      }
    >
      {description ? <p>{description}</p> : null}
    </Modal>
  );
}
