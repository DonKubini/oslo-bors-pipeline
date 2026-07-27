import pandas as pd
import yfinance as yf
import os
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from dotenv import load_dotenv

load_dotenv()

TICKER_MAP = {
    "EQNR.OL": "NO0010096985",
    "DNB.OL":  "NO0010161896",
    "TEL.OL":  "NO0010063308",
    "YAR.OL":  "NO0010208051",
    "NHY.OL":  "NO0005052605"
}

def get_db_connection():
    """Securely connects to Azure SQL using environment variables."""
    # NEVER hardcode passwords in scripts!
    server = os.getenv('AZURE_SQL_SERVER')
    database = os.getenv('AZURE_SQL_DATABASE')
    username = os.getenv('AZURE_SQL_USER')
    password = os.getenv('AZURE_SQL_PASSWORD')
    
    # Connection string for pyodbc / sqlalchemy
    conn_str = f"mssql+pyodbc://{username}:{password}@{server}/{database}?driver=ODBC+Driver+18+for+SQL+Server"
    return create_engine(conn_str)

def fetch_monthly_delta(ticker_map):
    # Get list of .OL tickers to download from yfinance
    yahoo_tickers = list(ticker_map.keys())
    print(f"Fetching latest market data for {len(yahoo_tickers)} tickers...")
    
    raw_data = yf.download(yahoo_tickers, period="2mo", interval="1mo", group_by="ticker", auto_adjust=False)
    processed_records = []
    
    for ticker in yahoo_tickers:
        try:
            ticker_data = raw_data[ticker].dropna()
            if len(ticker_data) < 2:
                continue
            
            latest_row = ticker_data.iloc[-1]
            prev_row = ticker_data.iloc[-2]
            
            ret_generic = (latest_row['Close'] - prev_row['Close']) / prev_row['Close']
            ret_adj = (latest_row['Adj Close'] - prev_row['Adj Close']) / prev_row['Adj Close']
            
            # Translate Yahoo ticker to ISIN here:
            isin_key = ticker_map.get(ticker, ticker)
            
            processed_records.append({
                'TradeDate': latest_row.name.date(),
                'Ticker': isin_key,  # Store historical ISIN in the Ticker column
                'SecurityType': 'Ordinary Shares',
                'Generic': latest_row['Close'],
                'Volume': latest_row['Volume'],
                'ReturnGeneric': ret_generic,
                'ReturnAdjGeneric': ret_adj
            })
        except Exception as e:
            print(f"Warning: Failed to process {ticker} - {str(e)}")
            
    return pd.DataFrame(processed_records)

def load_to_azure(df, engine):
    """Appends the new data to the raw_market_data table safely."""
    try:
        # Get the latest date currently in the database
        max_date_query = "SELECT MAX(TradeDate) as max_date FROM raw_market_data"
        max_date_df = pd.read_sql(max_date_query, engine)
        max_date = max_date_df.iloc[0]['max_date']

        # Filter the incoming dataframe for only newer dates
        if max_date:
            max_date = pd.to_datetime(max_date).date()
            new_records = df[df['TradeDate'] > max_date]
        else:
            new_records = df # If table is empty, all records are new

        if new_records.empty:
            print("No new records to upload. Database is already up to date.")
            return

        print(f"Uploading {len(new_records)} new records to Azure SQL...")
        new_records.to_sql('raw_market_data', engine, if_exists='append', index=False)
        print("Upload successful.")
        
    except SQLAlchemyError as e:
        print(f"Database Error: {str(e)}")

if __name__ == "__main__":
    # For MVP, we use a static list of the top Oslo Bors tickers. 
    # In the future, this could be queried dynamically.
    # oslo_tickers = ["EQNR.OL", "DNB.OL", "TEL.OL", "YAR.OL", "NHY.OL"] 
    
    try:
        # 1. Fetch Delta
        monthly_df = fetch_monthly_delta(TICKER_MAP)
        
        # 2. Connect to DB and Load
        if not monthly_df.empty:
            db_engine = get_db_connection()
            # load_to_azure(monthly_df, db_engine)
            
            print("PIPELINE SUCCESS. Sample of data to be uploaded:")
            print(monthly_df.head())
        else:
            print("No new data to upload.")
            
    except Exception as e:
        print(f"Pipeline failed: {str(e)}")