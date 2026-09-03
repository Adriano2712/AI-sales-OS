export type MessageChannel = "EMAIL" | "WHATSAPP" | "LINKEDIN" | "PHONE" | "OTHER";

export type MessageStatus = "DRAFT" | "APPROVED" | "REJECTED" | "SENT";

export interface Message {
  id: string;
  opportunity_id: string;
  channel: MessageChannel;
  status: MessageStatus;
  generated_text: string;
  sent_at: string | null;
  response: string | null;
  created_at: string;
  updated_at: string;
}
