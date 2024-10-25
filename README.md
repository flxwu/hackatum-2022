https://devpost.com/software/i-triple-w


# Optiver Challenge HackaTUM 2022
Our task was to build a) a trading bot that takes advantage of market inefficiencies and b) a market making bot.


# Team 032 (I Triple W)


# Idea Description and Implementation Explanation

Part 1



* Check if there is a market inefficiency, i.e. a difference between theoretical basket price and real basket price, in a loop
* Separate inefficiency situation into two cases:
    * Highest bid price for the basket is larger than the combined partial stock prices. → Basket is overvalued and we want to sell the basket and buy the stocks
    * Lowest ask price for the basket is smaller than the combined partial stock prices. → Basket is undervalued and we want to buy the basket and sell the stocks.
* Determine optimal order volume for each instrument by considering a balancing of our position and a maximisation of the order volume
    * Start with maximum potential order volumes from the order book
    * At first, reduce the order volumes of both stock instruments to be as balanced as possible
    * Afterwards, adjust the order volumes of basket and both instrument to keep the basket positions as equal as possible to the stock positions
* Place IOC orders if the profit is larger than a threshold

Part 2



* We quote between the lowest ask and the highest bid to provide liquidity to an illiquid market: we make sure to always overbid and underask the current order book 
    * Long term quoting plan: quoting depends on: “hit” and “lift” rate, market liquidity,  risk we are willing to take, our current inventory
* Our orders are reset on every tick in order to account for market movements such that our bids and asks always adapt to the current order book
* For our prototype we measured market metrics (by analysing the order book) and found that an order volume of 4 on both sides respectively is small enough to limit risk exposure and high enough to make a significant profit
    * Long term volume plan: we propose a dynamic approach: the order volume should depend on the inventory (positive position: higher ask volume, negative position: higher bid volume) and our current/forecasted “hit” and “lift” rate 
* Hedging: We combined our market making strategy with the opportunity detection strategy from part 1 which handles the balancing 
    * Long term hedging plan: having an optimizer function that outputs “Hedge” or “Wait” depending on parameters: our position size, PnL of the hedge (best current market price that we can go short/ long on the stocks for minus our market making bid-ask spread, i.e. the price that we might pay for the hedge minus the profit that we make with market making)

Additional implementation details:



* Start multiple threads, one for the green energy market making algorithm (part 2) and one for the hedging of each market segment (part 1), i.e. three threads in total


# Risk Handling



* We chose a minimal risk strategy by keeping our positions as balanced as possible
* Risks for hedging:
    * We do not fully realise our orders and therefore get an unbalanced portfolio.
    * Being unbalanced is risky because we are dependent on the random movement of the market
    * We adjust our orders to our imbalances, such that we tend towards a balanced portfolio
* Risks for market making:
    * Depend heavily on part 1 (since we combined the two strategies)
    * Additional risk sources: We are not able to hedge the size of our market making exposure/volume profitably
