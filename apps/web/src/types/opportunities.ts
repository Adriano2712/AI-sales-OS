export type OpportunityType =
  | "WEBSITE"
  | "E_COMMERCE"
  | "AUTOMATION"
  | "INTERNAL_SYSTEM"
  | "INTEGRATION"
  | "DIGITAL_PRESENCE"
  | "OTHER";

export type OpportunityStatus = "OPEN" | "REVIEWING" | "APPROVED" | "REJECTED" | "ARCHIVED";

export type OpportunityClassification = "HIGH" | "GOOD" | "REVIEW" | "LOW";

export interface Opportunity {
  id: string;
  company_id: string;
  type: OpportunityType;
  status: OpportunityStatus;
  problem: string | null;
  potential_solution: string | null;
  reasons: string[];
  digital_gap: number | null;
  business_fit: number | null;
  need: number | null;
  commercial_signals: number | null;
  opportunity_score: number | null;
  confidence: number | null;
  classification: OpportunityClassification | null;
  created_at: string;
  updated_at: string;
}

export interface OpportunityDetail extends Opportunity {
  company_name: string;
  company_segment: string;
  company_city: string;
  company_state: string;
  company_phone: string | null;
  company_website: string | null;
  next_action: string;
  company_do_not_contact: boolean;
}

export interface DashboardSummary {
  discovery: {
    companies_found: number;
    companies_validated: number;
    duplicates: number;
    enriched: number;
    analyzed: number;
  };
  opportunities: {
    total: number;
    high: number;
    good: number;
    review: number;
    low: number;
  };
  cost: {
    total_estimated_cost_usd: number;
    ai_calls: number;
  };
}
