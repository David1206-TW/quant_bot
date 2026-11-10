import requests
import pandas as pd
from datetime import datetime
import sqlite3
import os
import time

DB_PATH = "data/quant.db"

def fetch_twse_market_data(date_str):
    """
    向台灣證交所抓取全市場「收盤行情」與「三大法人」資料
    date_str 格式需為 YYYYMMDD，例如 20231025
    """
    print(f"啟動真實爬蟲：正在抓取證交所 {date_str} 盤後資料...")
    
    # 1. 抓取全市場收盤行情 (MI_INDEX)
    price_url = f"https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date={date_str}&type=ALLBUT0999"
    res_price = requests.get(price_url, headers={'User-Agent': 'Mozilla/5.0'})
    
    if res_price.json()['stat'] != 'OK':
        print(f"證交所行情 API 回應異常或今日休市 ({res_price.json()['stat']})")
        return pd.DataFrame()
        
    # 找出個股資料所在的區塊 (通常是 data[9] 或 data[8]，根據欄位特徵判定)
    price_data = next(data for data in res_price.json()['data9'] if len(data) > 10) if 'data9' in res_price.json() else res_price.json()['data8']
    price_fields = res_price.json()['fields9'] if 'fields9' in res_price.json() else res_price.json()['fields8']
    
    df_price = pd.DataFrame(price_data, columns=price_fields)
    
    # 2. 抓取全市場三大法人買賣超 (T86)
    time.sleep(3) # 禮貌性延遲，避免密集請求被擋
    inst_url = f"https://www.twse.com.tw/fund/T86?response=json&date={date_str}&selectType=ALLBUT0999"
    res_inst = requests.get(inst_url, headers={'User-Agent': 'Mozilla/5.0'})
    
    df_inst = pd.DataFrame()
    if res_inst.json()['stat'] == 'OK':
        df_inst = pd.DataFrame(res_inst.json()['data'], columns=res_inst.json()['fields'])
        
    # 3. 資料清洗與合併
    # 清理逗號並轉為數值
    df_price['收盤價'] = pd.to_numeric(df_price['收盤價'].str.replace(',', ''), errors='coerce')
    df_price['開盤價'] = pd.to_numeric(df_price['開盤價'].str.replace(',', ''), errors='coerce')
    df_price['漲跌價差'] = pd.to_numeric(df_price['漲跌價差'].str.replace(',', ''), errors='coerce')
    df_price['成交股數'] = pd.to_numeric(df_price['成交股數'].str.replace(',', ''), errors='coerce')
    
    # 計算漲跌幅 (還原昨收 = 收盤價 -/+ 漲跌價差)
    # 注意：證交所的漲跌欄位會帶有 HTML 標籤標示紅綠，這裡做簡化精算
    def calc_change_pct(row):
        try:
            sign = 1 if 'red' in str(row['漲跌(+/-)']) else (-1 if 'green' in str(row['漲跌(+/-)']) else 0)
            diff = row['漲跌價差'] * sign
            prev_close = row['收盤價'] - diff
            if prev_close > 0:
                return (diff / prev_close) * 100
            return 0.0
        except:
            return 0.0
            
    df_price['漲跌幅(%)'] = df_price.apply(calc_change_pct, axis=1)
    
    # 合併三大法人資料 (透過證券代號)
    if not df_inst.empty:
        df_inst['外陸資買賣超股數(不含外資自營商)'] = pd.to_numeric(df_inst['外陸資買賣超股數(不含外資自營商)'].str.replace(',', ''), errors='coerce')
        df_inst['投信買賣超股數'] = pd.to_numeric(df_inst['投信買賣超股數'].str.replace(',', ''), errors='coerce')
        
        # 只取需要的欄位合併
        df_inst_clean = df_inst[['證券代號', '外陸資買賣超股數(不含外資自營商)', '投信買賣超股數']]
        df_inst_clean.columns = ['證券代號', '外資買賣超', '投信買賣超']
        df_market = pd.merge(df_price, df_inst_clean, on='證券代號', how='left')
    else:
        df_market = df_price
        df_market['外資買賣超'] = 0
        df_market['投信買賣超'] = 0

    return df_market

def save_to_database(df):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    df.to_sql('bot1_limit_up_pool', conn, if_exists='append', index=False)
    conn.commit()
    conn.close()
    print("✅ 已將真實漲停與籌碼資料寫入 SQLite (bot1_limit_up_pool)。")

if __name__ == "__main__":
    # 使用當天日期 (轉換為民國年 YYYYMMDD，但 API 現在支援西元年)
    today_str = datetime.now().strftime("%Y%m%d")
    
    # 1. 抓取全市場資料
    df_market = fetch_twse_market_data(today_str)
    
    if df_market.empty:
        print("今日無交易資料 (可能為假日或 API 異常)，BOT 1 結束排程。")
    else:
        # 2. 嚴格篩選條件：漲幅 >= 9.8% 且成交量大於 0 的真漲停股
        limit_up_df = df_market[(df_market['漲跌幅(%)'] >= 9.8) & (df_market['成交股數'] > 0)].copy()
        limit_up_df['trade_date'] = today_str
        
        # 整理最終要輸出的乾淨欄位
        final_cols = ['trade_date', '證券代號', '證券名稱', '收盤價', '漲跌幅(%)', '成交股數', '外資買賣超', '投信買賣超']
        final_df = limit_up_df[[c for c in final_cols if c in limit_up_df.columns]]
        
        print(f"掃描完成！今日上市共有 {len(final_df)} 檔漲停。")
        print(final_df.head())
        
        # 3. 寫入資料庫
        save_to_database(final_df)
