"use client";
import * as Dialog from "@radix-ui/react-dialog";
import { AlertCircle, Check, Copy, X } from "lucide-react";
import { useState } from "react";
export function SectionTitle({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="section-title">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
      </div>
      {children && <div>{children}</div>}
    </div>
  );
}
export function Status({ status }: { status: string }) {
  const label = status.replaceAll("_", " ");
  return (
    <span className={`status-pill status-${status}`}>
      {status === "resolved" ? (
        <Check size={12} />
      ) : status === "rolled_back" ? (
        <AlertCircle size={12} />
      ) : (
        <span className="status-dot" />
      )}
      {label}
    </span>
  );
}
export function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      className="copy-button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        } catch {
          setDone(false);
        }
      }}
      aria-label="Copy commands"
    >
      {done ? <Check size={14} /> : <Copy size={14} />}{" "}
      {done ? "Copied" : "Copy"}
    </button>
  );
}
export function Confirm({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  onConfirm,
  destructive = false,
  busy = false,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  onConfirm: () => void;
  destructive?: boolean;
  busy?: boolean;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content">
          <Dialog.Close className="dialog-close" aria-label="Close">
            <X size={18} />
          </Dialog.Close>
          <div className={`dialog-icon ${destructive ? "dialog-danger" : ""}`}>
            <AlertCircle size={20} />
          </div>
          <Dialog.Title>{title}</Dialog.Title>
          <Dialog.Description>{description}</Dialog.Description>
          <div className="dialog-actions">
            <Dialog.Close className="button button-secondary">
              Go back
            </Dialog.Close>
            <button
              className={`button ${destructive ? "button-danger" : "button-primary"}`}
              onClick={onConfirm}
              disabled={busy}
            >
              {busy ? "Working…" : confirmLabel}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
export function ErrorBox({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div role="alert" className="error-box">
      <AlertCircle size={18} />
      <span>{message}</span>
      {onRetry && <button onClick={onRetry}>Retry</button>}
    </div>
  );
}
