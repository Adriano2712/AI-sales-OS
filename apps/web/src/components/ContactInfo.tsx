/** Consistent phone/website rendering everywhere a company shows up
 * (dashboard, opportunities list/detail, companies list/detail) — never a
 * raw "undefined"/"null", always a real link when there's something to
 * link to. */

function formatPhoneDisplay(phone: string): string {
  const digits = phone.replace(/\D/g, "");
  // Brazilian numbers: DDD + 8 or 9 digits, optionally with country code 55.
  const local = digits.startsWith("55") && digits.length > 11 ? digits.slice(2) : digits;
  if (local.length === 11) {
    return `(${local.slice(0, 2)}) ${local.slice(2, 7)}-${local.slice(7)}`;
  }
  if (local.length === 10) {
    return `(${local.slice(0, 2)}) ${local.slice(2, 6)}-${local.slice(6)}`;
  }
  return phone;
}

export function PhoneLink({ phone }: { phone: string | null }) {
  if (!phone) {
    return <span className="text-gray-400">Não informado</span>;
  }
  const digits = phone.replace(/[^\d+]/g, "");
  return (
    <a href={`tel:${digits}`} className="text-gray-700 hover:text-blue-600 hover:underline">
      {formatPhoneDisplay(phone)}
    </a>
  );
}

export function WebsiteLink({ website }: { website: string | null }) {
  if (!website) {
    return <span className="text-gray-400">Não informado</span>;
  }
  let display = website;
  try {
    const url = new URL(website.startsWith("http") ? website : `https://${website}`);
    display = url.hostname.replace(/^www\./, "");
  } catch {
    // Keep the raw string if it doesn't parse as a URL — never hide it.
  }
  return (
    <a
      href={website.startsWith("http") ? website : `https://${website}`}
      target="_blank"
      rel="noopener noreferrer"
      className="text-gray-700 hover:text-blue-600 hover:underline"
    >
      {display}
    </a>
  );
}
