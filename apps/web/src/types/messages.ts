export type MessageChannel = "EMAIL" | "WHATSAPP" | "LINKEDIN" | "PHONE" | "OTHER";

export type MessageStatus = "DRAFT" | "APPROVED" | "REJECTED" | "SENT";

export type MessageLanguage = "pt-BR" | "en";

export interface Message {
  id: string;
  opportunity_id: string;
  channel: MessageChannel;
  status: MessageStatus;
  language: MessageLanguage;
  generated_text: string;
  sent_at: string | null;
  response: string | null;
  created_at: string;
  updated_at: string;
}
