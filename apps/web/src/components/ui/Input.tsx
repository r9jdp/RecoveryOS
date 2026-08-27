import { forwardRef, useId } from "react";
import type { InputHTMLAttributes, SelectHTMLAttributes } from "react";

import styles from "../../styles/recovery-ui.module.css";
import { cx } from "./class-names";

interface FieldMeta {
  label: string;
  hint?: string;
  error?: string;
}

export interface InputProps
  extends InputHTMLAttributes<HTMLInputElement>, FieldMeta {}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, hint, error, id: suppliedId, className, required, ...props },
  ref,
) {
  const generatedId = useId();
  const id = suppliedId ?? generatedId;
  const descriptionId = error ? `${id}-error` : hint ? `${id}-hint` : undefined;

  return (
    <label className={styles.field} htmlFor={id}>
      <span className={styles.fieldLabel}>
        <span>{label}</span>
        {!required && <span className={styles.fieldHint}>Optional</span>}
      </span>
      <input
        ref={ref}
        id={id}
        required={required}
        className={cx(
          styles.input,
          Boolean(error) && styles.inputInvalid,
          className,
        )}
        aria-invalid={Boolean(error) || undefined}
        aria-describedby={descriptionId}
        {...props}
      />
      {error ? (
        <span id={descriptionId} className={styles.fieldError} role="alert">
          {error}
        </span>
      ) : hint ? (
        <span id={descriptionId} className={styles.fieldHint}>
          {hint}
        </span>
      ) : null}
    </label>
  );
});

export interface SelectProps
  extends SelectHTMLAttributes<HTMLSelectElement>, FieldMeta {}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  function Select(
    {
      label,
      hint,
      error,
      id: suppliedId,
      className,
      required,
      children,
      ...props
    },
    ref,
  ) {
    const generatedId = useId();
    const id = suppliedId ?? generatedId;
    const descriptionId = error
      ? `${id}-error`
      : hint
        ? `${id}-hint`
        : undefined;

    return (
      <label className={styles.field} htmlFor={id}>
        <span className={styles.fieldLabel}>
          <span>{label}</span>
          {!required && <span className={styles.fieldHint}>Optional</span>}
        </span>
        <select
          ref={ref}
          id={id}
          required={required}
          className={cx(
            styles.select,
            Boolean(error) && styles.inputInvalid,
            className,
          )}
          aria-invalid={Boolean(error) || undefined}
          aria-describedby={descriptionId}
          {...props}
        >
          {children}
        </select>
        {error ? (
          <span id={descriptionId} className={styles.fieldError} role="alert">
            {error}
          </span>
        ) : hint ? (
          <span id={descriptionId} className={styles.fieldHint}>
            {hint}
          </span>
        ) : null}
      </label>
    );
  },
);
