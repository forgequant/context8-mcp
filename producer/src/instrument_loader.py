"""Custom instrument loader for Binance public data without API keys."""
import httpx
from decimal import Decimal
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.currencies import Currency
from nautilus_trader.model.objects import Price, Quantity, Money
import structlog

log = structlog.get_logger()


def load_binance_spot_instruments(symbols: list[str]) -> dict[InstrumentId, CurrencyPair]:
    """
    Load Binance spot instruments from public API without authentication.

    Uses /api/v3/exchangeInfo endpoint which doesn't require API keys.

    Args:
        symbols: List of symbol strings (e.g., ["BTCUSDT", "ETHUSDT"])

    Returns:
        Dictionary mapping InstrumentId to CurrencySpot instrument
    """
    instruments = {}

    try:
        # Fetch exchange info from Binance public API (no auth required)
        url = "https://api.binance.com/api/v3/exchangeInfo"

        log.info(f"Fetching instrument data from Binance public API for symbols: {symbols}")

        with httpx.Client(timeout=10.0) as client:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()

        # Filter for requested symbols
        symbol_set = set(symbols)

        for symbol_data in data.get("symbols", []):
            symbol_str = symbol_data.get("symbol")

            if symbol_str not in symbol_set:
                continue

            if symbol_data.get("status") != "TRADING":
                log.warning(f"Symbol {symbol_str} is not in TRADING status, skipping")
                continue

            # Extract instrument parameters
            base_asset = symbol_data.get("baseAsset")
            quote_asset = symbol_data.get("quoteAsset")

            # Parse filters for price/quantity precision
            price_precision = 8  # default
            size_precision = 8   # default
            min_quantity = None
            max_quantity = None
            min_notional = None

            for f in symbol_data.get("filters", []):
                filter_type = f.get("filterType")

                if filter_type == "PRICE_FILTER":
                    tick_size = f.get("tickSize", "0.00000001")
                    # Calculate precision from tick size
                    price_precision = len(tick_size.rstrip('0').split('.')[-1]) if '.' in tick_size else 0

                elif filter_type == "LOT_SIZE":
                    step_size = f.get("stepSize", "0.00000001")
                    size_precision = len(step_size.rstrip('0').split('.')[-1]) if '.' in step_size else 0
                    min_quantity = Decimal(f.get("minQty", "0"))
                    max_quantity = Decimal(f.get("maxQty", "1000000"))

                elif filter_type == "MIN_NOTIONAL":
                    min_notional = Decimal(f.get("minNotional", "0"))

            # Create instrument
            instrument_id = InstrumentId(
                symbol=Symbol(symbol_str),
                venue=Venue("BINANCE")
            )

            base_currency = Currency.from_str(base_asset)
            quote_currency = Currency.from_str(quote_asset)

            instrument = CurrencyPair(
                instrument_id=instrument_id,
                raw_symbol=Symbol(symbol_str),
                base_currency=base_currency,
                quote_currency=quote_currency,
                price_precision=price_precision,
                size_precision=size_precision,
                price_increment=Price.from_str(f"1e-{price_precision}"),
                size_increment=Quantity.from_str(f"1e-{size_precision}"),
                margin_init=Decimal("0"),  # Spot has no margin
                margin_maint=Decimal("0"),
                maker_fee=Decimal("0.001"),  # Default Binance spot fee (0.1%)
                taker_fee=Decimal("0.001"),
                ts_event=0,
                ts_init=0,
                min_quantity=Quantity.from_str(str(min_quantity)) if min_quantity else None,
                max_quantity=Quantity.from_str(str(max_quantity)) if max_quantity else None,
                min_notional=Money.from_str(f"{min_notional} {quote_asset}") if min_notional else None,
                max_notional=None,
            )

            instruments[instrument_id] = instrument
            log.info(f"Loaded instrument: {instrument_id}")

        if not instruments:
            log.error(f"No instruments loaded for symbols: {symbols}. Check symbol names.")
        else:
            log.info(f"Successfully loaded {len(instruments)} instruments")

        return instruments

    except Exception as e:
        log.error(f"Failed to load Binance instruments: {type(e).__name__} - {e}")
        return {}
