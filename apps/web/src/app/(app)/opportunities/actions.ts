"use server";

import { revalidatePath } from "next/cache";

import { apiFetch } from "@/lib/api";
import type { MessageChannel, MessageStatus } from "@/types/messages";
import type { OpportunityStatus } from "@/types/opportunities";

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
