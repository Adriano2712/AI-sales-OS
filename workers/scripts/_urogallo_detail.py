import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api" / "src"))

from sqlalchemy import select  # noqa: E402

from app.core.db import async_session_factory, set_tenant_context  # noqa: E402
from app.modules.business_analysis.service import get_latest_business_analysis  # noqa: E402
from app.modules.companies.models import Company  # noqa: E402
from app.modules.opportunities.models import Opportunity  # noqa: E402
from app.modules.website_analysis.service import get_latest_analysis  # noqa: E402

TENANT_ID = uuid.UUID("7a7b98c8-5b96-4cc6-8823-d734ce69ad61")


async def main() -> None:
    async with async_session_factory() as db:
        await set_tenant_context(db, TENANT_ID)
        company = (
            await db.execute(
                select(Company).where(
                    Company.tenant_id == TENANT_ID, Company.name.ilike("%urogallo%")
                )
            )
        ).scalar_one()
        print("company:", company.name, "|", company.website, "|", company.phone)

        wa = await get_latest_analysis(db, TENANT_ID, company.id)
        if wa:
            print("\nwebsite_analysis:")
            print(" status:", wa.status)
            print(" digital_score (aggregate):", wa.digital_score)
            print(" score_funcionamento:", wa.score_funcionamento)
            print(" score_mobile:", wa.score_mobile)
            print(" score_conversao:", wa.score_conversao)
            print(" score_conteudo:", wa.score_conteudo)
            print(" findings:", wa.findings)

        ba = await get_latest_business_analysis(db, TENANT_ID, company.id)
        if ba:
            print("\nbusiness_analysis:")
            print(" digital_maturity_score:", ba.digital_maturity_score)
            print(" need_score:", ba.need_score)
            print(" overall_score:", ba.overall_score)
            print(" findings:", ba.findings)
            print(" problems:", ba.problems)
            print(" buying_potential:", ba.buying_potential_summary)

        opps = (
            await db.execute(select(Opportunity).where(Opportunity.company_id == company.id))
        ).scalars().all()
        for opp in opps:
            print("\nopportunity:", opp.id, opp.type)
            print(" classification:", opp.classification, "score:", opp.opportunity_score)
            print(" reasons:", opp.reasons)
            print(" problem:", opp.problem)
            print(" potential_solution:", opp.potential_solution)


if __name__ == "__main__":
    asyncio.run(main())
