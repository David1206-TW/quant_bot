import requests
import pandas as pd
from datetime import datetime
import sqlite3
import os
import time

DB_PATH = "data/quant.db"

def fetch_twse_market_data(date_str):
    """抓取【上市】證交所資料"""
    print(f"啟動真實爬蟲：正在抓取 證交所(上市) {date_str} 盤後資料...")
    price_url = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?response=json&date={date_str}&type=ALLBUT0999"
    res_price = requests.get(price_url, headers={'User-Agent': 'Mozilla/5.0'})
    
    if res_price.status_code != 200: return pd.DataFrame()
    try: json_data = res_price.json()
    except: return pd.DataFrame()

    price_data, price_fields = None, None
    for table in json_data.get('tables', []):
        fields = table.get('fields', [])
        if '證券代號' in fields and '收盤價' in fields:
            price_fields = fields
            price_data = table.get('data', [])
            break
            
    if not price_data: return pd.DataFrame()
    df_price = pd.DataFrame(price_data, columns=price_fields)
    
    time.sleep(2) 
    inst_url = f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={date_str}&selectType=ALLBUT0999"
    res_inst = requests.get(inst_url, headers={'User-Agent': 'Mozilla/5.0'})
    df_inst = pd.DataFrame()
    
    try:
        inst_json = res_inst.json()
        for table in inst_json.get('tables', []):
            fields = table.get('fields', [])
            if '證券代號' in fields and '投信買賣超股數' in fields:
                df_inst = pd.DataFrame(table.get('data', []), columns=fields)
                break
    except: pass

    # 清洗上市資料
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

def fetch_tpex_market_data(date_str):
    """抓取【上櫃】櫃買中心資料 (需轉換為民國年)"""
    # 將 20261110 轉為 115/11/10
    roc_year = int(date_str[:4]) - 1911
    roc_date = f"{roc_year}/{date_str[4:6]}/{date_str[6:8]}"
    print(f"啟動真實爬蟲：正在抓取 櫃買中心(上櫃) {roc_date} 盤後資料...")
    
    # 櫃買中心收盤行情 API
    price_url = f"https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&o=json&d={roc_date}"
    res_price = requests.get(price_url, headers={'User-Agent': 'Mozilla/5.0'})
    if res_price.status_code != 200: return pd.DataFrame()
    
    try:
        json_data = res_price.json()
        if 'aaData' not in json_data or not json_data['aaData']: return pd.DataFrame()
        # TPEx 欄位依序：0代號, 1名稱, 2收盤, 3漲跌, 4開盤, 5最高, 6最低, 7均價, 8成交股數
        df_price = pd.DataFrame(json_data['aaData'])
        df_price = df_price.rename(columns={0: '證券代號', 1: '證券名稱', 2: '收盤價', 3: '漲跌價差_原始', 8: '成交股數'})
    except: return pd.DataFrame()

    time.sleep(2)
    # 櫃買中心三大法人 API
    inst_url = f"https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&o=json&se=EW&t=D&d={roc_date}"
    res_inst = requests.get(inst_url, headers={'User-Agent': 'Mozilla/5.0'})
    df_inst = pd.DataFrame()
    
    try:
        if res_inst.status_code == 200:
            inst_data = res_inst.json().get('aaData', [])
            if inst_data:
                # TPEx 法人欄位依序：0代號, 1名稱, 4外資買賣超, 10投信買賣超 (依據目前 API 結構)
                df_inst = pd.DataFrame(inst_data)
                df_inst = df_inst.rename(columns={0: '證券代號', 4: '外資買賣超', 10: '投信買賣超'})
    except: pass

    # 清洗上櫃資料
    df_price['收盤價'] = pd.to_numeric(df_price['收盤價'].astype(str).str.replace(',', ''), errors='coerce')
    df_price['成交股數'] = pd.to_numeric(df_price['成交股數'].astype(str).str.replace(',', ''), errors='coerce')
    
    def calc_tpex_pct(row):
        try:
            diff_str = str(row['漲跌價差_原始']).replace(',', '').strip()
            # 櫃買中心的漲跌符號直接附在數字前面，例如 "+1.5", "-0.5", "X0.0"
            sign = 1 if '+' in diff_str else (-1 if '-' in diff_str else 0)
            diff_val = float(''.join([c for c in diff_str if c.isdigit() or c == '.']))
            diff = diff_val * sign
            prev_close = row['收盤價'] - diff
            return (diff / prev_close) * 100 if prev_close > 0 else 0.0
        except: return 0.0

    df_price['漲跌幅(%)'] = df_price.apply(calc_tpex_pct, axis=1)
    
    if not df_inst.empty and '證券代號' in df_inst.columns:
        df_inst['外資買賣超'] = pd.to_numeric(df_inst['外資買賣超'].astype(str).str.replace(',', ''), errors='coerce')
        df_inst['投信買賣超'] = pd.to_numeric(df_inst['投信買賣超'].astype(str).str.replace(',', ''), errors='coerce')
        df_market = pd.merge(df_price, df_inst[['證券代號', '外資買賣超', '投信買賣超']], on='證券代號', how='left')
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
    if not os.path.exists(DB_PATH):
        print("❌ 錯誤：找不到資料庫檔案。")
        return
    conn = sqlite3.connect(DB_PATH)
    try:
        df_verify = pd.read_sql_query("SELECT * FROM bot1_limit_up_pool ORDER BY ROWID DESC LIMIT 8", conn)
        print("最新的 8 筆漲停股資料：")
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', 1000)
        pd.set_option('display.unicode.east_asian_width', True) 
        print(df_verify)
    except Exception as e: print(f"❌ 讀取資料庫時發生錯誤：{e}")
    finally: conn.close()
    print("------------------------\n")

if __name__ == "__main__":
    today_str = "20261110"  # 測試日期
    # today_str = datetime.now().strftime("%Y%m%d")
    
    # 分別抓取上市與上櫃資料
    df_twse = fetch_twse_market_data(today_str)
    df_tpex = fetch_tpex_market_data(today_str)
    
    # 組合全市場大表
    df_all = pd.concat([df_twse, df_tpex], ignore_index=True)
    
    if df_all.empty:
        print("今日全市場無交易資料 (可能為假日或 API 異常)，BOT 1 結束排程。")
    else:
        # 在全市場中篩選漲停板 (漲幅 >= 9.8% 且有成交量)
        limit_up_df = df_all[(df_all['漲跌幅(%)'] >= 9.8) & (df_all['成交股數'] > 0)].copy()
        limit_up_df['trade_date'] = today_str
        
        final_cols = ['trade_date', '證券代號', '證券名稱', '收盤價', '漲跌幅(%)', '成交股數', '外資買賣超', '投信買賣超']
        final_df = limit_up_df[[c for c in final_cols if c in limit_up_df.columns]]
        
        print(f"掃描完成！今日【上市+上櫃】共有 {len(final_df)} 檔漲停。")
        
        save_to_database(final_df)
        verify_database()
