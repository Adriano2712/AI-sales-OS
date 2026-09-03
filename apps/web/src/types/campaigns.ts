export type CampaignStatus = "DRAFT" | "ACTIVE" | "PAUSED" | "COMPLETED" | "ARCHIVED";

export type CampaignRunStatus = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";

export interface Campaign {
  id: string;
  tenant_id: string;
  name: string;
  segment: string;
  cities: string[];
  state: string;
  country: string;
  target_quantity: number;
  filters: Record<string, unknown>;
  status: CampaignStatus;
  created_at: string;
  updated_at: string;
}

export interface CampaignRun {
  id: string;
  campaign_id: string;
  started_at: string | null;
  finished_at: string | null;
  status: CampaignRunStatus;
  companies_found: number;
  companies_validated: number;
  duplicates: number;
  enriched: number;
  analyzed: number;
  opportunities: number;
  errors: unknown[];
  created_at: string;
  updated_at: string;
}
