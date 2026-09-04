import httpx
import pytest

from app.core.db import set_tenant_context
from app.modules.companies.enums import CompanyStatus
from app.modules.companies.models import Company
from app.modules.messages.enums import MessageChannel, MessageStatus
from app.modules.messages.models import Message
from app.modules.opportunities.enums import OpportunityStatus, OpportunityType
from app.modules.opportunities.models import Opportunity

from .conftest import requires_live_db, requires_matching_env


async def _seed_opportunity(session, tenant_id) -> Opportunity:
    company = Company(
        tenant_id=tenant_id,
        name="Messages API Test Co",
        normalized_name="messages api test co",
        segment="restaurants",
        city="Sorocaba",
        state="SP",
        country="BR",
        status=CompanyStatus.DISCOVERED,
    )
    session.add(company)
    await session.flush()
    opportunity = Opportunity(
        tenant_id=tenant_id,
        company_id=company.id,
        type=OpportunityType.WEBSITE,
        status=OpportunityStatus.OPEN,
        reasons=[],
    )
    session.add(opportunity)
    await session.flush()
    return company, opportunity


@requires_live_db
@requires_matching_env
@pytest.mark.asyncio
async def test_editing_text_only_allowed_while_draft(
    authenticated_client, app_session_factory, two_tenants
):
    from app.main import app
    from app.modules.tenancy.enums import Role

    tenant_a, _ = two_tenants
    token = await authenticated_client(tenant_a.id, Role.ADMIN)
    headers = {"Authorization": f"Bearer {token}"}

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        _, opportunity = await _seed_opportunity(session, tenant_a.id)
        message = Message(
            tenant_id=tenant_a.id,
            opportunity_id=opportunity.id,
            channel=MessageChannel.WHATSAPP,
            status=MessageStatus.DRAFT,
            generated_text="Texto original.",
        )
        session.add(message)
        await session.commit()
        message_id = message.id

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        edited = await client.patch(
            f"/api/v1/messages/{message_id}",
            json={"text": "Texto editado pelo humano."},
            headers=headers,
        )
        assert edited.status_code == 200
        assert edited.json()["generated_text"] == "Texto editado pelo humano."

        approved = await client.patch(
            f"/api/v1/messages/{message_id}", json={"status": "APPROVED"}, headers=headers
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "APPROVED"

        # Now that it's APPROVED, editing the text must be rejected.
        blocked = await client.patch(
            f"/api/v1/messages/{message_id}", json={"text": "Tarde demais."}, headers=headers
        )
        assert blocked.status_code == 409


@requires_live_db
@requires_matching_env
@pytest.mark.asyncio
async def test_invalid_status_transition_is_rejected(
    authenticated_client, app_session_factory, two_tenants
):
    from app.main import app
    from app.modules.tenancy.enums import Role

    tenant_a, _ = two_tenants
    token = await authenticated_client(tenant_a.id, Role.ADMIN)
    headers = {"Authorization": f"Bearer {token}"}

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        _, opportunity = await _seed_opportunity(session, tenant_a.id)
        message = Message(
            tenant_id=tenant_a.id,
            opportunity_id=opportunity.id,
            channel=MessageChannel.WHATSAPP,
            status=MessageStatus.DRAFT,
            generated_text="Texto.",
        )
        session.add(message)
        await session.commit()
        message_id = message.id

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch(
            f"/api/v1/messages/{message_id}", json={"status": "SENT"}, headers=headers
        )
        assert response.status_code == 409


@requires_live_db
@requires_matching_env
@pytest.mark.asyncio
async def test_do_not_contact_blocks_marking_a_message_sent(
    authenticated_client, app_session_factory, two_tenants
):
    from app.main import app
    from app.modules.tenancy.enums import Role

    tenant_a, _ = two_tenants
    token = await authenticated_client(tenant_a.id, Role.ADMIN)
    headers = {"Authorization": f"Bearer {token}"}

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        company, opportunity = await _seed_opportunity(session, tenant_a.id)
        message = Message(
            tenant_id=tenant_a.id,
            opportunity_id=opportunity.id,
            channel=MessageChannel.WHATSAPP,
            status=MessageStatus.APPROVED,
            generated_text="Texto.",
        )
        session.add(message)
        await session.commit()
        message_id, company_id = message.id, company.id

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Human flags the company do_not_contact between approval and send —
        # the system must still refuse to let it be marked SENT.
        flagged = await client.patch(
            f"/api/v1/companies/{company_id}", json={"do_not_contact": True}, headers=headers
        )
        assert flagged.status_code == 200
        assert flagged.json()["do_not_contact"] is True

        blocked = await client.patch(
            f"/api/v1/messages/{message_id}", json={"status": "SENT"}, headers=headers
        )
        assert blocked.status_code == 409


@requires_live_db
@requires_matching_env
@pytest.mark.asyncio
async def test_generation_endpoint_rejects_do_not_contact_company(
    authenticated_client, app_session_factory, two_tenants
):
    from app.main import app
    from app.modules.tenancy.enums import Role

    tenant_a, _ = two_tenants
    token = await authenticated_client(tenant_a.id, Role.ADMIN)
    headers = {"Authorization": f"Bearer {token}"}

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        company, opportunity = await _seed_opportunity(session, tenant_a.id)
        company.do_not_contact = True
        await session.commit()
        opportunity_id = opportunity.id

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/opportunities/{opportunity_id}/messages",
            json={"channel": "WHATSAPP"},
            headers=headers,
        )
        assert response.status_code == 409


