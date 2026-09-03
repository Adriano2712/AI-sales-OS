import { notFound } from "next/navigation";

import { startRunAction, updateCampaignStatusAction } from "@/app/(app)/campaigns/actions";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { apiFetch } from "@/lib/api";
import { VALID_STATUS_TRANSITIONS } from "@/lib/campaignTransitions";
import { requireUser } from "@/lib/requireUser";
import { badgeClass, buttonVariants, cardClass, tableCell, tableHeadRow, tableRow } from "@/lib/ui";
import type { Campaign, CampaignRun } from "@/types/campaigns";

export default async function CampaignDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  await requireUser();
  const { id } = await params;

  const [campaignResponse, runsResponse] = await Promise.all([
    apiFetch(`/api/v1/campaigns/${id}`),
    apiFetch(`/api/v1/campaigns/${id}/runs`),
  ]);

  if (campaignResponse.status === 404) {
    notFound();
  }
  if (!campaignResponse.ok || !runsResponse.ok) {
    return <h1 className="text-lg font-semibold text-red-600">Falha ao carregar campanha</h1>;
  }

  const campaign: Campaign = await campaignResponse.json();
  const runs: CampaignRun[] = await runsResponse.json();
  const nextStatuses = VALID_STATUS_TRANSITIONS[campaign.status];

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <PageHeader
        title={campaign.name}
        actions={<span className={badgeClass("neutral")}>{campaign.status}</span>}
      />

      <div className={cardClass}>
        <dl className="grid grid-cols-2 gap-2 text-sm">
          <dt className="text-gray-500">Segmento</dt>
          <dd className="text-gray-900">{campaign.segment}</dd>
          <dt className="text-gray-500">Cidades</dt>
          <dd className="text-gray-900">{campaign.cities.join(", ")}</dd>
          <dt className="text-gray-500">Estado / País</dt>
          <dd className="text-gray-900">
            {campaign.state} / {campaign.country}
          </dd>
          <dt className="text-gray-500">Quantidade alvo</dt>
          <dd className="text-gray-900">{campaign.target_quantity}</dd>
        </dl>
      </div>

      <div className="flex flex-wrap gap-2">
        {nextStatuses.map((next) => (
          <form key={next} action={updateCampaignStatusAction.bind(null, campaign.id, next)}>
            <button type="submit" className={buttonVariants.secondary}>
              Mover para {next}
            </button>
          </form>
        ))}
        {campaign.status === "ACTIVE" && (
          <form action={startRunAction.bind(null, campaign.id)}>
            <button type="submit" className={buttonVariants.primary}>
              Iniciar Run
            </button>
          </form>
        )}
      </div>

      <div>
        <h2 className="text-sm font-semibold text-gray-900">Runs</h2>
        {runs.length === 0 ? (
          <EmptyState
            message={`Nenhum run ainda.${campaign.status !== "ACTIVE" ? " Ative a campanha para iniciar um." : ""}`}
          />
        ) : (
          <div className={`${cardClass} mt-2 overflow-x-auto p-0`}>
            <table className="w-full text-left text-sm">
              <thead>
                <tr className={tableHeadRow}>
                  <th className={`${tableCell} pl-4`}>Iniciado em</th>
                  <th className={tableCell}>Status</th>
                  <th className={tableCell}>Empresas</th>
                  <th className={`${tableCell} pr-4`}>Oportunidades</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id} className={tableRow}>
                    <td className={`${tableCell} pl-4 text-gray-600`}>
                      {run.started_at ? new Date(run.started_at).toLocaleString("pt-BR") : "—"}
                    </td>
                    <td className={`${tableCell} text-gray-600`}>{run.status}</td>
                    <td className={`${tableCell} text-gray-600`}>{run.companies_found}</td>
                    <td className={`${tableCell} pr-4 text-gray-600`}>{run.opportunities}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
