import { notFound } from "next/navigation";

import { updateCompanyDoNotContactAction, updateCompanyStatusAction } from "@/app/(app)/companies/actions";
import { PhoneLink, WebsiteLink } from "@/components/ContactInfo";
import { PageHeader } from "@/components/PageHeader";
import { apiFetch } from "@/lib/api";
import { requireUser } from "@/lib/requireUser";
import { badgeClass, buttonVariants, cardClass, type BadgeVariant } from "@/lib/ui";
import type { CompanyDetail, EvidenceConfidence } from "@/types/companies";

const CONFIDENCE_VARIANT: Record<EvidenceConfidence, BadgeVariant> = {
  HIGH: "success",
  MEDIUM: "warning",
  LOW: "warning",
  UNKNOWN: "neutral",
};

export default async function CompanyDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  await requireUser();
  const { id } = await params;

  const response = await apiFetch(`/api/v1/companies/${id}`);

  if (response.status === 404) {
    notFound();
  }
  if (!response.ok) {
    return <h1 className="text-lg font-semibold text-red-600">Falha ao carregar empresa</h1>;
  }

  const company: CompanyDetail = await response.json();

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <PageHeader
        title={company.name}
        description={`${company.segment} · ${company.city}/${company.state}`}
        actions={
          <>
            {company.needs_review && (
              <span className={badgeClass("warning")}>revisar possível duplicata</span>
            )}
            {company.do_not_contact && <span className={badgeClass("danger")}>não contatar</span>}
          </>
        }
      />

      <div className={cardClass}>
        <dl className="grid grid-cols-2 gap-2 text-sm">
          <dt className="text-gray-500">Endereço</dt>
          <dd className="text-gray-900">{company.address ?? "—"}</dd>
          <dt className="text-gray-500">Telefone</dt>
          <dd className="text-gray-900">
            <PhoneLink phone={company.phone} />
          </dd>
          <dt className="text-gray-500">Website</dt>
          <dd className="text-gray-900">
            <WebsiteLink website={company.website} />
          </dd>
          <dt className="text-gray-500">Status</dt>
          <dd className="text-gray-900">{company.status}</dd>
        </dl>
      </div>

      {company.website && (
        <div>
          <h2 className="text-sm font-semibold text-gray-900">Análise do site</h2>
          {company.website_analysis ? (
            <div className={`${cardClass} mt-2`}>
              <div className="flex items-baseline gap-2">
                <span className="text-2xl font-semibold text-gray-900">
                  {company.website_analysis.digital_score ?? "—"}
                </span>
                <span className="text-sm text-gray-500">/ 100</span>
              </div>
              <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                {(
                  [
                    ["Funcionamento", company.website_analysis.score_funcionamento],
                    ["Mobile", company.website_analysis.score_mobile],
                    ["UX", company.website_analysis.score_ux],
                    ["Conversão", company.website_analysis.score_conversao],
                    ["Conteúdo", company.website_analysis.score_conteudo],
                    ["Design", company.website_analysis.score_design],
                  ] as const
                ).map(([label, value]) => (
                  <div key={label} className="flex justify-between">
                    <dt className="text-gray-500">{label}</dt>
                    <dd className="text-gray-900">{value ?? "desconhecido"}</dd>
                  </div>
                ))}
              </dl>
              <p className="mt-2 text-xs text-gray-400">
                Analisado em{" "}
                {new Date(company.website_analysis.analyzed_at).toLocaleString("pt-BR")}. Uma
                dimensão “desconhecido” significa que não foi possível avaliar com segurança, não
                que o site vai mal nela.
              </p>
            </div>
          ) : (
            <p className="mt-2 text-sm text-gray-500">
              Ainda não analisado (a análise roda automaticamente após a descoberta).
            </p>
          )}
        </div>
      )}

      <div>
        <h2 className="text-sm font-semibold text-gray-900">Análise de negócio</h2>
        {company.business_analysis ? (
          <div className={`${cardClass} mt-2`}>
            <div className="flex items-baseline gap-4">
              <div>
                <span className="text-2xl font-semibold text-gray-900">
                  {company.business_analysis.overall_score ?? "—"}
                </span>
                <span className="text-sm text-gray-500"> / 100</span>
              </div>
              <div className="text-sm text-gray-500">
                confiança: {company.business_analysis.confidence ?? "—"}
                {company.business_analysis.confidence !== null && "%"}
              </div>
            </div>
            <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
              {(
                [
                  ["Perfil (fit)", company.business_analysis.business_fit_score],
                  ["Atividade", company.business_analysis.activity_score],
                  ["Maturidade digital", company.business_analysis.digital_maturity_score],
                  ["Necessidade", company.business_analysis.need_score],
                  ["Compatibilidade", company.business_analysis.compatibility_score],
                ] as const
              ).map(([label, value]) => (
                <div key={label} className="flex justify-between">
                  <dt className="text-gray-500">{label}</dt>
                  <dd className="text-gray-900">{value ?? "desconhecido"}</dd>
                </div>
              ))}
            </dl>

            {company.business_analysis.problems.length > 0 && (
              <div className="mt-3">
                <h3 className="text-xs font-semibold text-gray-700">Problemas identificados</h3>
                <ul className="mt-1 list-disc space-y-1 pl-4 text-sm text-gray-800">
                  {company.business_analysis.problems.map((problem, i) => (
                    <li key={i}>{problem}</li>
                  ))}
                </ul>
              </div>
            )}

            {company.business_analysis.findings.length > 0 && (
              <div className="mt-3">
                <h3 className="text-xs font-semibold text-gray-700">Achados</h3>
                <ul className="mt-1 list-disc space-y-1 pl-4 text-sm text-gray-600">
                  {company.business_analysis.findings.map((finding, i) => (
                    <li key={i}>{finding}</li>
                  ))}
                </ul>
              </div>
            )}

            <p className="mt-3 text-xs text-gray-400">
              Analisado em{" "}
              {new Date(company.business_analysis.analyzed_at).toLocaleString("pt-BR")}.
              Perfil/Atividade/Maturidade/Necessidade são calculados sem IA (dados que já
              coletamos); Compatibilidade e os textos acima vêm da análise por IA.
            </p>
          </div>
        ) : (
          <p className="mt-2 text-sm text-gray-500">
            Ainda não analisado (roda automaticamente após discovery/enrichment).
          </p>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        {company.do_not_contact ? (
          <form action={updateCompanyDoNotContactAction.bind(null, company.id, false)}>
            <button type="submit" className={buttonVariants.secondary}>
              Permitir contato novamente
            </button>
          </form>
        ) : (
          <form action={updateCompanyDoNotContactAction.bind(null, company.id, true)}>
            <button type="submit" className={buttonVariants.secondary}>
              Marcar como não contatar
            </button>
          </form>
        )}

        {company.status === "INVALID" ? (
          <form action={updateCompanyStatusAction.bind(null, company.id, "DISCOVERED")}>
            <button type="submit" className={buttonVariants.secondary}>
              Desmarcar (reativar)
            </button>
          </form>
        ) : (
          <form action={updateCompanyStatusAction.bind(null, company.id, "INVALID")}>
            <button type="submit" className={buttonVariants.danger}>
              Marcar como inativa (negócio fechado)
            </button>
          </form>
        )}
      </div>

      <div>
        <h2 className="text-sm font-semibold text-gray-900">Evidências</h2>
        <p className="mt-1 text-xs text-gray-400">
          Toda informação relevante tem uma fonte rastreável — ausência de dado é marcada
          explicitamente, nunca inventada.
        </p>
        <ul className="mt-2 space-y-2">
          {company.evidence.map((item) => (
            <li key={item.id} className={`${cardClass} text-sm`}>
              <div className="flex items-center justify-between gap-2">
                <span className="text-gray-900">{item.claim}</span>
                <span className={`shrink-0 ${badgeClass(CONFIDENCE_VARIANT[item.confidence])}`}>
                  {item.confidence}
                </span>
              </div>
              <div className="mt-1 text-xs text-gray-400">
                fonte: {item.source} · coletado em{" "}
                {new Date(item.collected_at).toLocaleString("pt-BR")}
              </div>
            </li>
          ))}
        </ul>
      </div>

      <div>
        <h2 className="text-sm font-semibold text-gray-900">Fontes</h2>
        <ul className="mt-2 space-y-2">
          {company.sources.map((source) => (
            <li key={source.id} className={`${cardClass} text-sm`}>
              <span className="font-medium text-gray-900">{source.provider}</span>{" "}
              <span className="text-gray-500">({source.external_id})</span>
              <div className="text-xs text-gray-400">
                coletado em {new Date(source.collected_at).toLocaleString("pt-BR")}
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
