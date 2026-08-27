export default function CustomerApprovalRouteLoading() {
  return (
    <main
      aria-busy="true"
      aria-live="polite"
      style={{ minHeight: "100vh", display: "grid", placeItems: "center" }}
    >
      Loading secure authorization…
    </main>
  );
}
