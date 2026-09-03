import Link from "next/link";

import { PhoneLink, WebsiteLink } from "@/components/ContactInfo";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { apiFetch } from "@/lib/api";
import { requireUser } from "@/lib/requireUser";
import { badgeClass, cardClass, tableCell, tableHeadRow, tableRow } from "@/lib/ui";
import type { Company } from "@/types/companies";

export default async function CompaniesPage() {
  await requireUser();

  const response = await apiFetch("/api/v1/companies");

  if (!response.ok) {
    return (
      <h1 className="text-lg font-semibold text-red-600">
        Falha ao carregar empresas ({response.status})
      </h1>
    );
  }

  const companies: Company[] = await response.json();

  return (
    <div className="space-y-6">
      <PageHeader
        title="Empresas"
        description="Descobertas automaticamente pelas campanhas — nenhuma cadastrada manualmente. Empresas marcadas como inativas (ex.: negócio fechado) não aparecem aqui. Os dados vêm do OpenStreetMap e podem estar desatualizados."
      />

      {companies.length === 0 ? (
        <EmptyState message="Nenhuma empresa ainda. Inicie um run em alguma campanha ativa." />
      ) : (
        <div className={`${cardClass} overflow-x-auto p-0`}>
          <table className="w-full text-left text-sm">
            <thead>
              <tr className={tableHeadRow}>
                <th className={`${tableCell} pl-4`}>Nome</th>
                <th className={tableCell}>Segmento</th>
                <th className={tableCell}>Cidade</th>
                <th className={tableCell}>Telefone</th>
                <th className={tableCell}>Site</th>
                <th className={`${tableCell} pr-4`}>Status</th>
              </tr>
            </thead>
            <tbody>
              {companies.map((company) => (
                <tr key={company.id} className={tableRow}>
                  <td className={`${tableCell} pl-4`}>
                    <Link
                      href={`/companies/${company.id}`}
                      className="font-medium text-gray-900 hover:text-blue-600 hover:underline"
                    >
                      {company.name}
                    </Link>
                    {company.needs_review && (
                      <span className={`${badgeClass("warning")} ml-2`}>revisar</span>
                    )}
                    {company.do_not_contact && (
                      <span className={`${badgeClass("danger")} ml-2`}>não contatar</span>
                    )}
                  </td>
                  <td className={`${tableCell} text-gray-600`}>{company.segment}</td>
                  <td className={`${tableCell} text-gray-600`}>{company.city}</td>
                  <td className={tableCell}>
                    <PhoneLink phone={company.phone} />
                  </td>
                  <td className={tableCell}>
                    <WebsiteLink website={company.website} />
                  </td>
                  <td className={`${tableCell} pr-4 text-gray-600`}>{company.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
