import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { apiFetch } from "@/lib/api";
import { requireUser } from "@/lib/requireUser";
import { cardClass } from "@/lib/ui";
import type { DashboardSummary } from "@/types/opportunities";

function MetricCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <div className={cardClass}>
      <div className="text-xs text-gray-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-gray-900">{value}</div>
      {hint && <div className="mt-1 text-xs text-gray-400">{hint}</div>}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-3">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">{title}</h2>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">{children}</div>
    </div>
  );
}

function formatPercent(value: number | null): string {
  return value === null ? "—" : `${value.toFixed(1)}%`;
}

function formatScore(value: number | null): string {
  return value === null ? "—" : value.toFixed(1);
}

function formatUsd(value: number | null): string {
  return value === null ? "—" : `$${value.toFixed(4)}`;
}

export default async function AnalyticsPage() {
  await requireUser();

  const response = await apiFetch("/api/v1/dashboard/summary");

  if (!response.ok) {
    return (
      <h1 className="text-lg font-semibold text-red-600">
        Falha ao carregar métricas ({response.status})
      </h1>
    );
  }

  const summary: DashboardSummary = await response.json();
  const hasAnyData = summary.discovery.companies_found > 0 || summary.cost.ai_calls > 0;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Analytics"
        description="Métricas agregadas de todo o tenant (spec seção 83) — Discovery, Enrichment, Analysis, Opportunity, Sales e Cost, sem filtros de campanha."
      />

      {!hasAnyData ? (
        <EmptyState message="Nenhum dado ainda. As métricas aparecem assim que uma campanha rodar." />
      ) : (
        <>
          <Section title="Discovery">
            <MetricCard label="Empresas encontradas" value={summary.discovery.companies_found} />
            <MetricCard label="Validadas" value={summary.discovery.companies_validated} />
            <MetricCard label="Duplicatas" value={summary.discovery.duplicates} />
            <MetricCard label="Inválidas" value={summary.discovery.invalid} />
          </Section>

          <Section title="Enrichment">
            <MetricCard label="Com site encontrado" value={summary.enrichment.website_found} />
            <MetricCard label="Sem site encontrado" value={summary.enrichment.website_not_found} />
            <MetricCard
              label="Taxa de sucesso"
              value={formatPercent(summary.enrichment.success_rate)}
              hint="% de empresas não-duplicadas com site encontrado"
            />
          </Section>

          <Section title="Analysis">
            <MetricCard label="Empresas analisadas" value={summary.analysis.companies_analyzed} />
            <MetricCard
              label="Score digital médio"
              value={formatScore(summary.analysis.average_digital_score)}
              hint="WEBSITE_QUALITY_SCORE"
            />
            <MetricCard
              label="Business fit médio"
              value={formatScore(summary.analysis.average_business_fit)}
            />
          </Section>

          <Section title="Opportunity">
            <MetricCard label="Criadas" value={summary.opportunities.total} />
            <MetricCard label="HIGH" value={summary.opportunities.high} />
            <MetricCard label="GOOD" value={summary.opportunities.good} />
            <MetricCard label="REVIEW" value={summary.opportunities.review} />
          </Section>

          <Section title="Sales">
            <MetricCard label="Aprovadas" value={summary.funnel.approved} />
            <MetricCard label="Contatadas" value={summary.funnel.contacted} />
            <MetricCard label="Responderam" value={summary.funnel.replied} />
            <MetricCard
              label="Reuniões"
              value={summary.funnel.meetings ?? "não rastreado"}
            />
            <MetricCard label="Propostas" value={summary.funnel.proposal_sent} />
            <MetricCard label="Ganhas" value={summary.funnel.won} />
            <MetricCard label="Perdidas" value={summary.funnel.lost} />
          </Section>

          <Section title="Cost">
            <MetricCard
              label="Custo total de IA"
              value={formatUsd(summary.cost.total_estimated_cost_usd)}
              hint={`${summary.cost.ai_calls} chamadas`}
            />
            <MetricCard label="Custo / empresa" value={formatUsd(summary.cost.cost_per_company)} />
            <MetricCard
              label="Custo / análise"
              value={formatUsd(summary.cost.cost_per_analysis)}
            />
            <MetricCard
              label="Custo / oportunidade"
              value={formatUsd(summary.cost.cost_per_opportunity)}
            />
          </Section>
        </>
      )}
    </div>
  );
}
