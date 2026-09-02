import styles from "@/components/features/a2a/a2a.module.css";

export default function CustomerApprovalRouteLoading() {
  return (
    <main className={styles.routeLoading} aria-busy="true" aria-live="polite">
      Loading secure authorization / verifying scope…
    </main>
  );
}
