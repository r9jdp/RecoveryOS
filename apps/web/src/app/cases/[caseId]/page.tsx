import { CaseWorkspace } from "@/components/features/merchant";

export default async function CasePage({
  params,
}: {
  params: Promise<{ caseId: string }>;
}) {
  const { caseId } = await params;
  return <CaseWorkspace caseId={caseId} />;
}
