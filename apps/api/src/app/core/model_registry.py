"""Importing this module (for its side effects) registers every SQLAlchemy
model with app.core.db.Base.metadata.

Needed anywhere models get used without going through app.main's full router
import chain — which pulls every model in transitively as a side effect of
importing the API routes, masking that this is even a requirement. Alembic's
env.py and workers/run.py both need it explicitly: a model whose table is
only ever referenced by a `ForeignKey("other_table.id")` *string* (not an
import of the other model class) fails at mapper-configuration time with
`NoReferencedTableError` if that other class was never imported anywhere in
the process — confirmed the hard way when `Job.tenant_id`'s FK to `tenants`
broke inside a real worker process in Fase 2 (workers/run.py never imported
`app.modules.tenancy.models` at all; nothing in the discovery job's own
import chain does either).

Add new model modules here as they're created — this is the one place a
missing import here silently breaks table resolution rather than failing at
import time.
"""

from app.modules.ai_gateway.models import AICall  # noqa: F401
from app.modules.audit.models import AuditLog  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.business_analysis.models import BusinessAnalysis  # noqa: F401
from app.modules.campaigns.models import Campaign, CampaignRun  # noqa: F401
from app.modules.companies.models import Company, CompanySource  # noqa: F401
from app.modules.evidence.models import Evidence  # noqa: F401
from app.modules.jobs.models import Job  # noqa: F401
from app.modules.messages.models import Message  # noqa: F401
from app.modules.opportunities.models import Opportunity  # noqa: F401
from app.modules.tenancy.models import Membership, Tenant  # noqa: F401
from app.modules.website_analysis.models import Website, WebsiteAnalysis, WebsitePage  # noqa: F401
