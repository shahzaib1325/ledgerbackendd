from pydantic import BaseModel, field_validator
import re

_DIGITS_RE = re.compile(r'^\d{7,15}$')


class WhatsAppReceiptRequest(BaseModel):
    sale_id: int
    phone: str

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        digits = re.sub(r'[^\d]', '', v)
        if not _DIGITS_RE.match(digits):
            raise ValueError("Phone must be 7–15 digits in international format (e.g. 8801712345678)")
        return digits


class WhatsAppReceiptResponse(BaseModel):
    message_id: str
