"""Send a custom digest containing ONLY HIGH/GOOD opportunities for a given
CampaignRun, per the user's explicit preference (2026-09-11): they don't
want REVIEW/LOW cluttering the results, and if nothing qualifies, say so
honestly rather than staying silent. Reuses BusinessAnalysis/Opportunity
data and the same Gmail SMTP sender as scheduler._send_digest_for_run, but
with its own filtered template instead of that function's list-everyone
one."""

import asyncio
import sys
import uuid
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api" / "src"))

from sqlalchemy import select  # noqa: E402

from app.core import model_registry  # noqa: E402,F401
from app.core.config import get_settings  # noqa: E402
from app.core.db import async_session_factory, set_tenant_context  # noqa: E402
from app.modules.business_analysis.service import get_latest_business_analysis  # noqa: E402
from app.modules.campaigns.models import Campaign, CampaignRun  # noqa: E402
from app.modules.companies.models import Company  # noqa: E402
from app.modules.notifications.email_sender import send_email  # noqa: E402
from app.modules.opportunities.models import Opportunity  # noqa: E402

TENANT_ID = uuid.UUID("7a7b98c8-5b96-4cc6-8823-d734ce69ad61")
GOOD = {"HIGH", "GOOD", "REVIEW"}


async def send_for_run(run_id: uuid.UUID, label: str) -> None:
    async with async_session_factory() as db:
        await set_tenant_context(db, TENANT_ID)
        run = await db.get(CampaignRun, run_id)
        campaign = await db.get(Campaign, run.campaign_id)
        companies = (
            await db.execute(select(Company).where(Company.campaign_run_id == run_id))
        ).scalars().all()

        rows = []
        for c in companies:
            opp = (
                await db.execute(select(Opportunity).where(Opportunity.company_id == c.id).limit(1))
            ).scalar_one_or_none()
            if opp and opp.classification and opp.classification.value in GOOD:
                analysis = await get_latest_business_analysis(db, TENANT_ID, c.id)
                rows.append((c, opp, analysis))

        settings = get_settings()
        total = len(companies)
        good = len(rows)

        if good == 0:
            subject = f"{label}: 0 boas oportunidades (de {total} encontradas)"
            text = (
                f"Busca em {label} ({campaign.segment}): {total} empresas encontradas, "
                f"nenhuma saiu HIGH ou GOOD dessa vez (todas ficaram REVIEW ou LOW).\n\n"
                f"Nenhuma ação recomendada agora."
            )
            html = f"<p>Busca em <b>{escape(label)}</b> ({escape(campaign.segment)}): "
            html += f"<b>{total}</b> empresas encontradas, <b>nenhuma</b> saiu HIGH ou GOOD dessa vez "
            html += "(todas ficaram REVIEW ou LOW).</p><p>Nenhuma ação recomendada agora.</p>"
        else:
            subject = f"{label}: {good} boa(s) oportunidade(s) (de {total} encontradas)"
            lines = [f"Busca em {label} ({campaign.segment}): {good} de {total} saíram HIGH/GOOD.\n"]
            html_rows = ""
            for c, opp, analysis in sorted(rows, key=lambda r: r[1].opportunity_score or 0, reverse=True):
                lines.append(
                    f"- {c.name} | {opp.classification.value} | score {opp.opportunity_score} | "
                    f"tel {c.phone or 'N/A'} | site {c.website or 'nenhum'}"
                )
                if opp.reasons:
                    for r in opp.reasons[:3]:
                        lines.append(f"    * {r}")
                html_rows += (
                    f"<li><b>{escape(c.name)}</b> — {escape(opp.classification.value)} "
                    f"(score {opp.opportunity_score})<br>tel: {escape(c.phone or 'N/A')} | "
                    f"site: {escape(c.website or 'nenhum')}"
                    f"<ul>{''.join(f'<li>{escape(r)}</li>' for r in (opp.reasons or [])[:3])}</ul></li>"
                )
            text = "\n".join(lines)
            html = f"<p>Busca em <b>{escape(label)}</b> ({escape(campaign.segment)}): "
            html += f"<b>{good}</b> de {total} saíram HIGH/GOOD.</p><ul>{html_rows}</ul>"

        await asyncio.to_thread(
            send_email,
            settings.gmail_smtp_user,
            settings.gmail_smtp_app_password,
            settings.daily_digest_recipient_email,
            subject,
            text,
            html,
        )
        print(f"{label}: sent email — {good}/{total} good")


async def main() -> None:
    run_id = uuid.UUID(sys.argv[1])
    label = sys.argv[2]
    await send_for_run(run_id, label)


if __name__ == "__main__":
    asyncio.run(main())
