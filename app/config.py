import os
from dotenv import load_dotenv

load_dotenv()

# x402 Payment Configuration
X402_PAY_TO_EVM = os.getenv("X402_PAY_TO_EVM", "")
X402_PAY_TO_SOL = os.getenv("X402_PAY_TO_SOL", "")
X402_NETWORK = os.getenv("X402_NETWORK", "testnet")

# Platform fee configuration
PLATFORM_FEE_RATE = float(os.getenv("PLATFORM_FEE_RATE", "0.05"))  # 5%
PLATFORM_WALLET_EVM = os.getenv("PLATFORM_WALLET_EVM", "0x7973dE05473e56A2B3Fa6c33736cb8932E7Aa332")
PLATFORM_WALLET_SOL = os.getenv("PLATFORM_WALLET_SOL", "45LnbLrLpKSCXUQUcC2MBJU9EKcHVvKiy17YT7riVoLm")
PLATFORM_ADMIN_KEY = os.getenv("PLATFORM_ADMIN_KEY", "")

# Facilitator URLs
FACILITATOR_URLS = {
    "testnet": "https://x402.org/facilitator",
    "mainnet": "https://api.cdp.coinbase.com/platform/v2/x402",
}

# Network CAIP-2 identifiers
NETWORKS = {
    "testnet": {
        "evm": "eip155:84532",      # Base Sepolia
        "solana": "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1",  # Solana Devnet
    },
    "mainnet": {
        "evm": "eip155:8453",       # Base Mainnet
        "solana": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",  # Solana Mainnet
    },
}

# CDP API credentials (for mainnet facilitator)
CDP_API_KEY_ID = os.getenv("CDP_API_KEY_ID", "")
CDP_API_KEY_SECRET = os.getenv("CDP_API_KEY_SECRET", "")


def get_facilitator_url():
    return FACILITATOR_URLS.get(X402_NETWORK, FACILITATOR_URLS["testnet"])


def get_network_id(chain: str = "evm"):
    env = X402_NETWORK if X402_NETWORK in NETWORKS else "testnet"
    return NETWORKS[env].get(chain, NETWORKS[env]["evm"])
