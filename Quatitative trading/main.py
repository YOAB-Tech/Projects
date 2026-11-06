from datetime import date
import yfinance as yf
import sqlite3
import pandas as pd
from curl_cffi import requests
import re
import random
import seaborn as sns
import matplotlib.pyplot as plt
session = requests.Session(impersonate='chrome')

#=================================helper function=============================
def period_start(period:str,end_date = None):
    match = re.fullmatch(r"(\d+)(d|wk|mo|y)", period.lower())
    if match is None:
        raise ValueError(f"Invalid period {period}")
    amount = int(match.group(1))
    unit = match.group(2)
    if end_date is None:
        end_date = pd.Timestamp.today().normalize()
    else:
        end_date = pd.Timestamp(end_date)
    offsets = {
        "d": pd.Timedelta(days=amount),
        "wk": pd.Timedelta(weeks=amount),
        "mo": pd.DateOffset(months=amount),
        "y": pd.DateOffset(years=amount),
    }
    return end_date - offsets[unit]

stockdic = {}
stocks = ['601138.SS', '601600.SS','002475.SZ','000988.SZ','603920.SS']
stockdic['gyfl'] = stocks[0]
stockdic['zgly'] = stocks[1]
stockdic['lxjm'] = stocks[2]
stockdic['hgkj'] = stocks[3]
stockdic['sydl'] = stocks[4]
stockindex = ['szzs', 'szcz', 'kczj', 'cybz']
stockdic.update({'szzs': '000001.SS','szcz': '399001.SZ','kczj':'000680.SS','cybz':'399006.SZ'})
conn = sqlite3.connect('stocks.db')
##class stock, take real name in
class Stock:
    def __init__(self,name:str,data = None):
        self.data = data
        self.name = name
        self.buyindicator = 0
        self.sellindicator = 0
    def committodatabase(self):
        self.data.to_sql(self.name,conn,if_exists='replace',index = True, index_label="Date")
        conn.commit()
    def download(self,timespan):##imput the string of time span, ##download new data (purely)
        data = yf.download(
            stockdic[self.name],
            period=timespan,
            multi_level_index=False,
            auto_adjust=True,
            progress=True,session = session)
        if data is None or data.empty:
            raise RuntimeError(f'Stock {self.name} not available')
        self.data = data.sort_index()
    def loadfromdatabase(self): ##load the stock data from stock.db, return False if there's now existing corresponding table
        table_exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",(self.name,)).fetchone()
        if table_exists is None:
            return False
        data = pd.read_sql_query(
            f'SELECT * FROM {self.name}',
            conn,
            parse_dates = ["Date"],
            index_col = "Date",
        )
        if data.empty:
            return False
        self.data = data.sort_index()
        return True
    def update(self):  ##handle the case where the data is stale
        if not self.loadfromdatabase():
            return False
        latest_date = self.data.index.max()
        next_date = latest_date + pd.Timedelta(days=1)
        today = pd.Timestamp.today().normalize()
        if next_date > today:
            return
        new_data = yf.download(
            stockdic[self.name],
            start=next_date,
            end=(today + pd.Timedelta(days=1)),
            multi_level_index=False,
            progress=False,
            session=session,
        )
        if new_data.empty:
            return True
        new_data = new_data[new_data.index > latest_date]
        self.data = pd.concat([self.data,new_data]).sort_index()
        return True
    def calculateallIndex(self,macd = [10,23,8],ma = [5,20],vma = [5,20],start_timestamp = None, warmup = 200):
        self.data = self.data.sort_index()
        if start_timestamp is None:
            start_pos = 0
        else:
            start_time = pd.Timestamp(start_timestamp)
            start_pos = self.data.index.searchsorted(start_time,side = "left")
        if start_pos >= len(self.data):
            return self.data.iloc[0:0].copy()
        calculation_start = max(0,start_pos-warmup)
        calculation_data = self.data.iloc[calculation_start:].copy()
        close = calculation_data["Close"]
        volume =calculation_data["Volume"]
        #===================================MA and VMA calculation=================================
        for i in ma:
            calculation_data[f"MA{i}"] = close.rolling(window = i).mean()
        for i in vma:
            calculation_data[f"VMA{i}"] = volume.rolling(window = i).mean()
        #===================================MACD calculation========================================
        if len(macd)!=3:
            raise ValueError("MACD requires 3 factors")
        ema_fast = close.ewm(span = macd[0], adjust = False).mean()
        ema_slow = close.ewm(span = macd[1], adjust = False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span = macd[2], adjust = False).mean()
        calculation_data["DIF"] = dif
        calculation_data["DEA"] = dea
        calculation_data["MACD"] = 2 * (dif-dea)
        calculation_data["goldencross"] = (
        (dif > dea) & (dif.shift(1) <= dea.shift(1))
        )
        calculation_data["deadcross"] = (
        (dif < dea) & (dif.shift(1) >= dea.shift(1))
        )
        for column in ("goldencross", "deadcross"):
            if column in self.data.columns:
                self.data[column] = (
                    self.data[column]
                    .fillna(False)
                    .astype(bool)
                )
        result = calculation_data.iloc[start_pos-calculation_start:].copy()
        for column in result.columns:
            self.data.loc[result.index,column] = result[column]
        return result
