"use server";

import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";

import { apiFetch } from "@/lib/api";
import type { CampaignStatus } from "@/types/campaigns";

async function assertOk(response: Response, action: string): Promise<void> {
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${action} failed (${response.status}): ${body}`);
  }
}

export async function createCampaignAction(formData: FormData): Promise<void> {
  const cities = String(formData.get("cities") ?? "")
    .split(",")
    .map((c) => c.trim())
    .filter(Boolean);

  const response = await apiFetch("/api/v1/campaigns", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: formData.get("name"),
      segment: formData.get("segment"),
      cities,
      state: formData.get("state"),
      country: formData.get("country") || "BR",
      target_quantity: Number(formData.get("target_quantity")),
      filters: {},
    }),
  });
  await assertOk(response, "Criar campanha");

  const campaign = await response.json();
  revalidatePath("/campaigns");
  redirect(`/campaigns/${campaign.id}`);
}

export async function updateCampaignStatusAction(
  campaignId: string,
  status: CampaignStatus
): Promise<void> {
  const response = await apiFetch(`/api/v1/campaigns/${campaignId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  await assertOk(response, "Atualizar status da campanha");

  revalidatePath(`/campaigns/${campaignId}`);
  revalidatePath("/campaigns");
}

export async function startRunAction(campaignId: string): Promise<void> {
  const response = await apiFetch(`/api/v1/campaigns/${campaignId}/runs`, {
    method: "POST",
  });
  await assertOk(response, "Iniciar run");

  revalidatePath(`/campaigns/${campaignId}`);
}
