"use server";

import { revalidatePath } from "next/cache";

import { apiFetch } from "@/lib/api";
import type { MessageChannel, MessageStatus } from "@/types/messages";
import type { OpportunityOutcome, OpportunityStatus } from "@/types/opportunities";

export async function updateOpportunityStatusAction(
  opportunityId: string,
  status: OpportunityStatus
): Promise<void> {
  const response = await apiFetch(`/api/v1/opportunities/${opportunityId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Atualizar status da oportunidade falhou (${response.status}): ${body}`);
  }

  revalidatePath(`/opportunities/${opportunityId}`);
  revalidatePath("/opportunities");
}

export async function updateOpportunityOutcomeAction(
  opportunityId: string,
  outcome: OpportunityOutcome,
  outcomeNotes: string
): Promise<void> {
  const response = await apiFetch(`/api/v1/opportunities/${opportunityId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ outcome, outcome_notes: outcomeNotes }),
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Atualizar estágio de venda falhou (${response.status}): ${body}`);
  }

  revalidatePath(`/opportunities/${opportunityId}`);
  revalidatePath("/dashboard");
}

export async function generateMessageAction(
  opportunityId: string,
  channel: MessageChannel
): Promise<void> {
  const response = await apiFetch(`/api/v1/opportunities/${opportunityId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ channel }),
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Gerar mensagem falhou (${response.status}): ${body}`);
  }

  revalidatePath(`/opportunities/${opportunityId}`);
}

export async function createGmailDraftAction(
  messageId: string,
  opportunityId: string
): Promise<void> {
  const response = await apiFetch(`/api/v1/messages/${messageId}/gmail-draft`, {
    method: "POST",
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Criar rascunho no Gmail falhou (${response.status}): ${body}`);
  }

  revalidatePath(`/opportunities/${opportunityId}`);
}

export async function updateMessageAction(
  messageId: string,
  opportunityId: string,
  data: { text?: string; status?: MessageStatus; response?: string }
): Promise<void> {
  const response = await apiFetch(`/api/v1/messages/${messageId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Atualizar mensagem falhou (${response.status}): ${body}`);
  }

  revalidatePath(`/opportunities/${opportunityId}`);
}