## Strategy
##strategy stimulation all in one
class Strategy:
    def __init__(self,port: list[Stock], timespan: str, money: int, factorusage : list[str],
                 stop = 0.92 , target = 1.15, macd = [0.1,0.5],ma_calculation = (5,20),
                 macd_calculation = (10,23,8),vma_calculation = (5,20)):
        self.port = port
        self.timespan = timespan## such as "macd" : 0, "upsell": 15, "downsell": 15
        self.money = money
        self.initial_money = money
        self.start_date = period_start(timespan)
        self.macd = macd
        self.ma_calculation = list(ma_calculation)
        self.vma_calculation = list(vma_calculation)
        self.macd_calculation = list(macd_calculation)
        self.factorusage = factorusage
        self.target = target
        self.stop = stop
        self.equity_curve = pd.DataFrame(columns=["cash","position_value","portfolio_value","profit",]) ##record the panorama of trades
        self.totalprofit = 0 ##totalprofit
        self.transactions = pd.DataFrame({
            "averageprice": pd.Series(dtype="float64"),
            "volume": pd.Series(dtype="int64"),
            "date": pd.Series(dtype="datetime64[ns]"),
            "profit": pd.Series(dtype="float64"),
        })
        ## name as index, indicating bought average price and bought v newest bought date, and totalprofit for each stock
        self.operations = pd.DataFrame({
            "name": pd.Series(dtype="object"),
            "date": pd.Series(dtype="datetime64[ns]"),
            "price": pd.Series(dtype="float64"),
            "volume": pd.Series(dtype="int64"),
            "buy": pd.Series(dtype="bool"),
            "totalprice": pd.Series(dtype="float64"),
        })
        ##dataframe storing comprehensive transaction details
    def initialize(self):
        for stock in self.port:
            loaded = stock.loadfromdatabase()
            if loaded:
                stock.update()
                indicator_columns = [
                    "DIF",
                    "DEA",
                    "MACD",
                    "goldencross",
                    "deadcross",
                    *[f"MA{window}" for window in self.ma_calculation],
                    *[f"VMA{window}" for window in self.vma_calculation],
                ]
                if not set(indicator_columns).issubset(stock.data.columns):
                    stock.calculateallIndex(macd=self.macd_calculation, ma=self.ma_calculation,
                                            vma=self.vma_calculation)
                    stock.committodatabase()
                else:
                    missing_rows = stock.data[indicator_columns].isna().any(axis=1)
                    if missing_rows.any():
                        first_missing_date = stock.data.index[missing_rows][0]
                        stock.calculateallIndex(
                            macd=self.macd_calculation,
                            ma=self.ma_calculation,
                            vma=self.vma_calculation,
                            start_timestamp=first_missing_date,
                            )
                    stock.committodatabase()
            else:
                stock.download(timespan=self.timespan)
                stock.calculateallIndex(macd = self.macd_calculation,ma = self.ma_calculation,vma = self.vma_calculation)
                stock.committodatabase()
            self.transactions.loc[stock.name] = [0.0,0,pd.Timestamp.today().normalize(),0.0]
        for index in stockindex:
            index_stock = Stock(index)
            loaded = index_stock.loadfromdatabase()
            if loaded:
                index_stock.update()
            else:
                index_stock.download(timespan=self.timespan)
            index_stock.committodatabase()
            ## initialize transactions dataframe, add more attributes later
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
        print(f"Buy {name} at {actualdate}, {volume} in price {price}, total price {volume*100*price}")
        print(self.totalprofit)
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
        print(f"Sell {name} at {actualdate}, {volume} in price {price}, total price {volume*100*price}")
        print(f"Current profit{int(self.totalprofit)}, {int(self.money)}remains")
        return True
    def prepare_closing_price(self,all_dates):
        closing_prices = pd.DataFrame({st.name:st.data['Close']
                                       for st in self.port})
        closing_prices = closing_prices.sort_index()
        closing_prices = closing_prices.reindex(all_dates).ffill()
        return closing_prices
    ##read the factor and execute it to get the corresponding data
    def readandexecute(self):
        all_dates = sorted({
            current_date
            for stock in self.port
            for current_date in stock.data.index
            if current_date >= self.start_date
        })
        closing_prices = self.prepare_closing_price(all_dates)
        minimum_history = 34
        for i in all_dates:
            for st in self.port:
                if i not in st.data.index:
                    continue
                st.data = st.data.sort_index()
                ##rl --> real index ( im too lazy to change i to date)
                rl = st.data.index.get_loc(i)
                if rl < minimum_history:
                    continue
                row = st.data.iloc[rl]
                previous = st.data.iloc[rl-1]
                before_previous = st.data.iloc[rl-2]
    ##===============buy operation===================================
                macd_signal = (
                        "macd" in self.factorusage
                        and previous["goldencross"]
                        and -self.macd[0] < previous["DIF"] < self.macd[0]
                        and before_previous["DEA"] < self.macd[1] ##ensure the purchase is after a sudden golden cross
                        and before_previous["DIF"] < self.macd[1]
                        and previous["VMA{}".format(self.vma_calculation[0])] > previous["VMA{}".format(self.vma_calculation[1])]
                        and before_previous["VMA{}".format(self.vma_calculation[0])] <= before_previous["VMA{}".format(self.vma_calculation[1])]
                        and row["Open"] >= previous["Close"] * 0.99
                )
                devour_signal = (
                        "devour" in self.factorusage
                        and previous["Open"] <= before_previous["Low"]
                        and previous["Close"] >= before_previous["High"]
                )
                ma_signal = ( ##golden cross for MA
                    "ma" in self.factorusage
                    and previous["MA{}".format(self.ma_calculation[0])]>=previous["MA{}".format(self.ma_calculation[1])]
                    and before_previous["MA{}".format(self.ma_calculation[0])]<=before_previous["MA{}".format(self.ma_calculation[1])]
                )
                if macd_signal or devour_signal or ma_signal:
                    entry_price = row["Open"]
                    volume = int((self.money/len(self.port))/(entry_price*100))
                    if volume > 0:
                        self.buy(st,rl,entry_price,volume)
    ##================sell determination====================================
                if self.transactions.loc[st.name,"volume"] > 0 and i > self.transactions.loc[st.name,"date"]: ## if price > the average price of the holding price then sold all
                    reversed_devour_signal = (
                            previous["Open"] >= before_previous["High"]
                            and previous["Close"] <= before_previous["Low"]
                    )
                    macd_signal = (
                        "macd" in self.factorusage
                        and previous["deadcross"]
                        and (previous["DEA"] < -self.macd[1] or previous["DEA"] > self.macd[1])
                    )
                    boughtprice = self.transactions.loc[st.name,"averageprice"]
                    targetprice = boughtprice * self.target
                    stopprice = boughtprice * self.stop
                    volume = self.transactions.loc[st.name,"volume"]
                    high = row["High"]
                    low = row["Low"]
                    open_price = row["Open"]
                    lots = int(volume//100)
                    partiallots = max(1, int(lots)) if lots else 0
                    if reversed_devour_signal or macd_signal: ##make stop of losing
                        self.sell(st,rl,open_price,lots)
                    elif open_price <= stopprice:
                        self.sell(st,rl,open_price,lots)
                    elif open_price >= targetprice:
                        if partiallots > 0:
                            self.sell(st,rl,open_price,partiallots)
                    elif low <= stopprice:
                        self.sell(st,rl,stopprice,lots)
                    elif high >= targetprice:
                        if partiallots > 0:
                            self.sell(st,rl,targetprice,partiallots)
    ##==================calculating position value=============================
            position_value = 0.0
            for st in self.port:
                shares = self.transactions.loc[st.name,"volume"]
                close = closing_prices.loc[i,st.name]
                if pd.notna(close):
                    position_value += shares*close

            portfolio_value = position_value+self.money
            self.equity_curve.loc[i] = [
                self.money,
                position_value,
                portfolio_value,
                portfolio_value-self.initial_money,
            ]
        monthly_cumulative_profit = self.equity_curve["profit"].resample("ME").last()
        monthly_profit = monthly_cumulative_profit.diff()
        monthly_profit.iloc[0] = monthly_cumulative_profit.iloc[0]
        print(monthly_profit)
        print(self.transactions)
    def showresult(self):
        fig, ax = plt.subplots(figsize=(12,6))
        ax.plot(
            self.equity_curve.index,
            self.equity_curve["portfolio_value"],
            label = "Portfolio Value",
        )
        ax.plot(
            self.equity_curve.index,
            self.equity_curve["cash"],
            label = "Cash",
        )
        ax.plot(
            self.equity_curve.index,
            self.equity_curve["profit"],
            label = "Profit",
        )
        ax.set_title("Portfolio perfomance")
        ax.set_xlabel("Date")
        ax.set_ylabel("Value")
        ax.legend()
        plt.tight_layout()
        plt.show()

def backtest():
    tradable_names = ['gyfl', 'zgly', 'lxjm', 'hgkj', 'sydl']
    teststocklist = [Stock(name) for name in tradable_names]
    teststrategy = Strategy(teststocklist,"2y",100000,["macd","devour","ma"],stop = 0.95,target=1.5) ##modify timespan, buying, selling, and signal logic
    teststrategy.initialize()
    teststrategy.readandexecute()
    teststrategy.showresult()
if __name__ == "__main__":
    backtest()









