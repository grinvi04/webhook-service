#!/usr/bin/env bash
# 로컬 개발용 테스트 테넌트를 DB에 생성합니다.
#
# 사전 조건:
#   docker-compose up -d db
#   alembic upgrade head
#
# 사용법:
#   ./scripts/seed_tenant.sh
#
# 생성 후 docs/examples/http.env 의 값과 일치해야 합니다:
#   tenantId      = demo-tenant
#   webhookSecret = my-super-secret-key

set -euo pipefail

DB_URL="${DATABASE_URL:-postgresql+psycopg2://user:password@localhost:5433/webhook_db}"

python3 - <<PYTHON
import sys
sys.path.insert(0, ".")

from app.database import SessionLocal
from app.models.customer import Customer

db = SessionLocal()
try:
    existing = db.query(Customer).filter(Customer.tenant_id == "demo-tenant").first()
    if existing:
        print("테스트 테넌트가 이미 존재합니다.")
        print(f"  tenant_id     : {existing.tenant_id}")
        print(f"  webhook_secret: {existing.webhook_secret}")
        sys.exit(0)

    tenant = Customer(
        tenant_id="demo-tenant",
        name="Demo Tenant",
        webhook_secret="my-super-secret-key",
        is_active=True,
        allowed_event_types=[],
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    print("테스트 테넌트를 생성했습니다.")
    print(f"  id            : {tenant.id}")
    print(f"  tenant_id     : {tenant.tenant_id}")
    print(f"  webhook_secret: {tenant.webhook_secret}")
finally:
    db.close()
PYTHON
