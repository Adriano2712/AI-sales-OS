import type { CampaignStatus } from "@/types/campaigns";

// Mirrors apps/api VALID_STATUS_TRANSITIONS (app/modules/campaigns/enums.py).
// The backend is the real enforcement point — this only keeps the UI from
// offering a button that would just come back as a 409.
export const VALID_STATUS_TRANSITIONS: Record<CampaignStatus, CampaignStatus[]> = {
  DRAFT: ["ACTIVE", "ARCHIVED"],
  ACTIVE: ["PAUSED", "COMPLETED", "ARCHIVED"],
  PAUSED: ["ACTIVE", "ARCHIVED"],
  COMPLETED: ["ARCHIVED"],
  ARCHIVED: [],
};
