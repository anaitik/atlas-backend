"""
Blockchain provenance service for document hash anchoring and verification.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

import structlog
from eth_account import Account
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from app.config import get_settings
from app.core.errors import AppError, ErrorCode

logger = structlog.get_logger()
settings = get_settings()

DEFAULT_POLYGON_RPC_URL = "https://rpc-amoy.polygon.technology/"
HASH_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_GAS_LIMIT = 500000
DEFAULT_PRIORITY_FEE_GWEI = 25
DEFAULT_RECEIPT_TIMEOUT_SECONDS = 120
DEFAULT_HASHSTORE_ABI: list[dict[str, Any]] = [
    {
        "inputs": [{"internalType": "bytes32[]", "name": "_fileHashes", "type": "bytes32[]"}],
        "name": "storeHashes",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "_fileHash", "type": "bytes32"}],
        "name": "verifyHash",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
]


def _chain_config_path() -> Path | None:
    configured_path = os.getenv("HASHSTORE_CHAIN_CONFIG_PATH")
    if configured_path:
        candidate = Path(configured_path).expanduser()
        return candidate if candidate.exists() else None

    file_path = Path(__file__).resolve()
    candidates = []
    for parent in file_path.parents:
        candidates.append(parent / "chain_config.json")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _load_chain_config() -> dict[str, Any]:
    chain_config_path = _chain_config_path()
    if not chain_config_path:
        return {}
    try:
        return json.loads(chain_config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("blockchain_chain_config_invalid", path=str(chain_config_path), error=str(exc))
        return {}


def _normalize_hash(file_hash: str) -> str:
    candidate = (file_hash or "").strip().lower()
    if candidate.startswith("0x"):
        candidate = candidate[2:]
    if not HASH_HEX_PATTERN.fullmatch(candidate):
        raise AppError(ErrorCode.BAD_REQUEST, "A valid SHA-256 hash is required.")
    return candidate


def _rpc_url() -> str:
    return settings.POLYGON_RPC_URL or DEFAULT_POLYGON_RPC_URL


def _contract_address() -> str | None:
    raw_address = settings.HASHSTORE_CONTRACT_ADDRESS or _load_chain_config().get("address")
    if not raw_address:
        return None
    try:
        return Web3.to_checksum_address(raw_address)
    except ValueError:
        logger.warning("blockchain_contract_address_invalid", address=raw_address)
        return None


def _contract_abi() -> list[dict[str, Any]]:
    abi = _load_chain_config().get("abi")
    if isinstance(abi, list) and abi:
        return abi
    return DEFAULT_HASHSTORE_ABI


def _is_read_configured() -> bool:
    return settings.BLOCKCHAIN_ENABLED and bool(_contract_address() and _contract_abi() and _rpc_url())


def _is_write_configured() -> bool:
    return _is_read_configured() and bool(settings.SIGNER_PRIVATE_KEY)


def _web3_client() -> Web3:
    w3 = Web3(Web3.HTTPProvider(_rpc_url()))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


def _contract(w3: Web3):
    address = _contract_address()
    if not address:
        return None
    return w3.eth.contract(address=address, abi=_contract_abi())


def blockchain_metadata() -> dict[str, Any]:
    enabled = _is_read_configured()
    return {
        "blockchain_enabled": settings.BLOCKCHAIN_ENABLED,
        "chain_id": settings.POLYGON_CHAIN_ID if enabled else None,
        "contract_address": _contract_address() if enabled else None,
    }


def _transaction_fee_fields(w3: Web3) -> dict[str, int]:
    latest_block = w3.eth.get_block("latest")
    base_fee = latest_block.get("baseFeePerGas")
    if base_fee is None:
        return {"gasPrice": int(w3.eth.gas_price)}

    priority_fee = w3.to_wei(DEFAULT_PRIORITY_FEE_GWEI, "gwei")
    return {
        "maxPriorityFeePerGas": int(priority_fee),
        "maxFeePerGas": int(base_fee * 2) + int(priority_fee),
    }


def _anchor_document_hash_sync(file_hash: str) -> str | None:
    normalized_hash = _normalize_hash(file_hash)
    if not _is_write_configured():
        return None

    w3 = _web3_client()
    contract = _contract(w3)
    if not contract:
        return None

    account = Account.from_key(settings.SIGNER_PRIVATE_KEY)
    nonce = w3.eth.get_transaction_count(account.address)
    tx = contract.functions.storeHashes([bytes.fromhex(normalized_hash)]).build_transaction(
        {
            "from": account.address,
            "nonce": nonce,
            "chainId": settings.POLYGON_CHAIN_ID,
            "gas": DEFAULT_GAS_LIMIT,
            **_transaction_fee_fields(w3),
        }
    )

    signed_tx = w3.eth.account.sign_transaction(tx, private_key=settings.SIGNER_PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=DEFAULT_RECEIPT_TIMEOUT_SECONDS)
    if receipt.status != 1:
        raise AppError(ErrorCode.DEPENDENCY_FAILURE, "Blockchain transaction failed.")
    return receipt.transactionHash.hex()


def _verify_document_hash_sync(file_hash: str) -> bool:
    normalized_hash = _normalize_hash(file_hash)
    if not _is_read_configured():
        return False

    w3 = _web3_client()
    contract = _contract(w3)
    if not contract:
        return False

    return bool(contract.functions.verifyHash(bytes.fromhex(normalized_hash)).call())


async def anchor_document_hash(file_hash: str) -> str | None:
    if not _is_write_configured():
        return None
    try:
        tx_hash = await asyncio.to_thread(_anchor_document_hash_sync, file_hash)
        if tx_hash:
            logger.info("blockchain_hash_anchored", tx_hash=tx_hash)
        return tx_hash
    except AppError:
        raise
    except Exception as exc:
        logger.error("blockchain_anchor_failed_detailed", error=str(exc), exc_info=True)
        raise AppError(ErrorCode.DEPENDENCY_FAILURE, f"Failed to anchor document hash on blockchain: {str(exc)}")


async def verify_document_hash(file_hash: str) -> bool:
    if not _is_read_configured():
        return False
    try:
        return await asyncio.to_thread(_verify_document_hash_sync, file_hash)
    except AppError:
        raise
    except Exception as exc:
        logger.exception("blockchain_verify_failed", error=str(exc))
        raise AppError(ErrorCode.DEPENDENCY_FAILURE, "Failed to verify document hash on blockchain.")


async def build_hash_verification(file_hash: str) -> dict[str, Any]:
    normalized_hash = _normalize_hash(file_hash)
    payload = {
        "sha256_hash": normalized_hash,
        **blockchain_metadata(),
    }
    if not payload["blockchain_enabled"]:
        return {
            **payload,
            "verified_on_chain": False,
            "verification_status": "not_configured",
        }

    verified = await verify_document_hash(normalized_hash)
    return {
        **payload,
        "verified_on_chain": verified,
        "verification_status": "verified" if verified else "not_found",
    }
