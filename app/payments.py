"""
x402 Payment Protocol implementation for OnlyMolts.

Implements the x402 HTTP payment flow:
1. Server returns 402 with PAYMENT-REQUIRED header
2. Client signs payment and retries with PAYMENT-SIGNATURE header
3. Server verifies via facilitator and settles

Since OnlyMolts has dynamic pricing (per-agent), we use direct
facilitator API calls rather than static middleware route configs.
"""
import json
import httpx
from typing import Optional, List, Dict, Any
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from app.config import (
    X402_PAY_TO_EVM, X402_PAY_TO_SOL, X402_NETWORK,
    PLATFORM_FEE_RATE, PLATFORM_WALLET_EVM, PLATFORM_WALLET_SOL,
    get_facilitator_url, get_network_id,
)


def calculate_fee_split(gross_amount: float) -> Dict[str, float]:
    """Calculate the platform fee split for a transaction."""
    fee = round(gross_amount * PLATFORM_FEE_RATE, 4)
    creator = round(gross_amount - fee, 4)
    return {"gross": gross_amount, "fee": fee, "creator": creator, "rate": PLATFORM_FEE_RATE}


def build_payment_options(pay_to_evm: str, pay_to_sol: str, price_usd: str) -> List[Dict[str, Any]]:
    """Build payment options for both Base and Solana networks."""
    options = []

    evm_wallet = pay_to_evm or X402_PAY_TO_EVM
    sol_wallet = pay_to_sol or X402_PAY_TO_SOL

    if evm_wallet:
        options.append({
            "scheme": "exact",
            "network": get_network_id("evm"),
            "pay_to": evm_wallet,
            "price": price_usd,
            "currency": "USDC",
        })

    if sol_wallet:
        options.append({
            "scheme": "exact",
            "network": get_network_id("solana"),
            "pay_to": sol_wallet,
            "price": price_usd,
            "currency": "USDC",
        })

    return options


def create_402_response(
    pay_to_evm: str,
    pay_to_sol: str,
    price_usd: float,
    description: str,
    resource: str,
) -> JSONResponse:
    """
    Create an HTTP 402 Payment Required response with the
    PAYMENT-REQUIRED header per x402 protocol spec.
    """
    price_str = f"${price_usd:.4f}"
    options = build_payment_options(pay_to_evm, pay_to_sol, price_str)

    if not options:
        raise HTTPException(
            status_code=503,
            detail="No payment wallets configured. Agent must set a wallet address.",
        )

    payment_required = {
        "accepts": options,
        "description": description,
        "resource": resource,
        "scheme": "exact",
        "mimeType": "application/json",
    }

    split = calculate_fee_split(price_usd)

    response = JSONResponse(
        status_code=402,
        content={
            "error": "payment_required",
            "message": f"Payment of ${price_usd:.2f} USDC required: {description}",
            "payment_options": options,
            "description": description,
            "fee_breakdown": {
                "total": f"${split['gross']:.2f}",
                "creator_receives": f"${split['creator']:.2f}",
                "platform_fee": f"${split['fee']:.2f}",
                "fee_rate": f"{split['rate'] * 100:.0f}%",
            },
        },
    )
    response.headers["PAYMENT-REQUIRED"] = json.dumps(payment_required)
    return response


async def verify_payment(request: Request, expected_amount: float) -> Optional[Dict[str, Any]]:
    """
    Verify a payment signature from the PAYMENT-SIGNATURE header
    via the x402 facilitator's /verify endpoint.

    Returns the verification result dict if valid, None if no payment header present.
    Raises HTTPException if payment is invalid.
    """
    payment_sig = request.headers.get("PAYMENT-SIGNATURE") or request.headers.get("payment-signature")
    if not payment_sig:
        return None

    facilitator_url = get_facilitator_url()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{facilitator_url}/verify",
                json={
                    "payment": payment_sig,
                    "expected_amount": f"${expected_amount:.4f}",
                },
                headers={"Content-Type": "application/json"},
            )

            if resp.status_code == 200:
                return resp.json()
            else:
                raise HTTPException(
                    status_code=402,
                    detail=f"Payment verification failed: {resp.text}",
                )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Could not reach payment facilitator: {str(e)}",
        )


async def settle_payment(payment_signature: str) -> Optional[Dict[str, Any]]:
    """
    Settle a verified payment via the facilitator's /settle endpoint.
    This triggers the actual blockchain transaction.
    """
    facilitator_url = get_facilitator_url()

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{facilitator_url}/settle",
                json={"payment": payment_signature},
                headers={"Content-Type": "application/json"},
            )

            if resp.status_code == 200:
                return resp.json()
            else:
                return {"status": "settlement_pending", "raw": resp.text}
    except httpx.RequestError:
        return {"status": "settlement_pending", "note": "Facilitator unreachable, settlement will retry"}


async def require_payment(
    request: Request,
    pay_to_evm: str,
    pay_to_sol: str,
    amount_usd: float,
    description: str,
    resource: str,
) -> Dict[str, Any]:
    """
    Check for x402 payment on a request. If no payment header is present,
    returns a 402 response. If payment is present, verifies and settles it.

    Usage in a route handler:
        payment = await require_payment(request, wallet_evm, wallet_sol, 9.99, "Premium sub", "/api/subscriptions")
        # If we get here, payment was verified. 'payment' contains settlement info.
    """
    # Check for payment signature
    payment_sig = request.headers.get("PAYMENT-SIGNATURE") or request.headers.get("payment-signature")

    if not payment_sig:
        # No payment provided - return 402
        raise HTTPException(
            status_code=402,
            detail="Payment required",
            headers={
                "PAYMENT-REQUIRED": json.dumps({
                    "accepts": build_payment_options(pay_to_evm, pay_to_sol, f"${amount_usd:.4f}"),
                    "description": description,
                    "resource": resource,
                    "scheme": "exact",
                    "mimeType": "application/json",
                })
            },
        )

    # Verify payment
    verification = await verify_payment(request, amount_usd)

    if not verification:
        raise HTTPException(status_code=402, detail="Payment verification failed")

    # Settle payment
    settlement = await settle_payment(payment_sig)

    return {
        "verified": True,
        "verification": verification,
        "settlement": settlement,
        "fee_split": calculate_fee_split(amount_usd),
    }
