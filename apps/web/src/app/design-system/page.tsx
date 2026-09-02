"use client";

import { useState } from "react";

import { AppShell, PageHeader } from "../../components/layout";
import type { NavigationGroup } from "../../components/layout";
import {
  Alert,
  Badge,
  BarChart,
  Button,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  ChartShell,
  Drawer,
  EmptyState,
  Icon,
  Input,
  MetricCard,
  Select,
  Skeleton,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
  TableViewport,
  TestModeBadge,
  Timeline,
} from "../../components/ui";
import styles from "../../styles/recovery-ui.module.css";

const navigation: NavigationGroup[] = [
  {
    label: "Recovery",
    items: [
      {
        label: "Control Tower",
        href: "#overview",
        icon: <Icon name="chart" />,
        active: true,
      },
      { label: "Cases", href: "#table", icon: <Icon name="case" /> },
      {
        label: "Audit trail",
        href: "#timeline",
        icon: <Icon name="activity" />,
      },
    ],
  },
  {
    label: "Workspace",
    items: [
      { label: "Recovery Lab", href: "#charts", icon: <Icon name="lab" /> },
      { label: "Policies", href: "#forms", icon: <Icon name="shield" /> },
      { label: "Settings", href: "#feedback", icon: <Icon name="settings" /> },
    ],
  },
];

const chartData = [
  { label: "Mon", value: 28 },
  { label: "Tue", value: 46 },
  { label: "Wed", value: 34 },
  { label: "Thu", value: 72 },
  { label: "Fri", value: 58 },
  { label: "Sat", value: 42 },
  { label: "Sun", value: 65 },
];

const timelineItems = [
  {
    id: "evt-1",
    title: "Payment failure verified",
    timestamp: "Today, 10:42 AM · payment.failed",
    description:
      "The signature is valid and the event is correlated to invoice inv_FIT_1024.",
    tone: "danger" as const,
    trailing: <Badge tone="danger">Failed</Badge>,
  },
  {
    id: "evt-2",
    title: "Recovery policy evaluated",
    timestamp: "Today, 10:43 AM · deterministic policy",
    description:
      "Gateway retries remain active. A standalone Payment Link was rejected as unsafe.",
    tone: "warning" as const,
    trailing: <Badge tone="warning">Approval</Badge>,
  },
  {
    id: "evt-3",
    title: "Card update surface prepared",
    timestamp: "Today, 10:44 AM · Razorpay test mode",
    description:
      "The customer can update the card for this subscription; no charge is initiated by RecoveryOS.",
    tone: "success" as const,
    trailing: <Badge tone="success">Ready</Badge>,
  },
];

const swatches = [
  ["Cobalt action", "#1748FF", "white"],
  ["Cobalt link", "#143FD9", "white"],
  ["Ledger ink", "#111318", "white"],
  ["Secondary ink", "#252A35", "white"],
  ["Muted text", "#596174", "white"],
  ["Warm paper", "#FAFAF7", "#111318"],
  ["Soft surface", "#F1F3F7", "#111318"],
  ["Ledger rule", "#D8DEEA", "#111318"],
  ["Verified", "#167052", "white"],
  ["Attention", "#8A5A00", "white"],
  ["Destructive", "#BD302D", "white"],
];

