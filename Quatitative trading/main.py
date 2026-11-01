from datetime import date
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
class Stock:
    def __init__(self,name,data = None):
        self.data = data
        self.name = name
    def download(self,timespan):##imput the string of time span, ##download new data (purely)
        self.data = yf.download(
            stockdic[self.name],
            period=timespan,
            multi_level_index=False,
            auto_adjust=True,
            progress=True,session = session)
        self.data.to_sql(self.name,conn,if_exists='append')
    def loadfromdatabase(self): ##load the stock data from stock.db, return False if there's now existing corresponding table
        table_exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",(self.name,)).fetchone()
        if table_exists is None:
            return False
        self.data = pd.read_sql_query(
            f'SELECT * FROM {self.name}',
            conn,
            parse_dates = ["Date"],
            index_col = "Date",
        )
        return True
    def calculateMA(self,days: list[int]): ## calculate mA 5 for example
        data = self.data
        for i in days:
            add = "MA{}".format(i)
            data[add] = self.data["Close"].rolling(window = i).mean()
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
    def calculateVMA(self,days:list[int]):
        data = self.data
        for i in days:
            add = "VMA{}".format(i)
            data[add] = self.data["Volume"].rolling(window = i).mean()
## Strategy
##strategy stimulation all in one
class Strategy:
    def __init__(self,port: list[Stock], timespan: int, factors: dict, money: int ):
        self.port = port
        self.timespan = timespan
        self.factors = factors ## such as "macd" : 0, "upsell": 15, "downsell": 15
        self.money = money
        self.totalprofit = 0 ##totalprofit
        self.transactions = pd.DataFrame(columns = ["averageprice","volume","date","profit"]) ## name as index, indicating average price and v etc. for each stock
        self.operations = pd.DataFrame(columns = ["name","date","price", "volume","buy","totalprice"]) ##dataframe storing comprehensive transaction details

    def initialize(self):
        for stock in self.port:
            if not stock.loadfromdatabase():
                stock.download(timespan = self.timespan)
            self.update(stock)
            stock.calculateMACD([10,23,8])
            stock.calculateMA(days = [5,20])
            self.transactions.loc[stock.name] = [0,0,pd.Timestamp.today().normalize(),0]
            ## initialize transactions dataframe, add more attributes later
    def update(self, st):  ##handle the case where the data is stale
        st.loadfromdatabase()
        latest_date = st.data.index.max()
        next_date = latest_date + pd.Timedelta(days=1)
        today = pd.Timestamp.today().normalize()
        if next_date > today:
            return
        new_data = yf.download(
            stockdic[st.name],
            start=next_date,
            end=(today + pd.Timedelta(days=1)),
            multi_level_index=False,
            progress=False,
            session=session,
        )
        if new_data.empty:
            return
        new_data = new_data[new_data.index > latest_date]
        if not new_data.empty:
            new_data.to_sql(
                st.name,
                conn,
                if_exists='append',
                index = True,
                index_label="Date"
            )
            conn.commit()
            st.data = pd.concat([st.data,new_data]).sort_index()
    def buy(self, chosenstock: Stock,date: int, price: float, volume: int) -> bool:
        if volume == 0:
            return False
        if self.money < price * volume*100:
            print("run out of money")
            return False
        self.money -= price*volume*100
        self.totalprofit -= price*volume*100
        sn = chosenstock.name
        ## modifying transactions
        newrow = {"name": chosenstock.name,"date" : chosenstock.data.index[date],"price" : price,"volume" : volume*100,"buy" : True}
        self.operations = pd.concat([self.operations,pd.DataFrame([newrow])],ignore_index = True)
        lastindex = self.operations.index[-1]
        self.operations.loc[lastindex,"totalprice"] = price*volume*100
        old_volume = self.transactions.loc[sn,"volume"]
        old_price = self.transactions.loc[sn,"averageprice"]
        self.transactions.loc[sn,"volume"] +=volume*100
        self.transactions.loc[sn,"averageprice"] = (old_price*old_volume+price*volume*100) / (old_volume+volume*100)
        self.transactions.loc[sn,"date"] = chosenstock.data.index[date]
        self.transactions.loc[sn,"profit"] -= price*volume*100
        name = chosenstock.name
        actualdate = chosenstock.data.index[date]
        print(f"Buy {name} at {actualdate}, {volume} in price {price}")
        return True
    def sell(self, chosenstock: Stock, date: int, price: float, volume: int) -> bool:
        if volume == 0:
            return False
        sn = chosenstock.name
        if volume*100 > self.transactions.loc[sn,"volume"]:
            print("volume exceeds")
            return False
        self.money += price*volume*100
        self.totalprofit += price * volume*100
        self.transactions.loc[sn, "profit"] += price * volume * 100
        newrow = {"name": chosenstock.name,"date" : chosenstock.data.index[date],"price" : price,"volume" : volume*100,"buy" : False}
        self.operations = pd.concat([self.operations,pd.DataFrame([newrow])],ignore_index = True)
        lastindex = self.operations.index[-1]
        self.operations.loc[lastindex, "totalprice"] = -price * volume * 100
        old_volume = self.transactions.loc[sn,"volume"]
        old_price = self.transactions.loc[sn,"averageprice"]
        self.transactions.loc[sn,"volume"] -=volume*100
        if volume*100 == old_volume:
            self.transactions.loc[sn,"averageprice"] = 0
        name = chosenstock.name
        actualdate = chosenstock.data.index[date]
        print(f"Sell {name} at {actualdate}, {volume} in price {price}")
        return True

    ##read the factor and execute it to get the corresponding data
    def readandexecute(self):
        all_dates = sorted(set().union(*(set(stock.data.index)for stock in self.port)))
        for i in all_dates:
            for st in self.port:
                if i not in st.data.index:
                    continue
                st.data = st.data.sort_index()
                ##rl --> real index ( im too lazy to change i to date)
                rl = st.data.index.get_loc(i)
                if rl == 0:
                    continue
                row = st.data.iloc[rl]
    ##===============buy operation===================================
                if st.data.iloc[rl-1]["goldencross"] and (-0.1<st.data.iloc[rl-1]["DIF"]<0.1): ##golden cross buy
                    if rl >= len(st.data):
                        continue
                    price = row["Open"]
                    if price > st.data.iloc[rl-1]["Close"] * 0.99:
                        self.buy(st,rl,price,round((self.money/len(self.port))/(price*100))) ## again using factors
                if st.data.iloc[rl]["Open"] < st.data.iloc[rl-1]["Low"] and st.data.iloc[rl]["Close"] > st.data.iloc[rl-1]["High"]:
                    price = row["Open"]
                    if rl +1>= len(st.data):
                        continue
                    self.buy(st,rl+1,st.data.iloc[rl+1]["Open"],round((self.money/len(self.port))/(price*100)))
    ##================sell determination====================================
                if self.transactions.loc[st.name,"volume"] > 0 and i > self.transactions.loc[st.name,"date"]: ## if price > the average price of the holding price then sold all
                    boughtprice = self.transactions.loc[st.name,"averageprice"]
                    volume = self.transactions.loc[st.name,"volume"]
                    high = row["High"]
                    low = row["Low"]
                    if high > boughtprice*1.15 > low: ## really sell the stock by the factor given
                           ##add the factor later, now just define the strategy myself
                        self.sell(st,rl,boughtprice*1.15,round((volume//100)*0.6))
                    if low>= boughtprice*1.15:
                        self.sell(st,rl,low,round((volume//100)*0.6))
                    if low< boughtprice * 0.92 < high:
                        self.sell(st,rl,boughtprice*0.92,volume//100)
                    if high< boughtprice * 0.92 :
                        self.sell(st,rl,high,volume//100)




