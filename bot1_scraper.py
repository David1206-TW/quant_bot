import requests
import pandas as pd
from datetime import datetime
import sqlite3
import os
import time

DB_PATH = "data/quant.db"

def fetch_twse_market_data(date_str):
    print(f"啟動真實爬蟲：正在抓取證交所 {date_str} 盤後資料...")
    
    # 1. 抓取全市場收盤行情 (MI_INDEX)
    price_url = f"https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date={date_str}&type=ALLBUT0999"
    res_price = requests.get(price_url, headers={'User-Agent': 'Mozilla/5.0'})
    
    # 檢查 API 是否成功回傳資料
    if res_price.status_code != 200:
        print(f"API 請求失敗，狀態碼：{res_price.status_code}")
        return pd.DataFrame()
    
    try:
        json_data = res_price.json()
    except Exception as e:
        print(f"解析 JSON 失敗: {e}")
        return pd.DataFrame()

    if json_data.get('stat') != 'OK':
        print(f"證交所行情 API 回應異常或今日休市 ({json_data.get('stat')})")
        return pd.DataFrame()
        
    # 動態尋找個股資料所在的區塊
    price_data = None
    price_fields = None
    
    for key, value in json_data.items():
        if key.startswith('fields') and '證券代號' in value and '收盤價' in value:
            price_fields = value
            data_key = key.replace('fields', 'data')
            if data_key in json_data:
                price_data = json_data[data_key]
            break
            
    if not price_data or not price_fields:
        print("無法在 API 回應中找到行情表格，可能 API 結構變更或今日無資料。")
        return pd.DataFrame()
        
    df_price = pd.DataFrame(price_data, columns=price_fields)
    
    # 2. 抓取全市場三大法人買賣超 (T86)
    time.sleep(3) 
    inst_url = f"https://www.twse.com.tw/fund/T86?response=json&date={date_str}&selectType=ALLBUT0999"
    res_inst = requests.get(inst_url, headers={'User-Agent': 'Mozilla/5.0'})
    
    df_inst = pd.DataFrame()
    if res_inst.status_code == 200:
        try:
            inst_json = res_inst.json()
            if inst_json.get('stat') == 'OK':
                df_inst = pd.DataFrame(inst_json.get('data', []), columns=inst_json.get('fields', []))
        except:
             pass
        
    # 3. 資料清洗與合併
    df_price['收盤價'] = pd.to_numeric(df_price['收盤價'].str.replace(',', ''), errors='coerce')
    df_price['開盤價'] = pd.to_numeric(df_price['開盤價'].str.replace(',', ''), errors='coerce')
    df_price['漲跌價差'] = pd.to_numeric(df_price['漲跌價差'].str.replace(',', ''), errors='coerce')
    df_price['成交股數'] = pd.to_numeric(df_price['成交股數'].str.replace(',', ''), errors='coerce')
    
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
    
    if not df_inst.empty and '證券代號' in df_inst.columns:
        if '外陸資買賣超股數(不含外資自營商)' in df_inst.columns:
             df_inst['外陸資買賣超股數(不含外資自營商)'] = pd.to_numeric(df_inst['外陸資買賣超股數(不含外資自營商)'].str.replace(',', ''), errors='coerce')
        else:
             df_inst['外陸資買賣超股數(不含外資自營商)'] = 0

        if '投信買賣超股數' in df_inst.columns:
             df_inst['投信買賣超股數'] = pd.to_numeric(df_inst['投信買賣超股數'].str.replace(',', ''), errors='coerce')
        else:
             df_inst['投信買賣超股數'] = 0
        
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

def verify_database():
    print("\n--- 📝 資料庫寫入驗證 ---")
    if not os.path.exists(DB_PATH):
        print("❌ 錯誤：找不到資料庫檔案。")
        return
        
    conn = sqlite3.connect(DB_PATH)
    try:
        df_verify = pd.read_sql_query("SELECT * FROM bot1_limit_up_pool ORDER BY ROWID DESC LIMIT 5", conn)
        print("最新的 5 筆漲停股資料：")
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', 1000)
        pd.set_option('display.unicode.east_asian_width', True) 
        print(df_verify)
    except Exception as e:
        print(f"❌ 讀取資料庫時發生錯誤：{e}")
    finally:
        conn.close()
    print("------------------------\n")

if __name__ == "__main__":
    today_str = "20261110" # 使用有開盤交易的日期測試
    # today_str = datetime.now().strftime("%Y%m%d")
    df_market = fetch_twse_market_data(today_str)
    
    if df_market.empty:
        print("今日無交易資料 (可能為假日或 API 異常)，BOT 1 結束排程。")
    else:
        limit_up_df = df_market[(df_market['漲跌幅(%)'] >= 9.8) & (df_market['成交股數'] > 0)].copy()
        limit_up_df['trade_date'] = today_str
        
        final_cols = ['trade_date', '證券代號', '證券名稱', '收盤價', '漲跌幅(%)', '成交股數', '外資買賣超', '投信買賣超']
        final_df = limit_up_df[[c for c in final_cols if c in limit_up_df.columns]]
        
        print(f"掃描完成！今日上市共有 {len(final_df)} 檔漲停。")
        
        save_to_database(final_df)
        
        verify_database()
