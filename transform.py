import pandas as pd
import numpy as np
import os
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from dotenv import load_dotenv
import urllib

load_dotenv()

def get_db_connection():
    server = os.environ["AZURE_SQL_SERVER"]
    database = os.environ["AZURE_SQL_DATABASE"]
    
    # We need the Client ID of our Managed Identity
    client_id = os.environ["AZURE_CLIENT_ID"]

    # The passwordless ODBC connection string
    conn_str = (
        f"Driver={{ODBC Driver 18 for SQL Server}};"
        f"Server=tcp:{server},1433;"
        f"Database={database};"
        f"Authentication=ActiveDirectoryMsi;"
        f"UID={client_id};"
        f"Encrypt=yes;"
    )
    
    # SQLAlchemy requires ODBC connection strings to be URL-encoded
    quoted_conn_str = urllib.parse.quote_plus(conn_str)
    engine = create_engine(f"mssql+pyodbc:///?odbc_connect={quoted_conn_str}")
    
    return engine
    

def engineer_features(df):
    print("Calculating ML features...")
    df['TradeDate'] = pd.to_datetime(df['TradeDate'])
    df.sort_values(by=['Ticker', 'TradeDate'], inplace=True)

    # 1. Target Winsorization (1st and 99th percentile)
    lower = df['ReturnAdjGeneric'].quantile(0.01)
    upper = df['ReturnAdjGeneric'].quantile(0.99)
    df['ReturnAdjGeneric_win'] = df['ReturnAdjGeneric'].clip(lower=lower, upper=upper)

    # Shift target to t+1
    df['Target_raw'] = df.groupby('Ticker')['ReturnAdjGeneric'].shift(-1)
    df['Target'] = df.groupby('Ticker')['ReturnAdjGeneric_win'].shift(-1)

    # 2. Proxies for Size and Liquidity
    df['log_size'] = np.log((df['Generic'] * df['Volume']).replace(0, np.nan))
    df['turnover'] = df['Volume'] 

    # 3. Momentum & Reversal
    df['rev_1m'] = df.groupby('Ticker')['ReturnAdjGeneric_win'].shift(1)
    df['mom_6m'] = df.groupby('Ticker')['ReturnAdjGeneric_win'].transform(lambda x: x.shift(2).rolling(5).sum())
    df['mom_12m'] = df.groupby('Ticker')['ReturnAdjGeneric_win'].transform(lambda x: x.shift(2).rolling(11).sum())

    # 4. Volatility
    df['vol_3m'] = df.groupby('Ticker')['ReturnAdjGeneric_win'].transform(lambda x: x.shift(1).rolling(3).std())
    df['vol_6m'] = df.groupby('Ticker')['ReturnAdjGeneric_win'].transform(lambda x: x.shift(1).rolling(6).std())

    # 5. Cross-Sectional Z-Scoring
    features_to_zscore = ['log_size', 'turnover', 'rev_1m', 'mom_6m', 'mom_12m', 'vol_3m', 'vol_6m', 'Target']
    for col in features_to_zscore:
        df[f'{col}_z'] = df.groupby('TradeDate')[col].transform(lambda x: (x - x.mean()) / x.std())

    # 6. Cleanup NaNs from rolling windows
    final_cols = ['TradeDate', 'Ticker', 'Target_raw'] + [f'{col}_z' for col in features_to_zscore]
    clean_df = df.dropna(subset=['Target_z', 'mom_12m_z'])[final_cols]
    
    return clean_df

if __name__ == "__main__":
    try:
        engine = get_db_connection()
        print("Downloading raw historical data from Azure...")
        
        # Fetch all raw data to compute rolling features
        raw_df = pd.read_sql("SELECT * FROM raw_market_data", engine)
        
        if raw_df.empty:
            print("No raw data found. Exiting.")
        else:
            ml_ready_df = engineer_features(raw_df)
            
            print(f"Uploading {len(ml_ready_df)} engineered rows back to Azure...")
            # We use if_exists='replace' for this initial bulk run. 
            # Later, we will optimize this to 'append' for monthly runs.
            ml_ready_df.to_sql('engineered_features', engine, if_exists='replace', index=False)
            print("Transformation complete! The Gold layer is ready for ML.")
            
    except Exception as e:
        print(f"Pipeline failed: {str(e)}")