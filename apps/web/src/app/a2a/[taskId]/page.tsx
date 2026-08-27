import { CustomerApproval } from "@/components/features/a2a";

export default async function CustomerApprovalPage({
  params,
}: {
  params: Promise<{ taskId: string }>;
}) {
  const { taskId } = await params;
  const customerAgentOrigin =
    process.env.CUSTOMER_AGENT_ORIGIN ?? "http://localhost:8010";
  return (
    <CustomerApproval
      taskId={taskId}
      customerAgentOrigin={customerAgentOrigin}
    />
  );
}
