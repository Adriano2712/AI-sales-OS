import { notFound } from "next/navigation";

import {
  generateMessageAction,
  updateMessageAction,
  updateOpportunityStatusAction,
} from "@/app/(app)/opportunities/actions";
import { PhoneLink, WebsiteLink } from "@/components/ContactInfo";
import { PageHeader } from "@/components/PageHeader";
import { apiFetch } from "@/lib/api";
import { requireUser } from "@/lib/requireUser";
import { badgeClass, buttonVariants, cardClass, inputClass, type BadgeVariant } from "@/lib/ui";
import type { Message, MessageChannel } from "@/types/messages";
import type { OpportunityClassification, OpportunityDetail, OpportunityStatus } from "@/types/opportunities";

const STATUS_OPTIONS: OpportunityStatus[] = [
  "OPEN",
  "REVIEWING",
  "APPROVED",
  "REJECTED",
  "ARCHIVED",
];

const CHANNEL_OPTIONS: MessageChannel[] = ["WHATSAPP", "EMAIL", "LINKEDIN", "PHONE", "OTHER"];

const CLASSIFICATION_VARIANT: Record<OpportunityClassification, BadgeVariant> = {
  HIGH: "success",
  GOOD: "info",
  REVIEW: "warning",
  LOW: "neutral",
};

const MESSAGE_STATUS_VARIANT: Record<Message["status"], BadgeVariant> = {
  DRAFT: "neutral",
  APPROVED: "info",
  REJECTED: "danger",
  SENT: "success",
};

