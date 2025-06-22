import json
from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List


class Trader:
    def run(self, state: TradingState):
        result = {}
        conversions = 0
        max_history = 5  # moving average window

        # Load historical price data from traderData
        if state.traderData:
            price_history = json.loads(state.traderData)
        else:
            price_history = {}

        position_limits = {
            "RAINFOREST_RESIN": 50,
            "KELP": 50,
            "SQUID_INK": 50,  # included in tracking, not in trading
        }

        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            position_limit = position_limits[product]
            current_position = state.position.get(product, 0)

            orders: List[Order] = []

            # Get best bid/ask for mid-price calc
            best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None
            best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else None

            mid_price = None
            if best_ask is not None and best_bid is not None:
                mid_price = (best_ask + best_bid) / 2

                # Update price history
                if product not in price_history:
                    price_history[product] = []
                price_history[product].append(mid_price)
                if len(price_history[product]) > max_history:
                    price_history[product] = price_history[product][-max_history:]
            else:
                # fallback if no bid/ask data
                mid_price = 10000 if product == "RAINFOREST_RESIN" else 1000

            # Calculate fair price as moving average
            history = price_history.get(product, [mid_price])
            fair_price = sum(history) / len(history)

            # Skip trading logic for SQUID_INK
            if product == "SQUID_INK":
                result[product] = []
                continue

            # BUY
            for ask_price in sorted(order_depth.sell_orders.keys()):
                ask_volume = order_depth.sell_orders[ask_price]
                if ask_price < fair_price and current_position < position_limit:
                    volume = min(-ask_volume, position_limit - current_position)
                    orders.append(Order(product, ask_price, volume))
                    current_position += volume

            # SELL
            for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
                bid_volume = order_depth.buy_orders[bid_price]
                if bid_price > fair_price and current_position > -position_limit:
                    volume = min(bid_volume, current_position + position_limit)
                    orders.append(Order(product, bid_price, -volume))
                    current_position -= volume

            result[product] = orders

        # Save updated price history to traderData
        traderData = json.dumps(price_history)

        return result, conversions, traderData
