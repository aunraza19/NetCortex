import { IncidentList } from "@/components/incident-list";
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ site?: string }>;
}) {
  const { site } = await searchParams;
  return <IncidentList initialSite={site} />;
}
