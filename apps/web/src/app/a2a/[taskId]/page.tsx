import { CustomerApproval } from "@/components/features/a2a";

export default async function CustomerApprovalPage({
  params,
}: {
  params: Promise<{ taskId: string }>;
}) {
  const { taskId } = await params;
  const customerAgentOrigin = process.env.CUSTOMER_AGENT_ORIGIN?.trim();
  if (!customerAgentOrigin) {
    throw new Error(
      "Customer authorization requires the server-side CUSTOMER_AGENT_ORIGIN setting.",
    );
  }
  return (
    <CustomerApproval
      taskId={taskId}
      customerAgentOrigin={customerAgentOrigin}
    />
  );
}
