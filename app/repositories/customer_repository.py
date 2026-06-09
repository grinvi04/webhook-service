from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ..models.customer import Customer


class CustomerRepository:
    """Customer 데이터 접근 전용.

    세션은 호출부가 소유(주입)한다. is_active 등 정책 판단(HTTP 403 등)은
    웹 레이어(WebhookVerifier)에 두고, 여기서는 조회만 한다.
    """

    def get_by_tenant_id(self, db: Session, tenant_id: str) -> Customer | None:
        return db.query(Customer).filter(Customer.tenant_id == tenant_id).first()

    async def get_by_tenant_id_async(
        self, db: AsyncSession, tenant_id: str
    ) -> Customer | None:
        result = await db.execute(
            select(Customer).where(Customer.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()
