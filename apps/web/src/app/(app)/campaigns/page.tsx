import Link from "next/link";

import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { apiFetch } from "@/lib/api";
import { requireUser } from "@/lib/requireUser";
import { badgeClass, buttonVariants, cardClass, tableCell, tableHeadRow, tableRow, type BadgeVariant } from "@/lib/ui";
import type { Campaign } from "@/types/campaigns";

const STATUS_VARIANT: Record<string, BadgeVariant> = {
  DRAFT: "neutral",
  ACTIVE: "success",
  PAUSED: "warning",
  COMPLETED: "info",
  ARCHIVED: "neutral",
};

export default async function CampaignsPage() {
  await requireUser();

  const response = await apiFetch("/api/v1/campaigns");

  if (!response.ok) {
    return (
      <h1 className="text-lg font-semibold text-red-600">
        Falha ao carregar campanhas ({response.status})
      </h1>
    );
  }

  const campaigns: Campaign[] = await response.json();

  return (
    <div className="space-y-6">
      <PageHeader
        title="Campanhas"
        actions={
          <Link href="/campaigns/new" className={buttonVariants.primary}>
            Nova Campanha
          </Link>
        }
      />

      {campaigns.length === 0 ? (
        <EmptyState message="Nenhuma campanha ainda." />
      ) : (
        <div className={`${cardClass} overflow-x-auto p-0`}>
          <table className="w-full text-left text-sm">
            <thead>
              <tr className={tableHeadRow}>
                <th className={`${tableCell} pl-4`}>Nome</th>
                <th className={tableCell}>Segmento</th>
                <th className={tableCell}>Cidades</th>
                <th className={tableCell}>Alvo</th>
                <th className={`${tableCell} pr-4`}>Status</th>
              </tr>
            </thead>
            <tbody>
              {campaigns.map((campaign) => (
                <tr key={campaign.id} className={tableRow}>
                  <td className={`${tableCell} pl-4`}>
                    <Link
                      href={`/campaigns/${campaign.id}`}
                      className="font-medium text-gray-900 hover:text-blue-600 hover:underline"
                    >
                      {campaign.name}
                    </Link>
                  </td>
                  <td className={`${tableCell} text-gray-600`}>{campaign.segment}</td>
                  <td className={`${tableCell} text-gray-600`}>{campaign.cities.join(", ")}</td>
                  <td className={`${tableCell} text-gray-600`}>{campaign.target_quantity}</td>
                  <td className={`${tableCell} pr-4`}>
                    <span className={badgeClass(STATUS_VARIANT[campaign.status] ?? "neutral")}>
                      {campaign.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
