export type CompanyStatus = "DISCOVERED" | "VALIDATING" | "VALIDATED" | "INVALID" | "DUPLICATE";

export interface Company {
  id: string;
  tenant_id: string;
  name: string;
  normalized_name: string;
  segment: string;
  address: string | null;
  city: string;
  state: string;
  country: string;
  phone: string | null;
  website: string | null;
  status: CompanyStatus;
  needs_review: boolean;
  do_not_contact: boolean;
  created_at: string;
  updated_at: string;
}

export interface CompanySource {
  id: string;
  company_id: string;
  provider: string;
  external_id: string;
  source_url: string | null;
  collected_at: string;
  data: Record<string, unknown>;
}

export type EvidenceConfidence = "HIGH" | "MEDIUM" | "LOW" | "UNKNOWN";

export interface Evidence {
  id: string;
  company_id: string;
  claim: string;
  source: string;
  source_url: string | null;
  collected_at: string;
  confidence: EvidenceConfidence;
  supporting_data: Record<string, unknown>;
}

export interface WebsiteAnalysis {
  id: string;
  website_id: string;
  digital_score: number | null;
  score_funcionamento: number | null;
  score_mobile: number | null;
  score_ux: number | null;
  score_conversao: number | null;
  score_conteudo: number | null;
  score_design: number | null;
  findings: Record<string, unknown>;
  analyzed_at: string;
}

export interface BusinessAnalysis {
  id: string;
  company_id: string;
  business_fit_score: number | null;
  activity_score: number | null;
  digital_maturity_score: number | null;
  need_score: number | null;
  compatibility_score: number | null;
  overall_score: number | null;
  confidence: number | null;
  findings: string[];
  problems: string[];
  analyzed_at: string;
}

export interface CompanyDetail extends Company {
  sources: CompanySource[];
  evidence: Evidence[];
  website_analysis: WebsiteAnalysis | null;
  business_analysis: BusinessAnalysis | null;
}
