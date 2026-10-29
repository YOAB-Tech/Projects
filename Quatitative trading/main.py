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
    def dowanload(self,timespan):
        self.data = yf.download(
            stockdic[self.name],
            period=timespan,
            multi_level_index=False,
            auto_adjust=True,
            progress=True)
        self.data.to_sql(self.name,conn,if_exists='replace')
    def calculateMA(self,days: list[int]):
        data = self.data
        for i in days:
            add = "MA{}".format(i)
            data[add] = self.data.rolling(window = i).mean()
    def calculateMACD(self,days: list[int]):
        data = self.data
        if len(days)!=3:
            print("error")
            return
        emafirst = self.data.ewm(span = days[0], adjust = True).mean()
        emasecond = self.data.ewm(span = days[1], adjust = True).mean()
        dif = emafirst - emasecond
        dea = dif.ewm(span = days[2], adjust = True).mean()
        self.data["Dif{}".format(days)] =dif
        self.data["Dea{}".format(days)] =dea
instance = stock('lxjm')
instance.dowanload("1y")
close = instance.data["Close"]
plt.figure(figsize = (12,6))
sns.lineplot(x = close.index, y = close.values )
plt.xlabel("Date")
plt.ylabel("Close")
plt.show()



