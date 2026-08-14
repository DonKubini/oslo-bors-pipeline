import pandas as pd
import numpy as np
import os
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor
import urllib
import xgboost as xgb
from dotenv import load_dotenv

load_dotenv()


def get_db_connection():
    server = os.getenv("AZURE_SQL_SERVER")
    database = os.getenv("AZURE_SQL_DATABASE")
    
    # We need the Client ID of our Managed Identity
    client_id = os.getenv("AZURE_CLIENT_ID")

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
    

def generate_signals(df):
    """
    Trains an Ensemble model on historical features and predicts returns for the latest date.
    """
    features = [
        'log_size_z', 'turnover_z', 
        'rev_1m_z', 'mom_6m_z', 'mom_12m_z', 
        'vol_3m_z', 'vol_6m_z'
    ]
    target_col = 'Target_z'
    
    df['TradeDate'] = pd.to_datetime(df['TradeDate'])
    latest_date = df['TradeDate'].max()
    
    print(f"Latest Trade Date in features: {latest_date.date()}")
    
    # Train set: All historical months before the latest date
    train_df = df[df['TradeDate'] < latest_date].dropna(subset=features + [target_col])
    # Inference set: The latest month we want predictions for
    predict_df = df[df['TradeDate'] == latest_date].dropna(subset=features)
    
    if predict_df.empty:
        print("No features available for prediction on the latest date.")
        return pd.DataFrame()
    
    X_train, y_train = train_df[features], train_df[target_col]
    X_predict = predict_df[features]
    
    print(f"Training models on {len(X_train)} historical rows...")
    
    # Instantiate models (using optimal hyperparameters from thesis tuning)
    model_ridge = Ridge(alpha=1.0, random_state=123)
    model_rf = RandomForestRegressor(max_depth=7, min_samples_leaf=20, n_estimators=100, random_state=123, n_jobs=-1)
    model_xgb = xgb.XGBRegressor(learning_rate=0.05, max_depth=2, n_estimators=100, subsample=0.6, random_state=123, n_jobs=-1)
    
    # Train
    model_ridge.fit(X_train, y_train)
    model_rf.fit(X_train, y_train)
    model_xgb.fit(X_train, y_train)
    
    # Predict
    pred_ridge = model_ridge.predict(X_predict)
    pred_rf = model_rf.predict(X_predict)
    pred_xgb = model_xgb.predict(X_predict)
    
    # Ensemble Average
    ensemble_preds = (pred_ridge + pred_rf + pred_xgb) / 3.0
    
    # Build output DataFrame
    output_df = predict_df[['TradeDate', 'Ticker']].copy()
    output_df['Predicted_Return_Z'] = ensemble_preds
    
    # Rank stocks based on predicted return (1 = highest expected return)
    output_df['Rank_Order'] = output_df['Predicted_Return_Z'].rank(ascending=False, method='min').astype(int)
    
    # Assign Buy signals to top 10 tickers
    output_df['Signal'] = np.where(output_df['Rank_Order'] <= 10, 'BUY', 'HOLD')
    
    output_df = output_df.sort_values(by='Rank_Order')
    return output_df

def save_signals_to_azure(df, engine):
    """Saves predictions to investment_signals table safely."""
    try:
        # Get the latest date currently in the database
        max_date_query = "SELECT MAX(TradeDate) as max_date FROM investment_signals"
        max_date_df = pd.read_sql(max_date_query, engine)
        max_date = max_date_df.iloc[0]['max_date']

        # Filter the incoming dataframe for only newer dates
        if max_date:
            max_date = pd.to_datetime(max_date)
            new_records = df[df['TradeDate'] > max_date]
        else:
            new_records = df

        if new_records.empty:
            print("Signals for this month already exist. Database is up to date.")
            return

        print(f"Saving {len(new_records)} predictions to Azure SQL...")
        new_records.to_sql('investment_signals', engine, if_exists='append', index=False)
        print("Predictions successfully saved!")
        
    except SQLAlchemyError as e:
        print(f"Database Error: {str(e)}")

if __name__ == "__main__":
    try:
        engine = get_db_connection()
        print("Reading engineered features from Azure SQL...")
        
        features_df = pd.read_sql("SELECT * FROM engineered_features", engine)
        
        if not features_df.empty:
            signals_df = generate_signals(features_df)
            if not signals_df.empty:
                print("\nTop 10 Investment Recommendations:")
                print(signals_df.head(10).to_string(index=False))
                
                # Save to Azure SQL (Uncomment to execute insert)
                save_signals_to_azure(signals_df, engine)
        else:
            print("engineered_features table is empty.")
            
    except Exception as e:
        print(f"Prediction script failed: {str(e)}")