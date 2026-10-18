import { IncidentDetail } from "@/components/incident-detail";
export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <IncidentDetail id={id} />;
}
