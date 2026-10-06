from uuid import UUID

from fastapi import Header, HTTPException
from rag_core.contracts import Principal


async def current_principal(
    x_user_id: str = Header(...),
    x_tenant_id: UUID = Header(...),
    x_roles: str = Header("reader"),
) -> Principal:
    # Replace trusted headers with verified OIDC/JWT claims behind the gateway.
    roles = [role.strip() for role in x_roles.split(",") if role.strip()]
    if not roles:
        raise HTTPException(403, "at least one role is required")
    return Principal(subject=x_user_id, tenant_id=x_tenant_id, roles=roles)