export default function DesignSystemPage() {
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <AppShell
      navigation={navigation}
      breadcrumb="RecoveryOS / Design system"
      topbarActions={<TestModeBadge />}
    >
      <PageHeader
        eyebrow="Phase 0 · Visual foundation"
        title="RecoveryOS design system"
        description="A ruled audit-ledger interface: warm paper, exact cobalt actions, editorial headings, technical metadata, and restrained motion."
        action={
          <Button onClick={() => setDrawerOpen(true)}>
            Open policy drawer
          </Button>
        }
      />

      <div className={styles.stack}>
        <section
          id="overview"
          className={styles.previewSection}
          aria-labelledby="overview-title"
        >
          <h2 id="overview-title">Control Tower foundations</h2>
          <div className={styles.grid4}>
            <MetricCard
              label="Revenue at risk"
              value="₹4,28,600"
              delta="18 active billing cycles"
            />
            <MetricCard
              label="Verified recovered"
              value="₹1,84,920"
              delta="↑ 12.4% this week"
              badge={<Badge tone="success">Verified</Badge>}
            />
            <MetricCard
              label="Recovery rate"
              value="43.1%"
              delta="+4.2 pts vs baseline"
            />
            <MetricCard
              label="Human review"
              value="7"
              delta="3 high-value cases"
              badge={<Badge tone="warning">Review</Badge>}
            />
          </div>
        </section>

        <section
          className={styles.previewSection}
          aria-labelledby="color-title"
        >
          <h2 id="color-title">Color tokens</h2>
          <div className={styles.swatches}>
            {swatches.map(([name, value, color]) => (
              <div
                key={name}
                className={styles.swatch}
                style={{ background: value, color }}
              >
                <span>{name}</span>
                <span>{value}</span>
              </div>
            ))}
          </div>
        </section>

        <section
          className={styles.previewSection}
          aria-labelledby="actions-title"
        >
          <h2 id="actions-title">Actions and evidence states</h2>
          <div className={styles.previewRow}>
            <Button>Approve recovery</Button>
            <Button variant="secondary">Escalate to human</Button>
            <Button variant="ghost">View evidence</Button>
            <Button variant="danger">Stop outreach</Button>
            <Button loading>Preparing surface</Button>
          </div>
          <div className={styles.previewRow}>
            <TestModeBadge />
            <Badge tone="neutral" showDot>
              Recovery evaluation
            </Badge>
            <Badge tone="info" showDot>
              Waiting
            </Badge>
            <Badge tone="success" showDot>
              Recovered
            </Badge>
            <Badge tone="warning" showDot>
              Review required
            </Badge>
            <Badge tone="danger" showDot>
              Policy blocked
            </Badge>
          </div>
        </section>

        <section
          id="forms"
          className={styles.previewSection}
          aria-labelledby="forms-title"
        >
          <h2 id="forms-title">Form controls</h2>
          <Card>
            <CardHeader
              title="Recovery policy"
              description="Controls are explicit about scope and customer impact."
            />
            <CardBody>
              <div className={styles.grid2}>
                <Input
                  label="Approval threshold"
                  type="number"
                  defaultValue="10000"
                  hint="Amounts above ₹10,000 require a human decision."
                  required
                />
                <Select
                  label="Preferred recovery action"
                  defaultValue="card-update"
                  required
                >
                  <option value="card-update">Subscription card update</option>
                  <option value="invoice-link">
                    Subscription invoice link
                  </option>
                  <option value="wait">Wait for gateway retry</option>
                </Select>
              </div>
            </CardBody>
            <CardFooter>
              <div className={styles.previewRow}>
                <Button size="sm">Save policy</Button>
                <Button size="sm" variant="secondary">
                  Reset
                </Button>
              </div>
            </CardFooter>
          </Card>
        </section>

        <section
          id="charts"
          className={styles.previewSection}
          aria-labelledby="charts-title"
        >
          <h2 id="charts-title">Chart shell</h2>
          <Card>
            <CardBody>
              <ChartShell
                title="Verified recovery by day"
                subtitle="Authoritative payment events only · ₹ thousands"
                action={<Badge tone="info">7 days</Badge>}
              >
                <BarChart
                  data={chartData}
                  valueLabel={(value) => `₹${value}k`}
                />
              </ChartShell>
            </CardBody>
          </Card>
        </section>

        <section
          id="table"
          className={styles.previewSection}
          aria-labelledby="table-title"
        >
          <h2 id="table-title">Case table</h2>
          <TableViewport>
            <Table>
              <TableCaption>
                Active recovery cases. Scroll horizontally on small screens.
              </TableCaption>
              <TableHead>
                <TableRow>
                  <TableHeaderCell>Case</TableHeaderCell>
                  <TableHeaderCell>Customer</TableHeaderCell>
                  <TableHeaderCell>Diagnosis</TableHeaderCell>
                  <TableHeaderCell>Amount</TableHeaderCell>
                  <TableHeaderCell>Status</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                <TableRow>
                  <TableCell>
                    <strong>REC-1024</strong>
                  </TableCell>
                  <TableCell>Ananya Sharma</TableCell>
                  <TableCell>Insufficient funds</TableCell>
                  <TableCell>₹1,499</TableCell>
                  <TableCell>
                    <Badge tone="warning">Awaiting approval</Badge>
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>
                    <strong>REC-1023</strong>
                  </TableCell>
                  <TableCell>Vikram Rao</TableCell>
                  <TableCell>Card expired</TableCell>
                  <TableCell>₹2,999</TableCell>
                  <TableCell>
                    <Badge tone="info">Card update sent</Badge>
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>
                    <strong>REC-1022</strong>
                  </TableCell>
                  <TableCell>Mira Patel</TableCell>
                  <TableCell>Unknown</TableCell>
                  <TableCell>₹899</TableCell>
                  <TableCell>
                    <Badge tone="success">Recovered</Badge>
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </TableViewport>
        </section>

        <section
          id="timeline"
          className={styles.previewSection}
          aria-labelledby="timeline-title"
        >
          <h2 id="timeline-title">Case timeline</h2>
          <Card>
            <CardHeader
              title="REC-1024 · FitBox Annual"
              description="Every policy decision and provider event remains inspectable."
            />
            <CardBody>
              <Timeline items={timelineItems} />
            </CardBody>
          </Card>
        </section>

        <section
          id="feedback"
          className={styles.previewSection}
          aria-labelledby="feedback-title"
        >
          <h2 id="feedback-title">Feedback, loading, and empty states</h2>
          <div className={styles.grid2}>
            <div className={styles.stack}>
              <Alert tone="info" title="Gateway retry is active">
                RecoveryOS will not create a standalone Payment Link.
              </Alert>
              <Alert tone="success" title="Payment verified">
                Revenue was attributed once from payment.captured.
              </Alert>
              <Alert tone="warning" title="Human approval required">
                This action exceeds the ₹10,000 threshold.
              </Alert>
              <Alert tone="danger" title="Outreach blocked">
                The customer opted out of automated contact.
              </Alert>
            </div>
            <EmptyState
              title="No cases need review"
              description="New policy-blocked or high-value recoveries will appear here."
              action={
                <Button variant="secondary" size="sm">
                  View all cases
                </Button>
              }
            />
          </div>
          <Card>
            <CardBody>
              <div
                className={styles.stack}
                aria-label="Loading case details"
                aria-busy="true"
              >
                <Skeleton width="38%" height="1.5rem" />
                <Skeleton height="0.875rem" />
                <Skeleton width="72%" height="0.875rem" />
              </div>
            </CardBody>
          </Card>
        </section>
      </div>

      <Drawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title="Recovery policy"
        description="Preview of the focus-trapped settings drawer. Escape and backdrop click close it."
        footer={
          <>
            <Button variant="secondary" onClick={() => setDrawerOpen(false)}>
              Cancel
            </Button>
            <Button onClick={() => setDrawerOpen(false)}>Save policy</Button>
          </>
        }
      >
        <div className={styles.stack}>
          <Alert tone="info" title="Safe by default">
            Native subscription recovery surfaces are preferred over standalone
            links.
          </Alert>
          <Input
            label="Daily contact limit"
            type="number"
            defaultValue="2"
            required
          />
          <Select label="Quiet hours" defaultValue="22-08" required>
            <option value="22-08">10:00 PM – 8:00 AM IST</option>
            <option value="21-09">9:00 PM – 9:00 AM IST</option>
          </Select>
        </div>
      </Drawer>
    </AppShell>
  );
}
