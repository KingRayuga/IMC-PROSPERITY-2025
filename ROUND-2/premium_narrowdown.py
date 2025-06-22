import json
import statistics
from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List

POSITION_LIMITS = {
    "RAINFOREST_RESIN": 50,
    "KELP": 50,
    "CROISSANTS": 250,
    "PICNIC_BASKET1": 60,
    "PICNIC_BASKET2": 100
}

COMPONENTS = {
    "PICNIC_BASKET1": {"CROISSANTS": 6, "JAMS": 3, "DJEMBES": 1},
    "PICNIC_BASKET2": {"CROISSANTS": 4, "JAMS": 2}
}

class Trader:
    def __init__(self):

        self.croissant_history = []
        self.croissant_window = 100
        self.std_threshold = 1.5
        self.max_trade_size = 10

        self.trader_data = {
            "spread_history": {
                "PICNIC_BASKET1": [],
                "PICNIC_BASKET2": []
            },
            "last_timestamp": 0,
            "open_positions": {},
            "price_history": {}  
        }
        
        self.dynamic_params = {
            "PICNIC_BASKET1": {
                "buffer_multiplier": 2.2,
                "min_buffer": 2.0,
                "max_buffer": 10.0,
                "current_buffer": 3.0
            },
            "PICNIC_BASKET2": {
                "buffer_multiplier": 2.0,
                "min_buffer": 1.5,
                "max_buffer": 8.0,
                "current_buffer": 2.0
            }
        }
        self.MIN_TRADE_SIZE = 3
        self.MAX_TRADE_VOLUME = 5
        self.PROFIT_TARGET = 1.5

    def update_croissant_history(self, current_price: float):
        """Maintain rolling window for CROISSANTS"""
        self.croissant_history.append(current_price)
        if len(self.croissant_history) > self.croissant_window:
            self.croissant_history.pop(0)

    def calculate_z_score(self, current_price: float) -> float:
        """Calculate z-score for CROISSANTS"""
        if len(self.croissant_history) < self.croissant_window:
            return 0
        mean = statistics.mean(self.croissant_history)
        std_dev = statistics.stdev(self.croissant_history) if len(self.croissant_history) > 1 else 0
        return (current_price - mean) / std_dev if std_dev != 0 else 0

    def calculate_spread_stats(self, order_depth: OrderDepth):
        """Calculate spread for PICNIC_BASKETs"""
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return None
        return min(order_depth.sell_orders.keys()) - max(order_depth.buy_orders.keys())

    def calculate_liquidity(self, order_depth: OrderDepth):
        """Calculate liquidity for PICNIC_BASKETs"""
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return 0
        return min(
            max(order_depth.buy_orders.values()),
            abs(min(order_depth.sell_orders.values()))
        )

    def update_dynamic_buffers(self, product: str, current_spread: float):
        """Adjust buffers for PICNIC_BASKETs"""
        history = self.trader_data["spread_history"][product]
        history.append(current_spread)
        if len(history) > 20:
            history.pop(0)
        
        if len(history) >= 5:
            median_spread = statistics.median(history)
            params = self.dynamic_params[product]
            self.dynamic_params[product]["current_buffer"] = max(
                params["min_buffer"],
                min(params["max_buffer"], 
                    median_spread * params["buffer_multiplier"])
            )

    def calculate_fair_value(self, components, state):
        """VWAP-based fair value for PICNIC_BASKETs"""
        total = 0
        for comp, qty in components.items():
            depth = state.order_depths.get(comp, None)
            if not depth or not depth.buy_orders or not depth.sell_orders:
                return None
            bid_vwap = sum(p*v for p,v in depth.buy_orders.items())/sum(depth.buy_orders.values())
            ask_vwap = sum(p*abs(v) for p,v in depth.sell_orders.items())/sum(abs(v) for v in depth.sell_orders.values())
            total += qty * (bid_vwap + ask_vwap)/2
        return total

    def run(self, state: TradingState):
        result = {}
        conversions = 0
        max_history = 5  

        # Load trader data
        if state.traderData:
            try:
                loaded_data = json.loads(state.traderData)
                for key in loaded_data:
                    if key in self.trader_data:
                        if isinstance(self.trader_data[key], dict):
                            self.trader_data[key].update(loaded_data[key])
                        else:
                            self.trader_data[key] = loaded_data[key]
            except:
                pass

        for product in state.order_depths:
            if product not in POSITION_LIMITS:
                continue  

            order_depth = state.order_depths[product]
            position_limit = POSITION_LIMITS[product]
            current_position = state.position.get(product, 0)
            orders = []

            # Skip if no market data
            if not order_depth.buy_orders or not order_depth.sell_orders:
                result[product] = []
                continue

            best_bid = max(order_depth.buy_orders.keys())
            best_ask = min(order_depth.sell_orders.keys())
            mid_price = (best_bid + best_ask) / 2

            # RAINFOREST_RESIN and KELP strategy (simple mean reversion)
            if product in ["RAINFOREST_RESIN", "KELP"]:
                Update price history
                if product not in self.trader_data["price_history"]:
                    self.trader_data["price_history"][product] = []
                self.trader_data["price_history"][product].append(mid_price)
                if len(self.trader_data["price_history"][product]) > max_history:
                    self.trader_data["price_history"][product] = self.trader_data["price_history"][product][-max_history:]
                
                # Calculate fair price as moving average
                history = self.trader_data["price_history"].get(product, [mid_price])
                fair_price = sum(history) / len(history)

                # BUY if price is below fair value
                for ask_price in sorted(order_depth.sell_orders.keys()):
                    ask_volume = order_depth.sell_orders[ask_price]
                    if ask_price < fair_price and current_position < position_limit:
                        volume = min(-ask_volume, position_limit - current_position)
                        orders.append(Order(product, ask_price, volume))
                        current_position += volume

                # SELL if price is above fair value
                for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
                    bid_volume = order_depth.buy_orders[bid_price]
                    if bid_price > fair_price and current_position > -position_limit:
                        volume = min(bid_volume, current_position + position_limit)
                        orders.append(Order(product, bid_price, -volume))
                        current_position -= volume

            # CROISSANTS strategy (z-score mean reversion)
            elif product == "CROISSANTS":
                self.update_croissant_history(mid_price)
                z_score = self.calculate_z_score(mid_price)

                # Mean reversion trading
                if z_score > self.std_threshold:  # Overbought - sell
                    sell_volume = min(
                        self.max_trade_size,
                        position_limit + current_position
                    )
                    if sell_volume > 0:
                        orders.append(Order(product, best_bid, -sell_volume))

                elif z_score < -self.std_threshold:  # Oversold - buy
                    buy_volume = min(
                        self.max_trade_size,
                        position_limit - current_position
                    )
                    if buy_volume > 0:
                        orders.append(Order(product, best_ask, buy_volume))

            result[product] = orders

        self.trader_data["last_timestamp"] = state.timestamp
        return result, conversions, json.dumps(self.trader_data)
