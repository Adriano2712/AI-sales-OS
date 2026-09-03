import Link from "next/link";

import { PhoneLink, WebsiteLink } from "@/components/ContactInfo";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { apiFetch } from "@/lib/api";
import { requireUser } from "@/lib/requireUser";
import {
  badgeClass,
  buttonVariants,
  cardClass,
  inputClass,
  tableCell,
  tableHeadRow,
  tableRow,
} from "@/lib/ui";
import type {
  DashboardSummary,
  OpportunityClassification,
  OpportunityDetail,
} from "@/types/opportunities";

const CLASSIFICATION_VARIANT: Record<OpportunityClassification, "success" | "info" | "warning" | "neutral"> = {
  HIGH: "success",
  GOOD: "info",
  REVIEW: "warning",
  LOW: "neutral",
};

interface Filters {
  segment?: string;
  city?: string;
  status?: string;
  type?: string;
  min_score?: string;
  min_confidence?: string;
}

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<Filters>;
}) {
  await requireUser();
  const filters = await searchParams;

  const [meResponse, summaryResponse] = await Promise.all([
    apiFetch("/api/v1/auth/me"),
    apiFetch("/api/v1/dashboard/summary"),
  ]);

  if (!meResponse.ok) {
    return (
      <div>
        <h1 className="text-lg font-semibold text-red-600">
          Falha ao carregar contexto do tenant ({meResponse.status})
        </h1>
        <p className="mt-2 text-sm text-gray-600">
          Verifique se o usuário possui um membership de tenant cadastrado (ver
          database/seeds).
        </p>
      </div>
    );
  }

  const query = new URLSearchParams();
  if (filters.segment) query.set("segment", filters.segment);
  if (filters.city) query.set("city", filters.city);
  if (filters.status) query.set("status", filters.status);
  if (filters.type) query.set("type", filters.type);
  if (filters.min_score) query.set("min_score", filters.min_score);
  if (filters.min_confidence) query.set("min_confidence", filters.min_confidence);
  const qs = query.toString();

  const opportunitiesResponse = await apiFetch(`/api/v1/opportunities${qs ? `?${qs}` : ""}`);

  const summary: DashboardSummary | null = summaryResponse.ok
    ? await summaryResponse.json()
    : null;
  const opportunities: OpportunityDetail[] = opportunitiesResponse.ok
    ? await opportunitiesResponse.json()
    : [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        description="“Com quem devo falar?” — oportunidades ordenadas por score, geradas automaticamente a partir da Análise de Negócio de cada empresa."
      />

      {summary && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div className={cardClass}>
            <div className="text-xs text-gray-500">Empresas descobertas</div>
            <div className="mt-1 text-2xl font-semibold text-gray-900">
              {summary.discovery.companies_found}
            </div>
            <div className="mt-1 text-xs text-gray-400">
              {summary.discovery.companies_validated} validadas · {summary.discovery.duplicates}{" "}
              duplicatas
            </div>
          </div>
          <div className={cardClass}>
            <div className="text-xs text-gray-500">Oportunidades</div>
            <div className="mt-1 text-2xl font-semibold text-gray-900">
              {summary.opportunities.total}
            </div>
            <div className="mt-1 text-xs text-gray-400">
              {summary.opportunities.high} HIGH · {summary.opportunities.good} GOOD ·{" "}
              {summary.opportunities.review} REVIEW · {summary.opportunities.low} LOW
            </div>
          </div>
          <div className={cardClass}>
            <div className="text-xs text-gray-500">Empresas analisadas</div>
            <div className="mt-1 text-2xl font-semibold text-gray-900">
              {summary.discovery.analyzed}
            </div>
            <div className="mt-1 text-xs text-gray-400">
              {summary.discovery.enriched} enriquecidas
            </div>
          </div>
          <div className={cardClass}>
            <div className="text-xs text-gray-500">Custo de IA (real)</div>
            <div className="mt-1 text-2xl font-semibold text-gray-900">
              ${summary.cost.total_estimated_cost_usd.toFixed(4)}
            </div>
            <div className="mt-1 text-xs text-gray-400">{summary.cost.ai_calls} chamadas</div>
          </div>
        </div>
      )}

      <div className={cardClass}>
        <form className="flex flex-wrap items-end gap-2" method="get">
          <input
            type="text"
            name="segment"
            placeholder="Segmento"
            defaultValue={filters.segment ?? ""}
            className={`${inputClass} w-32`}
          />
          <input
            type="text"
            name="city"
            placeholder="Cidade"
            defaultValue={filters.city ?? ""}
            className={`${inputClass} w-32`}
          />
          <input
            type="number"
            name="min_score"
            placeholder="Score mín."
            defaultValue={filters.min_score ?? ""}
            className={`${inputClass} w-28`}
          />
          <input
            type="number"
            name="min_confidence"
            placeholder="Confiança mín."
            defaultValue={filters.min_confidence ?? ""}
            className={`${inputClass} w-32`}
          />
          <select
            name="status"
            defaultValue={filters.status ?? ""}
            className={`${inputClass} w-auto`}
          >
            <option value="">Todos os status</option>
            <option value="OPEN">OPEN</option>
            <option value="REVIEWING">REVIEWING</option>
            <option value="APPROVED">APPROVED</option>
            <option value="REJECTED">REJECTED</option>
            <option value="ARCHIVED">ARCHIVED</option>
          </select>
          <select name="type" defaultValue={filters.type ?? ""} className={`${inputClass} w-auto`}>
            <option value="">Todos os tipos</option>
            <option value="WEBSITE">WEBSITE</option>
            <option value="E_COMMERCE">E_COMMERCE</option>
            <option value="AUTOMATION">AUTOMATION</option>
            <option value="INTERNAL_SYSTEM">INTERNAL_SYSTEM</option>
            <option value="INTEGRATION">INTEGRATION</option>
            <option value="DIGITAL_PRESENCE">DIGITAL_PRESENCE</option>
            <option value="OTHER">OTHER</option>
          </select>
          <button type="submit" className={buttonVariants.secondary}>
            Filtrar
          </button>
        </form>
      </div>

      {opportunities.length === 0 ? (
        <EmptyState message="Nenhuma oportunidade encontrada com esses filtros." />
      ) : (
        <div className={`${cardClass} overflow-x-auto p-0`}>
          <table className="w-full text-left text-sm">
            <thead>
              <tr className={tableHeadRow}>
                <th className={`${tableCell} pl-4`}>Empresa</th>
                <th className={tableCell}>Segmento / Cidade</th>
                <th className={tableCell}>Telefone</th>
                <th className={tableCell}>Site</th>
                <th className={tableCell}>Score</th>
                <th className={tableCell}>Confiança</th>
                <th className={tableCell}>Classificação</th>
                <th className={tableCell}>Solução potencial</th>
                <th className={`${tableCell} pr-4`}>Próxima ação</th>
              </tr>
            </thead>
            <tbody>
              {opportunities.map((opportunity) => (
                <tr key={opportunity.id} className={`${tableRow} align-top`}>
                  <td className={`${tableCell} pl-4`}>
                    <Link
                      href={`/opportunities/${opportunity.id}`}
                      className="font-medium text-gray-900 hover:text-blue-600 hover:underline"
                    >
                      {opportunity.company_name}
                    </Link>
                  </td>
                  <td className={`${tableCell} text-gray-600`}>
                    {opportunity.company_segment} · {opportunity.company_city}
                  </td>
                  <td className={tableCell}>
                    <PhoneLink phone={opportunity.company_phone} />
                  </td>
                  <td className={tableCell}>
                    <WebsiteLink website={opportunity.company_website} />
                  </td>
                  <td className={`${tableCell} text-gray-600`}>
                    {opportunity.opportunity_score ?? "—"}
                  </td>
                  <td className={`${tableCell} text-gray-600`}>
                    {opportunity.confidence !== null ? `${opportunity.confidence}%` : "—"}
                  </td>
                  <td className={tableCell}>
                    {opportunity.classification ? (
                      <span className={badgeClass(CLASSIFICATION_VARIANT[opportunity.classification])}>
                        {opportunity.classification}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className={`${tableCell} max-w-xs text-gray-600`}>
                    {opportunity.potential_solution ?? "—"}
                  </td>
                  <td className={`${tableCell} pr-4 text-gray-600`}>{opportunity.next_action}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
