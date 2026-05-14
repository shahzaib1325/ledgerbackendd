import sys
import os

sys.path.append('s:/RIVON/SmartLedger/ledgerbackend')

try:
    from app.api.v1.router import api_router
    print("=== APIS ===")
    for route in api_router.routes:
        methods = ",".join(route.methods) if hasattr(route, 'methods') else ''
        path = route.path
        module = route.endpoint.__module__ if hasattr(route, 'endpoint') else ''
        print(f"Route: {path} | Method: {methods} | File: {module}")
except Exception as e:
    print(f"API Error: {e}")

try:
    from app.core.database import Base
    import app.models  # This should load all models due to __init__.py
    print("\n=== MODELS ===")
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        print(f"Table: {cls.__tablename__}")
        for col in mapper.columns:
            print(f"  - {col.name} ({col.type})")
except Exception as e:
    print(f"Model Error: {e}")

