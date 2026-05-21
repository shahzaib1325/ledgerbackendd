"""
WhatsApp receipt delivery endpoint.

  POST /whatsapp/send-receipt   — send a sale invoice as a WhatsApp message
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models.auth import User
from app.schemas.common import SuccessResponse
from app.schemas.whatsapp import WhatsAppReceiptRequest, WhatsAppReceiptResponse
from app.services import sale_service
from app.services import whatsapp_service

router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]
WriteDep = Annotated[User, Depends(require_permission("sales", "write"))]


@router.post(
    "/send-receipt",
    summary="Send a sale invoice receipt via WhatsApp Business Cloud API",
)
async def send_whatsapp_receipt(
    body: WhatsAppReceiptRequest,
    db: DbDep,
    _: WriteDep,
) -> SuccessResponse[WhatsAppReceiptResponse]:
    sale = await sale_service.get_sale(db, body.sale_id)

    message = whatsapp_service.build_receipt_message(sale)

    try:
        message_id = await whatsapp_service.send_receipt(body.phone, message)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return SuccessResponse(data=WhatsAppReceiptResponse(message_id=message_id))
