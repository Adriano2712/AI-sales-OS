"use server";

import { revalidatePath } from "next/cache";

import { apiFetch } from "@/lib/api";
import type { CompanyStatus } from "@/types/companies";

export async function updateCompanyStatusAction(
  companyId: string,
  status: CompanyStatus
): Promise<void> {
  const response = await apiFetch(`/api/v1/companies/${companyId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Atualizar status da empresa falhou (${response.status}): ${body}`);
  }

  revalidatePath(`/companies/${companyId}`);
  revalidatePath("/companies");
}

export async function updateCompanyDoNotContactAction(
  companyId: string,
  doNotContact: boolean
): Promise<void> {
  const response = await apiFetch(`/api/v1/companies/${companyId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ do_not_contact: doNotContact }),
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Atualizar do_not_contact falhou (${response.status}): ${body}`);
  }

  revalidatePath(`/companies/${companyId}`);
  revalidatePath("/companies");
}
