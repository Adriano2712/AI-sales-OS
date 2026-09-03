import { Sidebar } from "@/components/Sidebar";
import { requireUser } from "@/lib/requireUser";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const user = await requireUser();

  return (
    <div className="flex min-h-screen bg-gray-50">
      <Sidebar email={user.email ?? ""} />
      <main className="min-w-0 flex-1">
        <div className="mx-auto max-w-6xl px-8 py-8">{children}</div>
      </main>
    </div>
  );
}
