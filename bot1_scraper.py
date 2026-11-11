import requests
import pandas as pd
from datetime import datetime
import sqlite3
import os
import time

DB_PATH = "data/quant.db"

def fetch_twse_market_data(date_str):
    print(f"啟動真實爬蟲：正在抓取 證交所(上市) {date_str} 盤後資料...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    price_url = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?response=json&date={date_str}&type=ALLBUT0999"
    res_price = requests.get(price_url, headers=headers)
    if res_price.status_code != 200: return pd.DataFrame()
    
    json_data = res_price.json()
    price_data, price_fields = None, None
    for table in json_data.get('tables', []):
        fields = table.get('fields', [])
        if '證券代號' in fields and '收盤價' in fields:
            price_fields, price_data = fields, table.get('data', [])
            break
            
    if not price_data: return pd.DataFrame()
    df_price = pd.DataFrame(price_data, columns=price_fields)
    
    time.sleep(2) 
    inst_url = f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={date_str}&selectType=ALLBUT0999"
    res_inst = requests.get(inst_url, headers=headers)
    df_inst = pd.DataFrame()
    
    if res_inst.status_code == 200:
        inst_json = res_inst.json()
        for table in inst_json.get('tables', []):
            fields = table.get('fields', [])
            if '證券代號' in fields and '投信買賣超股數' in fields:
                df_inst = pd.DataFrame(table.get('data', []), columns=fields)
                break

    df_price['證券代號'] = df_price['證券代號'].astype(str).str.strip()
    df_price['收盤價'] = pd.to_numeric(df_price['收盤價'].astype(str).str.replace(',', ''), errors='coerce')
    df_price['漲跌價差'] = pd.to_numeric(df_price['漲跌價差'].astype(str).str.replace(',', ''), errors='coerce')
    df_price['成交股數'] = pd.to_numeric(df_price['成交股數'].astype(str).str.replace(',', ''), errors='coerce')
    
    def calc_twse_pct(row):
        try:
            change_text = str(row['漲跌(+/-)'])
            sign = 1 if ('+' in change_text or 'red' in change_text) else (-1 if ('-' in change_text or 'green' in change_text) else 0)
            diff = row['漲跌價差'] * sign
            prev_close = row['收盤價'] - diff
            return (diff / prev_close) * 100 if prev_close > 0 else 0.0
        except: return 0.0
            
    df_price['漲跌幅(%)'] = df_price.apply(calc_twse_pct, axis=1)
    
    if not df_inst.empty and '證券代號' in df_inst.columns:
        df_inst['證券代號'] = df_inst['證券代號'].astype(str).str.strip()
        if '外陸資買賣超股數(不含外資自營商)' in df_inst.columns:
            df_inst['外資買賣超'] = pd.to_numeric(df_inst['外陸資買賣超股數(不含外資自營商)'].astype(str).str.replace(',', ''), errors='coerce')
        else: df_inst['外資買賣超'] = 0
            
        if '投信買賣超股數' in df_inst.columns:
            df_inst['投信買賣超'] = pd.to_numeric(df_inst['投信買賣超股數'].astype(str).str.replace(',', ''), errors='coerce')
        else: df_inst['投信買賣超'] = 0
            
        df_market = pd.merge(df_price, df_inst[['證券代號', '外資買賣超', '投信買賣超']], on='證券代號', how='left')
    else:
        df_market = df_price
        df_market['外資買賣超'], df_market['投信買賣超'] = 0, 0

    return df_market

def fetch_tpex_market_data():
    print(f"啟動真實爬蟲：正在抓取 櫃買中心(上櫃) OpenAPI 最新盤後資料...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    # 1. 上櫃價格
    price_url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
    res_price = requests.get(price_url, headers=headers)
    df_price = pd.DataFrame()
    
    if res_price.status_code == 200:
        try:
            raw_data = res_price.json()
            if raw_data:
                df_price = pd.DataFrame(raw_data)
                if 'SecuritiesCompanyCode' in df_price.columns:
                    df_price = df_price[['SecuritiesCompanyCode', 'CompanyName', 'Close', 'Change', 'TradingShares']]
                else:
                    df_price = df_price.iloc[:, [1, 2, 3, 4, 8]]
                df_price.columns = ['證券代號', '證券名稱', '收盤價', '漲跌價差_原始', '成交股數']
        except Exception as e: print(f"解析上櫃價格失敗: {e}")

    # 2. 上櫃法人
    time.sleep(2)
    inst_url = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"
    res_inst = requests.get(inst_url, headers=headers)
    df_inst = pd.DataFrame()
    
    if res_inst.status_code == 200:
        try:
            raw_inst = res_inst.json()
            if raw_inst:
                df_inst = pd.DataFrame(raw_inst)
                if len(df_inst.columns) >= 12:
                    df_inst = df_inst.iloc[:, [1, 5, 11]]
                    df_inst.columns = ['證券代號', '外資買賣超', '投信買賣超']
        except Exception as e: print(f"解析上櫃法人失敗: {e}")

    if df_price.empty: return pd.DataFrame()

    df_price['證券代號'] = df_price['證券代號'].astype(str).str.strip()
    df_price['收盤價'] = pd.to_numeric(df_price['收盤價'].astype(str).str.replace(',', ''), errors='coerce')
    df_price['成交股數'] = pd.to_numeric(df_price['成交股數'].astype(str).str.replace(',', ''), errors='coerce')
    
    def calc_tpex_pct(row):
        try:
            diff = float(str(row['漲跌價差_原始']).replace(',', '').strip())
            prev_close = row['收盤價'] - diff
            return (diff / prev_close) * 100 if prev_close > 0 else 0.0
        except: return 0.0

    df_price['漲跌幅(%)'] = df_price.apply(calc_tpex_pct, axis=1)
    
    if not df_inst.empty and '證券代號' in df_inst.columns:
        df_inst['證券代號'] = df_inst['證券代號'].astype(str).str.strip()
        df_inst['外資買賣超'] = pd.to_numeric(df_inst['外資買賣超'].astype(str).str.replace(',', ''), errors='coerce')
        df_inst['投信買賣超'] = pd.to_numeric(df_inst['投信買賣超'].astype(str).str.replace(',', ''), errors='coerce')
        df_market = pd.merge(df_price, df_inst, on='證券代號', how='left')
    else:
        df_market = df_price
        df_market['外資買賣超'], df_market['投信買賣超'] = 0, 0

    return df_market

def save_to_database(df):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    df.to_sql('bot1_limit_up_pool', conn, if_exists='append', index=False)
    conn.commit()
    conn.close()
    print("✅ 已將真實漲停與籌碼資料寫入 SQLite (bot1_limit_up_pool)。")

def verify_database():
    print("\n--- 📝 資料庫寫入驗證 ---")
    if not os.path.exists(DB_PATH): return
    conn = sqlite3.connect(DB_PATH)
    try:
        df_verify = pd.read_sql_query("SELECT * FROM bot1_limit_up_pool ORDER BY ROWID DESC LIMIT 15", conn)
        print("最新的 15 筆漲停股資料 (已過濾權證/ETF，僅保留正規股票)：")
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', 1000)
        pd.set_option('display.unicode.east_asian_width', True) 
        print(df_verify)
    except Exception as e: print(f"❌ 讀取資料庫時發生錯誤：{e}")
    finally: conn.close()
    print("------------------------\n")

if __name__ == "__main__":
    today_str = datetime.now().strftime("%Y%m%d") 
    
    df_twse = fetch_twse_market_data(today_str)
    df_tpex = fetch_tpex_market_data() 
    
    df_all = pd.concat([df_twse, df_tpex], ignore_index=True)
    
    if df_all.empty:
        print("今日全市場無交易資料，BOT 1 結束排程。")
    else:
        # ★ 關鍵過濾：只保留代碼為 4 碼的標的 (剃除 6 碼的權證、ETN、ETF)
        df_all = df_all[df_all['證券代號'].str.len() == 4]
        
        limit_up_df = df_all[(df_all['漲跌幅(%)'] >= 9.8) & (df_all['成交股數'] > 0)].copy()
        limit_up_df['trade_date'] = today_str
        
        final_cols = ['trade_date', '證券代號', '證券名稱', '收盤價', '漲跌幅(%)', '成交股數', '外資買賣超', '投信買賣超']
        final_df = limit_up_df[[c for c in final_cols if c in limit_up_df.columns]]
        final_df = final_df.fillna({'外資買賣超': 0, '投信買賣超': 0})
        
        print(f"掃描完成！今日【上市+上櫃】共有 {len(final_df)} 檔正規股票漲停。")
        save_to_database(final_df)
        verify_database()