export default async function OpportunityDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  await requireUser();
  const { id } = await params;

  const response = await apiFetch(`/api/v1/opportunities/${id}`);

  if (response.status === 404) {
    notFound();
  }
  if (!response.ok) {
    return <h1 className="text-lg font-semibold text-red-600">Falha ao carregar oportunidade</h1>;
  }

  const opportunity: OpportunityDetail = await response.json();

  const messagesResponse = await apiFetch(`/api/v1/opportunities/${id}/messages`);
  const messages: Message[] = messagesResponse.ok ? await messagesResponse.json() : [];

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <PageHeader
        title={opportunity.company_name}
        description={`${opportunity.company_segment} · ${opportunity.company_city}/${opportunity.company_state}`}
        actions={<span className={badgeClass("neutral")}>{opportunity.type}</span>}
      />

      <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
        <div>
          <span className="text-gray-500">Telefone: </span>
          <PhoneLink phone={opportunity.company_phone} />
        </div>
        <div>
          <span className="text-gray-500">Site: </span>
          <WebsiteLink website={opportunity.company_website} />
        </div>
      </div>

      <div className={cardClass}>
        <div className="flex flex-wrap items-baseline gap-4">
          <div>
            <span className="text-2xl font-semibold text-gray-900">
              {opportunity.opportunity_score ?? "—"}
            </span>
            <span className="text-sm text-gray-500"> / 100</span>
          </div>
          <div className="text-sm text-gray-500">
            confiança: {opportunity.confidence ?? "—"}
            {opportunity.confidence !== null && "%"}
          </div>
          {opportunity.classification && (
            <span className={badgeClass(CLASSIFICATION_VARIANT[opportunity.classification])}>
              {opportunity.classification}
            </span>
          )}
        </div>
        <p className="mt-2 text-xs text-gray-400">
          Score e confiança são conceitos separados (score alto + confiança baixa significa
          oportunidade potencialmente boa, mas com evidência limitada).
        </p>

        <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-1 border-t border-gray-100 pt-4 text-sm">
          <dt className="text-gray-500">Digital Gap</dt>
          <dd className="text-gray-900">{opportunity.digital_gap ?? "desconhecido"}</dd>
          <dt className="text-gray-500">Business Fit</dt>
          <dd className="text-gray-900">{opportunity.business_fit ?? "desconhecido"}</dd>
          <dt className="text-gray-500">Necessidade</dt>
          <dd className="text-gray-900">{opportunity.need ?? "desconhecido"}</dd>
          <dt className="text-gray-500">Sinais comerciais</dt>
          <dd className="text-gray-900">{opportunity.commercial_signals ?? "desconhecido"}</dd>
        </dl>
      </div>

      {(opportunity.problem || opportunity.potential_solution || opportunity.reasons.length > 0) && (
        <div className={`${cardClass} space-y-4`}>
          {opportunity.problem && (
            <div>
              <h2 className="text-sm font-semibold text-gray-900">Problema</h2>
              <p className="mt-1 text-sm text-gray-700">{opportunity.problem}</p>
            </div>
          )}

          {opportunity.potential_solution && (
            <div>
              <h2 className="text-sm font-semibold text-gray-900">Solução potencial</h2>
              <p className="mt-1 text-sm text-gray-700">{opportunity.potential_solution}</p>
            </div>
          )}

          {opportunity.reasons.length > 0 && (
            <div>
              <h2 className="text-sm font-semibold text-gray-900">Motivos</h2>
              <ul className="mt-1 list-disc space-y-1 pl-4 text-sm text-gray-700">
                {opportunity.reasons.map((reason, i) => (
                  <li key={i}>{reason}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      <div>
        <h2 className="text-sm font-semibold text-gray-900">Status</h2>
        <form
          action={async (formData: FormData) => {
            "use server";
            const status = formData.get("status") as OpportunityStatus;
            await updateOpportunityStatusAction(opportunity.id, status);
          }}
          className="mt-2 flex items-center gap-2"
        >
          <select
            name="status"
            defaultValue={opportunity.status}
            className={`${inputClass} w-auto`}
          >
            {STATUS_OPTIONS.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
          <button type="submit" className={buttonVariants.secondary}>
            Atualizar status
          </button>
        </form>
      </div>

      <div>
        <h2 className="text-sm font-semibold text-gray-900">Mensagens</h2>
        <p className="mt-1 text-xs text-gray-400">
          Geradas por IA a partir do problema/solução acima — você revisa, edita se quiser, aprova
          e envia manualmente (nunca automático). Sugestão de oferta ainda não existe; isso é
          Fase 8.
        </p>

        {opportunity.company_do_not_contact ? (
          <p className="mt-3 text-sm font-medium text-red-700">
            Esta empresa está marcada “não contatar” — geração e envio de mensagens estão
            bloqueados.
          </p>
        ) : (
          <form
            action={async (formData: FormData) => {
              "use server";
              const channel = formData.get("channel") as MessageChannel;
              await generateMessageAction(opportunity.id, channel);
            }}
            className="mt-3 flex flex-wrap items-center gap-2"
          >
            <select name="channel" defaultValue="WHATSAPP" className={`${inputClass} w-auto`}>
              {CHANNEL_OPTIONS.map((channel) => (
                <option key={channel} value={channel}>
                  {channel}
                </option>
              ))}
            </select>
            <button type="submit" className={buttonVariants.primary}>
              Gerar mensagem
            </button>
            <span className="text-xs text-gray-400">
              leva alguns segundos — atualize a página depois
            </span>
          </form>
        )}

        <ul className="mt-4 space-y-4">
          {messages.map((message) => (
            <li key={message.id} className={cardClass}>
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium text-gray-500">{message.channel}</span>
                <span className={badgeClass(MESSAGE_STATUS_VARIANT[message.status])}>
                  {message.status}
                </span>
              </div>

              {message.status === "DRAFT" ? (
                <form
                  action={async (formData: FormData) => {
                    "use server";
                    const text = formData.get("text") as string;
                    const action = formData.get("action") as string;
                    if (action === "save") {
                      await updateMessageAction(message.id, opportunity.id, { text });
                    } else if (action === "approve") {
                      await updateMessageAction(message.id, opportunity.id, {
                        text,
                        status: "APPROVED",
                      });
                    } else if (action === "reject") {
                      await updateMessageAction(message.id, opportunity.id, {
                        status: "REJECTED",
                      });
                    }
                  }}
                  className="mt-2 space-y-2"
                >
                  <textarea
                    name="text"
                    defaultValue={message.generated_text}
                    rows={5}
                    className={inputClass}
                  />
                  <div className="flex gap-2">
                    <button type="submit" name="action" value="save" className={buttonVariants.secondary}>
                      Salvar edição
                    </button>
                    <button type="submit" name="action" value="approve" className={buttonVariants.primary}>
                      Aprovar
                    </button>
                    <button type="submit" name="action" value="reject" className={buttonVariants.danger}>
                      Rejeitar
                    </button>
                  </div>
                </form>
              ) : (
                <p className="mt-2 whitespace-pre-wrap text-sm text-gray-700">
                  {message.generated_text}
                </p>
              )}

              {message.status === "APPROVED" && !opportunity.company_do_not_contact && (
                <form
                  action={updateMessageAction.bind(null, message.id, opportunity.id, {
                    status: "SENT",
                  })}
                  className="mt-2"
                >
                  <button type="submit" className={buttonVariants.primary}>
                    Marcar como enviada (envio é manual, fora do sistema)
                  </button>
                </form>
              )}

              {message.status === "SENT" && (
                <div className="mt-2 text-xs text-gray-400">
                  Enviada em{" "}
                  {message.sent_at ? new Date(message.sent_at).toLocaleString("pt-BR") : "—"}
                  {message.response && (
                    <p className="mt-1 text-sm text-gray-700">Resposta: {message.response}</p>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