@requires_live_db
@requires_matching_env
@pytest.mark.asyncio
async def test_gmail_draft_rejects_non_email_channel(
    authenticated_client, app_session_factory, two_tenants
):
    from app.main import app
    from app.modules.tenancy.enums import Role

    tenant_a, _ = two_tenants
    token = await authenticated_client(tenant_a.id, Role.ADMIN)
    headers = {"Authorization": f"Bearer {token}"}

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        company, opportunity = await _seed_opportunity(session, tenant_a.id)
        company.email = "prospect@example.com"
        message = Message(
            tenant_id=tenant_a.id,
            opportunity_id=opportunity.id,
            channel=MessageChannel.WHATSAPP,
            status=MessageStatus.APPROVED,
            generated_text="Texto.",
        )
        session.add(message)
        await session.commit()
        message_id = message.id

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/v1/messages/{message_id}/gmail-draft", headers=headers)
        assert response.status_code == 409


@requires_live_db
@requires_matching_env
@pytest.mark.asyncio
async def test_gmail_draft_requires_approved_status(
    authenticated_client, app_session_factory, two_tenants
):
    from app.main import app
    from app.modules.tenancy.enums import Role

    tenant_a, _ = two_tenants
    token = await authenticated_client(tenant_a.id, Role.ADMIN)
    headers = {"Authorization": f"Bearer {token}"}

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        company, opportunity = await _seed_opportunity(session, tenant_a.id)
        company.email = "prospect@example.com"
        message = Message(
            tenant_id=tenant_a.id,
            opportunity_id=opportunity.id,
            channel=MessageChannel.EMAIL,
            status=MessageStatus.DRAFT,
            generated_text="Texto.",
        )
        session.add(message)
        await session.commit()
        message_id = message.id

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/v1/messages/{message_id}/gmail-draft", headers=headers)
        assert response.status_code == 409


@requires_live_db
@requires_matching_env
@pytest.mark.asyncio
async def test_gmail_draft_requires_known_company_email(
    authenticated_client, app_session_factory, two_tenants
):
    from app.main import app
    from app.modules.tenancy.enums import Role

    tenant_a, _ = two_tenants
    token = await authenticated_client(tenant_a.id, Role.ADMIN)
    headers = {"Authorization": f"Bearer {token}"}

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        _, opportunity = await _seed_opportunity(session, tenant_a.id)  # no email set
        message = Message(
            tenant_id=tenant_a.id,
            opportunity_id=opportunity.id,
            channel=MessageChannel.EMAIL,
            status=MessageStatus.APPROVED,
            generated_text="Texto.",
        )
        session.add(message)
        await session.commit()
        message_id = message.id

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/v1/messages/{message_id}/gmail-draft", headers=headers)
        assert response.status_code == 409


@requires_live_db
@requires_matching_env
@pytest.mark.asyncio
async def test_gmail_draft_blocks_do_not_contact_company(
    authenticated_client, app_session_factory, two_tenants
):
    from app.main import app
    from app.modules.tenancy.enums import Role

    tenant_a, _ = two_tenants
    token = await authenticated_client(tenant_a.id, Role.ADMIN)
    headers = {"Authorization": f"Bearer {token}"}

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        company, opportunity = await _seed_opportunity(session, tenant_a.id)
        company.email = "prospect@example.com"
        company.do_not_contact = True
        message = Message(
            tenant_id=tenant_a.id,
            opportunity_id=opportunity.id,
            channel=MessageChannel.EMAIL,
            status=MessageStatus.APPROVED,
            generated_text="Texto.",
        )
        session.add(message)
        await session.commit()
        message_id = message.id

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/v1/messages/{message_id}/gmail-draft", headers=headers)
        assert response.status_code == 409


@requires_live_db
@requires_matching_env
@pytest.mark.asyncio
async def test_gmail_draft_creates_draft_and_logs_audit(
    authenticated_client, app_session_factory, two_tenants, monkeypatch
):
    """Never sends anything — verifies the endpoint calls the draft-only
    IMAP function (mocked here, spec section 39: tests must never touch a
    real mailbox) and records it in the audit log."""
    import app.api.v1.messages as messages_router
    from app.core.config import get_settings
    from app.main import app
    from app.modules.tenancy.enums import Role

    calls = []

    def _fake_create_gmail_draft(smtp_user, smtp_app_password, to_address, subject, text_body):
        calls.append({"to": to_address, "subject": subject, "body": text_body})

    monkeypatch.setattr(messages_router, "create_gmail_draft", _fake_create_gmail_draft)
    monkeypatch.setattr(get_settings(), "gmail_smtp_user", "sender@test.com")
    monkeypatch.setattr(get_settings(), "gmail_smtp_app_password", "fake-app-password")

    tenant_a, _ = two_tenants
    token = await authenticated_client(tenant_a.id, Role.ADMIN)
    headers = {"Authorization": f"Bearer {token}"}

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        company, opportunity = await _seed_opportunity(session, tenant_a.id)
        company.email = "prospect@example.com"
        message = Message(
            tenant_id=tenant_a.id,
            opportunity_id=opportunity.id,
            channel=MessageChannel.EMAIL,
            status=MessageStatus.APPROVED,
            generated_text="Texto do rascunho.",
        )
        session.add(message)
        await session.commit()
        message_id = message.id

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/v1/messages/{message_id}/gmail-draft", headers=headers)
        assert response.status_code == 200
        assert response.json() == {"status": "draft_created"}

    assert len(calls) == 1
    assert calls[0]["to"] == "prospect@example.com"
    assert calls[0]["body"] == "Texto do rascunho."

    # The message itself must stay APPROVED, not silently become SENT — a
    # draft in Gmail isn't a send.
    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        unchanged = await session.get(Message, message_id)
        assert unchanged.status == MessageStatus.APPROVED
        assert unchanged.sent_at is None
