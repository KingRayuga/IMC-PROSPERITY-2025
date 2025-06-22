from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Tuple
import json
import statistics

class Trader:
    def __init__(self):

        self.vr_max_short = 200  
        self.vr_price = 10500  
        self.vr_last_prices = []  
        
        self.pb_position_limits = {
            "RAINFOREST_RESIN": 50,
            "KELP": 50,
            "CROISSANTS": 250,
            "PICNIC_BASKET1": 60,
            "PICNIC_BASKET2": 100
        }
        

        self.pb_components = {
            "PICNIC_BASKET1": {"CROISSANTS": 6, "JAMS": 3, "DJEMBES": 1},
            "PICNIC_BASKET2": {"CROISSANTS": 4, "JAMS": 2}
        }
        

        self.pb_croissant_history = []
        self.pb_croissant_window = 100
        self.pb_std_threshold = 1.5
        self.pb_max_trade_size = 10
        
        self.pb_dynamic_params = {
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
        
        self.trader_data = {
            "last_timestamp": 0,
            "price_history": {},
            "spread_history": {
                "PICNIC_BASKET1": [],
                "PICNIC_BASKET2": []
            }
        }

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result = {}
        conversions = 0
        
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

        self.vr_update_market_data(state)
        for product in state.order_depths:
            if product.startswith('VOLCANIC_ROCK_VOUCHER'):
                orders = self.vr_short_itm_voucher(product, state)
                if orders:
                    result[product] = orders


        for product in state.order_depths:
            if product in self.pb_position_limits:
                orders = self.pb_process_product(product, state)
                if orders:
                    result[product] = orders


        self.trader_data["last_timestamp"] = state.timestamp
        trader_data_str = json.dumps(self.trader_data)
        
        return result, conversions, trader_data_str

    def vr_update_market_data(self, state: TradingState):
        """Update VR market data"""
        if 'VOLCANIC_ROCK' in state.order_depths:
            bids = state.order_depths['VOLCANIC_ROCK'].buy_orders
            asks = state.order_depths['VOLCANIC_ROCK'].sell_orders
            if bids and asks:
                self.vr_price = (max(bids.keys()) + min(asks.keys())) / 2
                self.vr_last_prices.append(self.vr_price)
                if len(self.vr_last_prices) > 20:
                    self.vr_last_prices.pop(0)

    def vr_short_itm_voucher(self, product: str, state: TradingState) -> List[Order]:
        """Generate short orders for ITM vouchers"""
        strike = int(product.split('_')[-1])
        if self.vr_price <= strike:
            return []
            
        current_pos = state.position.get(product, 0)
        short_capacity = self.vr_max_short + current_pos
        if short_capacity <= 0:
            return []
            
        quantity = min(10, short_capacity)
        intrinsic = self.vr_price - strike
        price = int(intrinsic * 0.95) 
        
        return [Order(product, price, -quantity)]

    # --- Picnic Basket Strategy Methods ---
    def pb_process_product(self, product: str, state: TradingState) -> List[Order]:
        """Process Picnic Basket strategy products"""
        order_depth = state.order_depths[product]
        position_limit = self.pb_position_limits[product]
        current_position = state.position.get(product, 0)
        orders = []

        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders

        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        mid_price = (best_bid + best_ask) / 2

        # RAINFOREST_RESIN and KELP strategy
        if product in ["RAINFOREST_RESIN", "KELP"]:
            if product not in self.trader_data["price_history"]:
                self.trader_data["price_history"][product] = []
            self.trader_data["price_history"][product].append(mid_price)
            if len(self.trader_data["price_history"][product]) > 5:
                self.trader_data["price_history"][product] = self.trader_data["price_history"][product][-5:]
            
            fair_price = sum(self.trader_data["price_history"][product]) / len(self.trader_data["price_history"][product])

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

        # CROISSANTS strategy
        elif product == "CROISSANTS":
            self.pb_update_croissant_history(mid_price)
            z_score = self.pb_calculate_z_score(mid_price)

            if z_score > self.pb_std_threshold:  # Overbought - sell
                sell_volume = min(
                    self.pb_max_trade_size,
                    position_limit + current_position
                )
                if sell_volume > 0:
                    orders.append(Order(product, best_bid, -sell_volume))

            elif z_score < -self.pb_std_threshold:  # Oversold - buy
                buy_volume = min(
                    self.pb_max_trade_size,
                    position_limit - current_position
                )
                if buy_volume > 0:
                    orders.append(Order(product, best_ask, buy_volume))

        return orders

    def pb_update_croissant_history(self, current_price: float):
        """Maintain rolling window for CROISSANTS"""
        self.pb_croissant_history.append(current_price)
        if len(self.pb_croissant_history) > self.pb_croissant_window:
            self.pb_croissant_history.pop(0)

    def pb_calculate_z_score(self, current_price: float) -> float:
        """Calculate z-score for CROISSANTS"""
        if len(self.pb_croissant_history) < self.pb_croissant_window:
            return 0
        mean = statistics.mean(self.pb_croissant_history)
        std_dev = statistics.stdev(self.pb_croissant_history) if len(self.pb_croissant_history) > 1 else 0
        return (current_price - mean) / std_dev if std_dev != 0 else 0
