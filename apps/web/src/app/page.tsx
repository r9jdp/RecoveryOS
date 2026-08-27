import Link from "next/link";

export default function HomePage() {
  return (
    <main
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: 24,
      }}
    >
      <section style={{ maxWidth: 720 }}>
        <p>RecoveryOS · Razorpay Test Mode</p>
        <h1>
          Recover failed subscription revenue with evidence, policy, and
          control.
        </h1>
        <p>
          The Phase 0 foundation is online. Explore the frozen component and
          token contract before the first recovery workflow is connected.
        </p>
        <Link href="/design-system">Open the design system</Link>
      </section>
    </main>
  );
}
