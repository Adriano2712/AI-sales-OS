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
import type { OpportunityClassification, OpportunityDetail } from "@/types/opportunities";

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
}

export default async function OpportunitiesPage({
  searchParams,
}: {
  searchParams: Promise<Filters>;
}) {
  await requireUser();
  const filters = await searchParams;

  const query = new URLSearchParams();
  if (filters.segment) query.set("segment", filters.segment);
  if (filters.city) query.set("city", filters.city);
  if (filters.status) query.set("status", filters.status);
  if (filters.type) query.set("type", filters.type);
  const qs = query.toString();

  const response = await apiFetch(`/api/v1/opportunities${qs ? `?${qs}` : ""}`);

  if (!response.ok) {
    return (
      <h1 className="text-lg font-semibold text-red-600">
        Falha ao carregar oportunidades ({response.status})
      </h1>
    );
  }

  const opportunities: OpportunityDetail[] = await response.json();

  return (
    <div className="space-y-6">
      <PageHeader
        title="Oportunidades"
        description="Geradas automaticamente a partir da Análise de Negócio de cada empresa — score e classificação calculados sem IA (regras determinísticas sobre dados já coletados)."
      />

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
        <EmptyState message="Nenhuma oportunidade encontrada. Elas são criadas automaticamente após a Análise de Negócio de cada empresa." />
      ) : (
        <div className={`${cardClass} overflow-x-auto p-0`}>
          <table className="w-full text-left text-sm">
            <thead>
              <tr className={tableHeadRow}>
                <th className={`${tableCell} pl-4`}>Empresa</th>
                <th className={tableCell}>Segmento</th>
                <th className={tableCell}>Cidade</th>
                <th className={tableCell}>Telefone</th>
                <th className={tableCell}>Site</th>
                <th className={tableCell}>Tipo</th>
                <th className={tableCell}>Score</th>
                <th className={tableCell}>Confiança</th>
                <th className={tableCell}>Classificação</th>
                <th className={`${tableCell} pr-4`}>Status</th>
              </tr>
            </thead>
            <tbody>
              {opportunities.map((opportunity) => (
                <tr key={opportunity.id} className={tableRow}>
                  <td className={`${tableCell} pl-4`}>
                    <Link
                      href={`/opportunities/${opportunity.id}`}
                      className="font-medium text-gray-900 hover:text-blue-600 hover:underline"
                    >
                      {opportunity.company_name}
                    </Link>
                  </td>
                  <td className={`${tableCell} text-gray-600`}>{opportunity.company_segment}</td>
                  <td className={`${tableCell} text-gray-600`}>{opportunity.company_city}</td>
                  <td className={tableCell}>
                    <PhoneLink phone={opportunity.company_phone} />
                  </td>
                  <td className={tableCell}>
                    <WebsiteLink website={opportunity.company_website} />
                  </td>
                  <td className={`${tableCell} text-gray-600`}>{opportunity.type}</td>
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
                  <td className={`${tableCell} pr-4 text-gray-600`}>{opportunity.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
