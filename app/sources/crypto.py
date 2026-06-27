"""
Cripto: valoración EN VIVO de tus holdings con CoinGecko (gratis, sin API key).

Introduces tus tenencias (cantidad + moneda) y se valoran al precio actual.
Ej.:  "0.5 BTC", "2 ETH", "100 ADA"  →  valor en € de cada una y total.
"""

from . import http
from .common import Position

SOURCE = "Cripto"
CATEGORY = "Cripto"

# Símbolo -> id de CoinGecko (las más comunes). Si no está, se usa lo escrito
# como id directamente (puedes poner el id de CoinGecko: 'bitcoin', 'nexo'…).
COIN_IDS = {
    "btc": "bitcoin", "eth": "ethereum", "sol": "solana", "usdt": "tether",
    "usdc": "usd-coin", "bnb": "binancecoin", "xrp": "ripple", "ada": "cardano",
    "doge": "dogecoin", "dot": "polkadot", "matic": "matic-network", "ltc": "litecoin",
    "link": "chainlink", "avax": "avalanche-2", "atom": "cosmos", "near": "near",
    "trx": "tron", "shib": "shiba-inu", "uni": "uniswap", "xlm": "stellar",
    "algo": "algorand", "vet": "vechain", "ftm": "fantom", "sand": "the-sandbox",
    "mana": "decentraland", "aave": "aave", "grt": "the-graph", "xmr": "monero",
    "bch": "bitcoin-cash", "etc": "ethereum-classic", "fil": "filecoin",
    "icp": "internet-computer", "ape": "apecoin", "arb": "arbitrum", "op": "optimism",
    "inj": "injective-protocol", "sui": "sui", "sei": "sei-network", "pepe": "pepe",
    "nexo": "nexo", "ton": "the-open-network", "cro": "crypto-com-chain",
}


def parse_holdings(text):
    """Convierte texto libre en una lista de {amount, coin}. Acepta '0.5 BTC',
    'BTC 0.5', con coma o punto decimal, una por línea."""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        amount, coin = None, None
        for tok in line.replace(",", ".").split():
            try:
                amount = float(tok)
            except ValueError:
                coin = tok
        if amount is not None and coin:
            out.append({"amount": amount, "coin": coin.lower()})
    return out


def _prices(ids, vs="eur"):
    if not ids:
        return {}
    url = ("https://api.coingecko.com/api/v3/simple/price?ids="
           + ",".join(sorted(ids)) + "&vs_currencies=" + vs)
    status, data = http.get_json(url)
    return data if status == 200 and data else {}


def analyze(holdings, currency="eur"):
    cur = currency.lower()
    resolved = [(h, COIN_IDS.get(h["coin"], h["coin"])) for h in holdings]
    prices = _prices({cid for _, cid in resolved}, cur)
    positions, warnings = [], []
    for h, cid in resolved:
        unit = prices.get(cid, {}).get(cur)
        if unit is None:
            warnings.append(f"Sin precio para «{h['coin'].upper()}» (id CoinGecko '{cid}').")
            unit = 0.0
        positions.append(Position(
            source=SOURCE, category=CATEGORY, name=h["coin"].upper(),
            quantity=h["amount"], unit_value=unit, value=round(unit * h["amount"], 2),
            currency=currency.upper(), extra={"tag": cid},
        ).finalize())
    total = round(sum(p.value for p in positions), 2)
    return {"source": SOURCE, "category": CATEGORY,
            "positions": [p.to_dict() for p in positions],
            "total": total, "currency": currency.upper(), "warnings": warnings}
