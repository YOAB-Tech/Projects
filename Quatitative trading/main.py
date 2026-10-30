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
            progress=True)
        self.data.to_sql(self.name,conn,if_exists='replace')
    def calculateMA(self,days: list[int]): ## calculate mA 5 for example
        data = self.data
        for i in days:
            add = "MA{}".format(i)
            data[add] = self.data.rolling(window = i).mean()
        self.data.to_sql(self.name, conn, if_exists='replace')
    def calculateMACD(self,days: list[int]):
        data = self.data
        if len(days)!=3:
            print("MACD requires only 3 factors")
            return
        emafirst = self.data.ewm(span = days[0], adjust = True).mean()
        emasecond = self.data.ewm(span = days[1], adjust = True).mean()
        dif = emafirst - emasecond
        dea = dif.ewm(span = days[2], adjust = True).mean()
        self.data["DIF"] =dif
        self.data["DEA"] =dea
        self.data["MACD"] = 2*(dif-dea)
        self.data["goldencross"] = (
            dif > dea and dif.shift(1) <= dea.shift(1)
        )
        self.data["deadcross"] = (
            dif < dea and dif.shift(1) >= dea.shift(1)
        )
        self.data.to_sql(self.name, conn, if_exists='replace')

## Strategy
##MACD strategy
class strategy:
    def __init__(self,port: list[stock], timespan: int, factors: dict, money: int ):
        self.port = port
        self.timespan = timespan
        self.factors = factors ## such as "macd" : 0, "upsell": 15, "downsell": 15
        self.money = money
        self.expense = 0

    def initialize(self):
        for stock in self.port:
            stock.dowanload(timespan = self.timespan)
            stock.calculateMACD([10,23,8])
            stock.calculateMA(days = [5,20])

    def buy(self, chosenstock: stock,date: str, price: float, volume: int):
        self.expense += price * volume*100
        name = chosenstock.name
        print(f"Buy {name} at {date}, {volume} in price {price}")

    def sell(self, chosenstock: stock, date: str, price: float, volume: int):
        self.expense -= price * volume
         ## notice that self.expense is negative when earning money
        name = chosenstock.name
        print(f"Sell {name} at {date}, {volume} in price {price}")

    def readandexecute(self):
        for st in self.port:
            st.data = st.data.sort_index()
            for i,(date, row) in st.data.iterrows():
                if row["goldencross"] and (-0.1<row["DIF"]<0.1):
                    if i+1 >= len(st.data):
                        continue
                    nextdate = st.data.index[i+1]
                    nextprice = st.data["Open"].iloc[i+1]
                    self.buy(st,nextdate,nextprice,1)

