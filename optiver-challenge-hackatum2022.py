import logging
import time
from optibook import ORDER_TYPE_IOC, ORDER_TYPE_LIMIT, SIDE_ASK, SIDE_BID
from optibook.exchange_responses import InsertOrderResponse
from optibook.synchronous_client import Exchange
import threading

logging.getLogger('client').setLevel('ERROR')
logger = logging.getLogger(__name__)

MAX_POSITIONS = 500 # Maximum number of positions per instrument
UNDER_BIDDING = 0.0
OVER_ASKING = 0.0
MAX_NEGATIVE_PROFIT = 1000 # Limit trades with negative profit (usually required to rebalance positions)
MAX_DIFF = 0

ORDER_VOLUME = 1
MARKET_MAKER_MARGIN = 0.1

total_pnl = 0
hits = 0
lifts = 0
running = True # Variable used to stop running threads on keyboard interrupt

    
def sgn(i):
    """ Return sign of input argument, if argument is zero then return zero """
    if i > 0:
        return 1
    elif i == 0:
        return 0
    return -1
    

def trade_cycle(e: Exchange, instrument_ids: list):
    order_responses: InsertOrderResponse = []
    
    """ Get current positions """
    positions = e.get_positions()
    basket_pos = positions[instrument_ids[0]]
    instrument_1_pos = positions[instrument_ids[1]]
    instrument_2_pos = positions[instrument_ids[2]]
    
    """ Get current price books """
    basket_book = e.get_last_price_book(instrument_ids[0])
    instrument_1_book = e.get_last_price_book(instrument_ids[1])
    instrument_2_book = e.get_last_price_book(instrument_ids[2])
    
    
    #debug = '' # String for debug purposes
    
    """ CASE 1: Basket is overvalued. i.e. we sell the basket, buy the stocks """
    if instrument_1_book.asks and instrument_2_book.asks and basket_book.bids:
        lowest_ask_instrument_1 = instrument_1_book.asks[0]
        lowest_ask_instrument_2 = instrument_2_book.asks[0]
        highest_bid_basket = basket_book.bids[0]
        true_basket_price = lowest_ask_instrument_1.price * 0.5 + lowest_ask_instrument_2.price * 0.5 # Calculate current market price of basket components
        
        if highest_bid_basket.price > true_basket_price:
            """ Get maximum potential volumes """
            basket_volume = highest_bid_basket.volume
            if abs(basket_pos - highest_bid_basket.volume) > MAX_POSITIONS:
                basket_volume -= abs(basket_pos - highest_bid_basket.volume) - MAX_POSITIONS
            instrument_1_volume = lowest_ask_instrument_1.volume
            if abs(instrument_1_pos + lowest_ask_instrument_1.volume) > MAX_POSITIONS:
                instrument_1_volume -= abs(instrument_1_pos + lowest_ask_instrument_1.volume) - MAX_POSITIONS
            instrument_2_volume = lowest_ask_instrument_2.volume
            if abs(instrument_2_pos + lowest_ask_instrument_2.volume) > MAX_POSITIONS:
                instrument_2_volume -= abs(instrument_2_pos + lowest_ask_instrument_2.volume) - MAX_POSITIONS
            #debug += f'1.1 {basket_volume} {instrument_1_volume} {instrument_2_volume}\n'
            
            if (instrument_ids[0] == 'C2_GREEN_ENERGY_ETF'):
                basket_volume = 0
            
            """ Calculate potential positions """
            potential_basket_pos = basket_pos - basket_volume
            potential_instrument_1_pos = instrument_1_pos + instrument_1_volume
            potential_instrument_2_pos = instrument_2_pos + instrument_2_volume
            
            """ Balance potential positons of instrument 1 vs. instrument 2 by reducing instrument 1 volume or instrument 2 volume """
            if abs(potential_instrument_1_pos - potential_instrument_2_pos) > 0:
                difference = abs(potential_instrument_1_pos - potential_instrument_2_pos)
                instrument_1_volume = max(0, instrument_1_volume - difference)
                potential_instrument_1_pos = instrument_1_pos + instrument_1_volume
            elif abs(potential_instrument_2_pos - potential_instrument_1_pos) > 0:
                difference = abs(potential_instrument_2_pos - potential_instrument_1_pos)
                instrument_2_volume = max(0, instrument_2_volume - difference)
                potential_instrument_2_pos = instrument_2_pos + instrument_2_volume
            #debug += f'1.2 {basket_volume} {instrument_1_volume} {instrument_2_volume} {sgn(potential_basket_pos) != sgn(potential_instrument_1_pos)} {potential_basket_pos} {potential_instrument_1_pos} {potential_instrument_2_pos}\n'
            
            """ Balance potential positions of potential positions for basket vs. potential positions of instrument 1 and instrument 2 """
            if sgn(potential_basket_pos) != sgn(potential_instrument_1_pos): # case examples: 200, -80, -80 / 100, -60, -60 / -110, 50, 50
                if abs(potential_basket_pos) > abs(potential_instrument_1_pos + potential_instrument_2_pos) and sgn(potential_basket_pos) < 0:
                    difference = abs(potential_basket_pos) - (abs(potential_instrument_1_pos) + abs(potential_instrument_2_pos))
                    basket_volume = max(0, basket_volume - difference)
                elif abs(potential_basket_pos) > abs(potential_instrument_1_pos + potential_instrument_2_pos) and sgn(potential_basket_pos) > 0:
                    difference = abs(potential_basket_pos) - abs(potential_instrument_1_pos - potential_instrument_2_pos)
                    instrument_1_volume = max(0, instrument_1_volume - difference // 2)
                    instrument_2_volume = max(0, instrument_2_volume - difference // 2)
                elif abs(potential_basket_pos) < abs(potential_instrument_1_pos + potential_instrument_2_pos) and sgn(potential_basket_pos) > 0:
                    difference = (abs(potential_instrument_1_pos) + abs(potential_instrument_2_pos)) - abs(potential_basket_pos)
                    basket_volume = max(0, basket_volume - difference)
                elif abs(potential_basket_pos) < abs(potential_instrument_1_pos + potential_instrument_2_pos) and sgn(potential_basket_pos) < 0:
                    difference = abs(potential_instrument_1_pos) + abs(potential_instrument_2_pos) - abs(potential_basket_pos)
                    instrument_1_volume = max(0, instrument_1_volume - difference // 2)
                    instrument_2_volume = max(0, instrument_2_volume - difference // 2)
            else: # case examples:  200, 10, 10 / 50, 30, 30 / -200, -10, -10
                if sgn(potential_basket_pos) == 1:
                    difference = abs(potential_instrument_1_pos) + abs(potential_instrument_2_pos) + abs(potential_basket_pos)
                    instrument_1_volume = max(0, instrument_1_volume - difference // 2)
                    instrument_2_volume = max(0, instrument_2_volume - difference // 2)
                elif sgn(potential_basket_pos) == -1:
                    difference = abs(potential_basket_pos) + (abs(potential_instrument_1_pos) + abs(potential_instrument_2_pos))
                    basket_volume = max(0, basket_volume - difference)
            #debug += f'1.3 {basket_volume} {instrument_1_volume} {instrument_2_volume}'
            
            """ Calculate profit """
            profit = (highest_bid_basket.price - OVER_ASKING) * basket_volume
            profit -= (lowest_ask_instrument_1.price - UNDER_BIDDING) * instrument_1_volume
            profit -= (lowest_ask_instrument_2.price - UNDER_BIDDING) * instrument_2_volume
            
            """ Execute trades if their volume is larger than zero and profit is large enough """
            if profit > -MAX_NEGATIVE_PROFIT:
                if basket_volume > 0 or instrument_1_volume > 0 or instrument_2_volume > 0:
                    logger.info(f'Try to sell {basket_volume} of {instrument_ids[0]} and buy {instrument_1_volume} of {instrument_ids[1]} and {instrument_2_volume} of {instrument_ids[2]} with a price delta of {profit:.2f}')
                if instrument_2_volume > 0:
                    order_responses.append(e.insert_order(
                        instrument_ids[2], price=lowest_ask_instrument_2.price + UNDER_BIDDING,
                        volume=instrument_2_volume, side=SIDE_BID, order_type=ORDER_TYPE_IOC))
                if basket_volume > 0:
                    if (instrument_ids[0] == 'C2_GREEN_ENERGY_ETF'):
                        pass
                        """outstanding_orders = e.get_outstanding_orders(instrument_ids[0])
                        print(outstanding_orders)
                        own_order = sum(map(lambda x: x.side == SIDE_BID, outstanding_orders.values()))
                        if own_order == 0:
                            order_responses.append(e.insert_order(
                                instrument_ids[0], price=highest_bid_basket.price - OVER_ASKING,
                                volume=basket_volume, side=SIDE_ASK, order_type=ORDER_TYPE_IOC))"""
                    else:
                        order_responses.append(e.insert_order(
                            instrument_ids[0], price=highest_bid_basket.price - OVER_ASKING,
                            volume=basket_volume, side=SIDE_ASK, order_type=ORDER_TYPE_IOC))
                if instrument_1_volume > 0:
                    order_responses.append(e.insert_order(
                        instrument_ids[1], price=lowest_ask_instrument_1.price + UNDER_BIDDING,
                        volume=instrument_1_volume, side=SIDE_BID, order_type=ORDER_TYPE_IOC))
            
            
    """ CASE 2: Basket is undervalued. i.e. we buy the basket, sell the stocks. """
    if instrument_1_book.bids and instrument_2_book.bids and basket_book.asks:
        highest_bid_instrument_1 = instrument_1_book.bids[0]
        highest_bid_instrument_2 = instrument_2_book.bids[0]
        lowest_ask_basket = basket_book.asks[0]
        true_basket_price = highest_bid_instrument_1.price * 0.5 + highest_bid_instrument_2.price * 0.5 # Calculate current market price of basket components
        
        if lowest_ask_basket.price < true_basket_price:
            # Get maximum potential volumes
            basket_volume = lowest_ask_basket.volume
            if abs(basket_pos + lowest_ask_basket.volume) > MAX_POSITIONS:
                basket_volume -= abs(basket_pos + lowest_ask_basket.volume) - MAX_POSITIONS
            instrument_1_volume = highest_bid_instrument_1.volume
            if abs(instrument_1_pos - highest_bid_instrument_1.volume) > MAX_POSITIONS:
                instrument_1_volume -= abs(instrument_1_pos - highest_bid_instrument_1.volume) - MAX_POSITIONS
            instrument_2_volume = highest_bid_instrument_2.volume
            if abs(instrument_2_pos - highest_bid_instrument_2.volume) > MAX_POSITIONS:
                instrument_2_pos -= abs(instrument_2_pos - highest_bid_instrument_2.volume) - MAX_POSITIONS
            #debug += f'2.1 {basket_volume} {instrument_1_volume} {instrument_2_volume}\n'
            
            if (instrument_ids[0] == 'C2_GREEN_ENERGY_ETF'):
                basket_volume = 0
            
            """ Calculate potential positions """
            potential_basket_pos = basket_pos + basket_volume # we buy the basket
            potential_instrument_1_pos = instrument_1_pos - instrument_1_volume # we sell the instrument
            potential_instrument_2_pos = instrument_2_pos - instrument_2_volume # we sell the instrument
            
            """ Balance potential positons of instrument 1 vs. instrument 2 by reducing instrument 1 volume or instrument 2 volume """
            if abs(potential_instrument_1_pos - potential_instrument_2_pos) > 0:
                difference = abs(potential_instrument_1_pos - potential_instrument_2_pos)
                instrument_1_volume = max(0, instrument_1_volume - difference)
                potential_instrument_1_pos = instrument_1_pos - instrument_1_volume
            elif abs(potential_instrument_2_pos - potential_instrument_1_pos) > 0:
                difference = abs(potential_instrument_2_pos - potential_instrument_1_pos)
                instrument_2_volume = max(0, instrument_2_volume - difference)
                potential_instrument_2_pos = instrument_2_pos - instrument_2_volume
            #debug += f'2.1 {basket_volume} {instrument_1_volume} {instrument_2_volume} {sgn(potential_basket_pos) != sgn(potential_instrument_1_pos)} {potential_basket_pos} {potential_instrument_1_pos} {potential_instrument_2_pos}\n'
            
            """ Balance potential positions of potential positions for basket vs. potential positions of instrument 1 and instrument 2 """
            if sgn(potential_basket_pos) != sgn(potential_instrument_1_pos): # case examples: 200, -80, -80 /100, -60, -60 / -110, 50, 50
                if abs(potential_basket_pos) > abs(potential_instrument_1_pos + potential_instrument_2_pos) and sgn(potential_basket_pos) > 0:
                    difference = abs(potential_basket_pos) - (abs(potential_instrument_1_pos) + abs(potential_instrument_2_pos))
                    basket_volume = max(0, basket_volume - difference)
                elif abs(potential_basket_pos) > abs(potential_instrument_1_pos + potential_instrument_2_pos) and sgn(potential_basket_pos) < 0:
                    difference = abs(potential_basket_pos) - (abs(potential_instrument_1_pos) + abs(potential_instrument_2_pos))
                    instrument_1_volume = max(0, instrument_1_volume - difference // 2)
                    instrument_2_volume = max(0, instrument_2_volume - difference // 2)
                elif abs(potential_basket_pos) < abs(potential_instrument_1_pos + potential_instrument_2_pos) and sgn(potential_basket_pos) < 0:
                    difference = (abs(potential_instrument_1_pos) + abs(potential_instrument_2_pos)) - abs(potential_basket_pos)
                    basket_volume = max(0, basket_volume - difference)
                elif abs(potential_basket_pos) < abs(potential_instrument_1_pos + potential_instrument_2_pos) and sgn(potential_basket_pos) > 0:
                    difference = abs(potential_instrument_1_pos) + abs(potential_instrument_2_pos) - abs(potential_basket_pos)
                    instrument_1_volume = max(0, instrument_1_volume - difference // 2)
                    instrument_2_volume = max(0, instrument_2_volume - difference // 2)
            else: # case examples:  200, 10, 10 / 50, 30, 30 / -200, -10, -10
                if sgn(potential_basket_pos) == 1:
                    difference = abs(potential_basket_pos) + (abs(potential_instrument_1_pos) + abs(potential_instrument_2_pos))
                    basket_volume = max(0, basket_volume - difference)
                elif sgn(potential_basket_pos) == -1:
                    difference = abs(potential_instrument_1_pos) + abs(potential_instrument_2_pos) + abs(potential_basket_pos)
                    instrument_1_volume = max(0, instrument_1_volume - difference // 2)
                    instrument_2_volume = max(0, instrument_2_volume - difference // 2)
            #debug += f'2.3 {basket_volume} {instrument_1_volume} {instrument_2_volume}'

            """ Calculate profit """
            profit = (highest_bid_instrument_1.price - OVER_ASKING) * instrument_1_volume
            profit += (highest_bid_instrument_2.price - OVER_ASKING) * instrument_2_volume
            profit -= (lowest_ask_basket.price + UNDER_BIDDING) * basket_volume
            
            """ Execute trades if their volume is larger than zero and profit is large enough """
            if profit > -MAX_NEGATIVE_PROFIT:
                if basket_volume > 0 or instrument_1_volume > 0 or instrument_2_volume > 0:
                    logger.info(f'Try to buy {basket_volume} of {instrument_ids[0]} and sell {instrument_1_volume} of {instrument_ids[1]} and {instrument_2_volume} of {instrument_ids[2]} with a price delta of {profit:.2f}')
                if instrument_2_volume > 0:
                    order_responses.append(e.insert_order(
                        instrument_ids[2], price=highest_bid_instrument_2.price - OVER_ASKING,
                        volume=instrument_2_volume, side=SIDE_ASK, order_type=ORDER_TYPE_IOC))
                if basket_volume > 0:
                    if (instrument_ids[0] == 'C2_GREEN_ENERGY_ETF'):
                        pass
                        """outstanding_orders = e.get_outstanding_orders(instrument_ids[0])
                        print(outstanding_orders)
                        own_order = sum(map(lambda x: x.side == SIDE_ASK, outstanding_orders.values()))
                        if own_order == 0:
                            order_responses.append(e.insert_order(
                                instrument_ids[0], price=lowest_ask_basket.price + UNDER_BIDDING,
                                volume=basket_volume, side=SIDE_BID, order_type=ORDER_TYPE_IOC))"""
                    else:
                        order_responses.append(e.insert_order(
                            instrument_ids[0], price=lowest_ask_basket.price + UNDER_BIDDING,
                            volume=basket_volume, side=SIDE_BID, order_type=ORDER_TYPE_IOC))
                if instrument_1_volume > 0:
                    order_responses.append(e.insert_order(
                        instrument_ids[1], price=highest_bid_instrument_1.price - OVER_ASKING,
                        volume=instrument_1_volume, side=SIDE_ASK, order_type=ORDER_TYPE_IOC))
                
    
    """ If orders were executed print current positions """
    if len(order_responses) > 0:
        #print(debug)
        positions = e.get_positions()
        logger.info(positions)


def log_profit(e: Exchange, instrument_ids: list):
    """ Calculate summary of PnL for all positions """
    basket_trades = e.poll_new_trades(instrument_ids[0])
    instrument_1_trades = e.poll_new_trades(instrument_ids[1])
    instrument_2_trades = e.poll_new_trades(instrument_ids[2])
    
    total_pnl = 0
    for k, trades in enumerate([basket_trades, instrument_1_trades, instrument_2_trades]):
        pnl_trades = 0
        for trade in trades:
            summed_price = trade.price * trade.volume
            if trade.side == SIDE_BID: # Subtract if bought
                pnl_trades -= summed_price
            elif trade.side == SIDE_ASK: # Add if sold
                pnl_trades += summed_price
        logger.info(f'PnL from {len(trades)} {instrument_ids[k]} trades: {pnl_trades:.2f}')
        total_pnl += pnl_trades
    
    logger.info(f'Total PnL: {total_pnl:.2f}')
    
def thread_loop(e: Exchange, instrument_ids: list):
    """ Loop which is started for each thread """
    global running
    while running: # Loop until 'running' is set to false in main thread
        trade_cycle(e, instrument_ids)
        #try: # Capture any exception to prevent program termination
        #except Exception as exc:
        #    e.connect()
        #    logger.info('Error: ' + str(exc))
        #time.sleep(0.01)
    log_profit(e, instrument_ids) # Log profits at termination
    
def on_tick_market_maker(e: Exchange, iid: str):
    global total_pnl, hits, lifts
    basket_book = e.get_last_price_book(iid)
    
    # EXIT CONDITION 1: no asks or no bids
    if not basket_book.asks or not basket_book.bids:
        return
    
    # EXIT CONDITION 2: bid-ask spread <= 0.2
    min_ask = basket_book.asks[0]
    max_bid = basket_book.bids[0]
    if min_ask.price - max_bid.price < MARKET_MAKER_MARGIN * 3:
        return
    
    # STEP 1: CANCEL ALL OUTSTANDING ORDERS
    e.delete_orders(iid)
    
    # STEP 2: PLACE MARKET MAKING ORDERS
    ask_price = min_ask.price - MARKET_MAKER_MARGIN
    ask_order = e.insert_order(iid, price=ask_price, volume=ORDER_VOLUME, side=SIDE_ASK, order_type=ORDER_TYPE_LIMIT)
    bid_price = max_bid.price + MARKET_MAKER_MARGIN
    bid_order = e.insert_order(iid, price=bid_price, volume=ORDER_VOLUME, side=SIDE_BID, order_type=ORDER_TYPE_LIMIT)
    
    # STEP 3: CALCULATE PnL
    trades = e.poll_new_trades(iid)
    pnl = 0
    for trade in trades:
        summed_price = trade.price * trade.volume
        if trade.side == SIDE_BID: # Subtract if bought
            pnl -= summed_price
            hits += trade.volume
        elif trade.side == SIDE_ASK: # Add if sold
            pnl += summed_price
            lifts += trade.volume
    
    total_pnl += pnl
    logger.info(f'Made BID [{bid_price:.2f}] & ASK [{ask_price:.2f}] orders, spread [{(ask_price - bid_price):.2f}], last PnL: {pnl:.2f}, totalPnL: {total_pnl:.2f}, hits {hits} lifts {lifts}')
    
def market_maker(e: Exchange):
    global running
    while running:
        on_tick_market_maker(e, 'C2_GREEN_ENERGY_ETF')
        #time.sleep(0.02)

def main():
    global running
    """ Initialize exchange """
    exchange = Exchange()
    exchange.connect()
    
    """ Print initial positions """
    positions = exchange.get_positions()
    logger.info(positions)

    t1 = threading.Thread(target=thread_loop, args=[exchange, ['C2_GREEN_ENERGY_ETF', 'C2_SOLAR_CO', 'C2_WIND_LTD']])
    t2 = threading.Thread(target=thread_loop, args=[exchange, ['C1_FOSSIL_FUEL_ETF', 'C1_GAS_INC', 'C1_OIL_CORP']])
    tmm = threading.Thread(target=market_maker, args=[exchange])
    try:
        """ Start two threads, each trading one of the two basket-stock-bundles """
        t1.start()
        t2.start()
        tmm.start()
        """ Wait for both threads to finish """
        t1.join()
        t2.join()
        tmm.join()
    except KeyboardInterrupt:
        print()
        running = False
    
    """ Wait for both threads to finish """
    t1.join()
    t2.join()
    tmm.join()
    
    """ Print final positions """
    positions = exchange.get_positions()
    logger.info(positions)

if __name__ == '__main__':
    main()
