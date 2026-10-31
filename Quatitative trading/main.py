from operator import index

import yfinance as yf
import sqlite3
import pandas as pd
from curl_cffi import requests
import seaborn as sns
import matplotlib.pyplot as plt
session = requests.Session(impersonate='chrome')

stockdic = {}
stocks = ['601138.SS', '601600.SS','002475.SZ','000988.SZ','603920.SS']
stockdic['gyfl'] = stocks[0]
stockdic['zgly'] = stocks[1]
stockdic['lxjm'] = stocks[2]
stockdic['hgkj'] = stocks[3]
stockdic['sydl'] = stocks[4]
conn = sqlite3.connect('stocks.db')
##class stock, take real name in
class stock:
    def __init__(self,name,data = None):
        self.data = data
        self.name = name
    def dowanload(self,timespan): ##imput the string of time span
        self.data = yf.download(
            stockdic[self.name],
            period=timespan,
            multi_level_index=False,
            auto_adjust=True,
            progress=True,session = session)
        self.data.to_sql(self.name,conn,if_exists='replace')
    def calculateMA(self,days: list[int]): ## calculate mA 5 for example
        data = self.data
        for i in days:
            add = "MA{}".format(i)
            data[add] = self.data["Close"].rolling(window = i).mean()
        self.data.to_sql(self.name, conn, if_exists='replace')
    def calculateMACD(self,days: list[int]):
        data = self.data
        if len(days)!=3:
            print("MACD requires only 3 factors")
            return
        emafirst = self.data["Close"].ewm(span = days[0], adjust = True).mean()
        emasecond = self.data["Close"].ewm(span = days[1], adjust = True).mean()
        dif = emafirst - emasecond
        dea = dif.ewm(span = days[2], adjust = True).mean()
        self.data["DIF"] =dif
        self.data["DEA"] =dea
        self.data["MACD"] = 2*(dif-dea)
        self.data["goldencross"] = (
            (dif > dea) & (dif.shift(1) <= dea.shift(1))
        )
        self.data["deadcross"] = (
            (dif < dea) & (dif.shift(1) >= dea.shift(1))
        )
        self.data.to_sql(self.name, conn, if_exists='replace')

## Strategy
##strategy stimulation all in one
class strategy:
    def __init__(self,port: list[stock], timespan: int, factors: dict, money: int ):
        self.port = port
        self.timespan = timespan
        self.factors = factors ## such as "macd" : 0, "upsell": 15, "downsell": 15
        self.money = money
        self.totalprofit = 0 ##totalprofit
        self.profit = {} ## store to expense of each stocks
        self.transactions = {}

    def initialize(self):
        for stock in self.port:
            stock.dowanload(timespan = self.timespan)
            stock.calculateMACD([10,23,8])
            stock.calculateMA(days = [5,20])
            self.transactions[stock] = [0,0,0]  ##transactions[stock][0]: average price, [1]: volume, [2]: index in dataframe
            self.profit[stock] = 0
    def buy(self, chosenstock: stock,date: int, price: float, volume: int) -> bool:
        if self.money < price * volume*100:
            print("run out of money")
            return False
        self.money -= price*volume*100
        self.totalprofit += price * volume*100
        ## modifying transactions
        oldvolume = self.transactions[chosenstock][1]
        self.transactions[chosenstock][1] += volume*100 ##adding volume
        self.transactions[chosenstock][0] = (self.transactions[chosenstock][0]*oldvolume+price*volume*100)/ self.transactions[chosenstock][1] ## calculating average price
        self.transactions[chosenstock][2] = date
        self.totalprofit -= price * volume*100
        self.profit[chosenstock] -= price*volume*100 ##changing profit
        name = chosenstock.name
        actualdate = chosenstock.data.index[date]
        print(f"Buy {name} at {actualdate}, {volume} in price {price}")
        return True
    ##take the list of price and list of volume as corresponding pairs for operation
    def sell(self, chosenstock: stock, date: int, price: float, volume: int) -> bool:
        if volume*100 > self.transactions[chosenstock][1]:
            print("volume exceeds")
            return False
        self.money += price*volume*100
        self.totalprofit += price * volume*100
        self.profit[chosenstock] += price*volume*100
        self.transactions[chosenstock][1] -= volume*100
        if self.transactions[chosenstock][1] == 0:
            self.transactions[chosenstock] = [0,0,0]
        name = chosenstock.name
        actualdate = chosenstock.data.index[date]
        print(f"Sell {name} at {actualdate}, {volume} in price {price}")
        return True

    def readandexecute(self):
        for st in self.port:
            st.data = st.data.sort_index()
            for i in range(len(st.data)):
                row = st.data.iloc[i]
                if i == 0:
                    continue
                if st.data.iloc[i-1]["goldencross"] and (-0.1<st.data.iloc[i-1]["DIF"]<0.1): ##golden cross buy
                    if i >= len(st.data):
                        continue
                    price = st.data.iloc[i]["Open"]
                    if price > st.data.iloc[i-1]["Close"] * 0.99:
                        self.buy(st,i,price,1) ## again using factors
                if self.transactions[st][1] > 0 and i > self.transactions[st][2]: ## if price > the average price of the holding price then sold all
                    high = row["High"]
                    low = row["Low"]
                    if high > self.transactions[st][0]*1.15 > low: ## really sell the stock by the factor given
                        self.sell(st,i,self.transactions[st][0]*1.15,self.transactions[st][1]//100)




