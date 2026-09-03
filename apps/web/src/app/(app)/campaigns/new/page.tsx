import { createCampaignAction } from "@/app/(app)/campaigns/actions";
import { PageHeader } from "@/components/PageHeader";
import { requireUser } from "@/lib/requireUser";
import { buttonVariants, cardClass, inputClass } from "@/lib/ui";

export default async function NewCampaignPage() {
  await requireUser();

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <PageHeader title="Nova Campanha" />

      <form action={createCampaignAction} className={`${cardClass} space-y-4`}>
        <div className="space-y-1">
          <label className="text-sm font-medium text-gray-700" htmlFor="name">
            Nome
          </label>
          <input id="name" name="name" required className={inputClass} />
        </div>

        <div className="space-y-1">
          <label className="text-sm font-medium text-gray-700" htmlFor="segment">
            Segmento
          </label>
          <input
            id="segment"
            name="segment"
            required
            placeholder="restaurants, clinics, b2b_services..."
            className={inputClass}
          />
        </div>

        <div className="space-y-1">
          <label className="text-sm font-medium text-gray-700" htmlFor="cities">
            Cidades (separadas por vírgula)
          </label>
          <input
            id="cities"
            name="cities"
            required
            placeholder="Sorocaba, Votorantim, Campinas"
            className={inputClass}
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1">
            <label className="text-sm font-medium text-gray-700" htmlFor="state">
              Estado
            </label>
            <input id="state" name="state" required defaultValue="SP" className={inputClass} />
          </div>
          <div className="space-y-1">
            <label className="text-sm font-medium text-gray-700" htmlFor="country">
              País
            </label>
            <input
              id="country"
              name="country"
              defaultValue="BR"
              maxLength={2}
              className={inputClass}
            />
          </div>
        </div>

        <div className="space-y-1">
          <label className="text-sm font-medium text-gray-700" htmlFor="target_quantity">
            Quantidade alvo
          </label>
          <input
            id="target_quantity"
            name="target_quantity"
            type="number"
            min={1}
            required
            defaultValue={100}
            className={inputClass}
          />
        </div>

        <button type="submit" className={`${buttonVariants.primary} w-full`}>
          Criar Campanha
        </button>
      </form>
    </div>
  );
}
