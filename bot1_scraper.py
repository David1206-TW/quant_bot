import requests
import pandas as pd
from datetime import datetime
import sqlite3
import os

# 設定 SQLite 資料庫路徑
DB_PATH = "data/quant.db"

def fetch_limit_up_stocks():
    """抓取當日真實漲停鎖死的股票名單與基礎籌碼"""
    print(f"[{datetime.now()}] BOT 1 啟動：開始掃描全市場漲停板...")
    
    # 這裡實務上會呼叫證交所 API 或 Yahoo API
    # 為了示範，我們先模擬一組從 API 抓回來的原始盤後數據
    mock_market_data = [
        {"symbol": "2330", "name": "台積電", "close": 1050, "change_pct": 2.1, "volume": 35000, "foreign_buy": 1200, "trust_buy": 500},
        {"symbol": "3037", "name": "欣興", "close": 180, "change_pct": 9.95, "volume": 42000, "foreign_buy": 3500, "trust_buy": 1200}, # 真漲停
        {"symbol": "2368", "name": "金像電", "close": 95, "change_pct": 8.5, "volume": 15000, "foreign_buy": 800, "trust_buy": -200}, # 假漲停(尾盤打開)
        {"symbol": "3231", "name": "緯創", "close": 115, "change_pct": 9.91, "volume": 85000, "foreign_buy": -5000, "trust_buy": 3000} # 真漲停
    ]
    df = pd.DataFrame(mock_market_data)

    # 核心過濾邏輯：只抓漲幅 >= 9.8% 的「真漲停」
    limit_up_df = df[df['change_pct'] >= 9.8].copy()
    
    # 加上時間標籤
    today_str = datetime.now().strftime("%Y-%m-%d")
    limit_up_df['trade_date'] = today_str
    
    print(f"掃描完成！今日大盤共有 {len(limit_up_df)} 檔真實漲停。")
    return limit_up_df

def save_to_database(df):
    """將漲停名單與籌碼存入 SQLite 資料庫"""
    # 確保 data 資料夾存在
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    
    # 將 DataFrame 寫入資料表 (若表格存在則附加在後面)
    df.to_sql('bot1_limit_up_pool', conn, if_exists='append', index=False)
    
    conn.commit()
    conn.close()
    print("已將資料寫入 SQLite 資料庫 (bot1_limit_up_pool 表格)。")

if __name__ == "__main__":
    # 1. 抓取資料
    df_limit_up = fetch_limit_up_stocks()
    
    # 防呆機制：如果今天大跌，0 檔漲停，直接結束
    if df_limit_up.empty:
        print("今日無任何漲停股，BOT 1 提早休息。")
    else:
        # 2. 存入資料庫
        save_to_database(df_limit_up)