from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel

class DocumentOut(BaseModel):
    id: str
    filename: str
    content_type: str
    file_size_bytes: int
    sha256_hash: str
    status: str
    blockchain_tx_id: Optional[str]
    uploaded_by_id: str
    created_at: datetime


class HashVerificationRequest(BaseModel):
    sha256_hash: str


class HashVerificationOut(BaseModel):
    sha256_hash: str
    blockchain_enabled: bool
    chain_id: Optional[int]
    contract_address: Optional[str]
    verified_on_chain: bool
    verification_status: Literal["verified", "not_found", "not_configured"]


class DocumentVerificationOut(HashVerificationOut):
    document_id: str
    blockchain_tx_id: Optional[str]
