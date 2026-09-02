"use client";

import { Check, TriangleAlert } from "lucide-react";
import { useRef } from "react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogMedia,
  AlertDialogTitle,
} from "@/components/shadcn/alert-dialog";
import { Spinner } from "@/components/shadcn/spinner";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  confirmationText?: string;
  onCancel: () => void;
  onConfirm: () => void;
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  danger = false,
  busy = false,
  confirmationText,
  onCancel,
  onConfirm,
}: ConfirmDialogProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const actionRef = useRef<HTMLButtonElement>(null);

  return (
    <AlertDialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen && !busy) onCancel();
      }}
    >
      <AlertDialogContent
        initialFocus={danger ? cancelRef : actionRef}
        className="max-w-md"
      >
        <AlertDialogHeader>
          <AlertDialogMedia
            className={danger ? "text-destructive" : "text-success"}
          >
            {danger ? <TriangleAlert /> : <Check />}
          </AlertDialogMedia>
          <AlertDialogTitle className="font-heading text-2xl font-normal">
            {title}
          </AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>

        {confirmationText ? (
          <p className="border border-l-2 border-l-primary bg-muted/20 px-3 py-2 font-mono text-xs leading-5 text-muted-foreground">
            {confirmationText}
          </p>
        ) : null}

        <AlertDialogFooter>
          <AlertDialogCancel ref={cancelRef} disabled={busy}>
            Cancel
          </AlertDialogCancel>
          <AlertDialogAction
            ref={actionRef}
            variant={danger ? "destructive" : "default"}
            disabled={busy}
            aria-busy={busy}
            onClick={onConfirm}
          >
            {busy ? <Spinner data-icon="inline-start" /> : null}
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
