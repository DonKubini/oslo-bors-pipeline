import sys
import extract
import transform
import predict
import pandas as pd

def run_monthly_pipeline():
    print("==========================================")
    print("STARTING OSLO BØRS AUTOMATED PIPELINE")
    print("==========================================")
    
    # Step 1: Extraction (Fetch delta data & update raw table)
    print("\n--- PHASE 1: EXTRACTION ---")
    TICKER_MAP = {
    "EQNR.OL": "NO0010096985",
    "DNB.OL":  "NO0010161896",
    "TEL.OL":  "NO0010063308",
    "YAR.OL":  "NO0010208051",
    "NHY.OL":  "NO0005052605"
    }
    engine = extract.get_db_connection()
    monthly_raw_df = extract.fetch_monthly_delta(TICKER_MAP)
    if not monthly_raw_df.empty:
        extract.load_to_azure(monthly_raw_df, engine)
    
    # Step 2: Transformation (Recalculate rolling features)
    print("\n--- PHASE 2: FEATURE ENGINEERING ---")
    raw_df = pd.read_sql("SELECT * FROM raw_market_data", engine)
    ml_ready_df = transform.engineer_features(raw_df)
    ml_ready_df.to_sql('engineered_features', engine, if_exists='replace', index=False)
    
    # Step 3: Inference (Train models & generate stock picks)
    print("\n--- PHASE 3: ML INFERENCE & SIGNALS ---")
    features_df = pd.read_sql("SELECT * FROM engineered_features", engine)
    signals_df = predict.generate_signals(features_df)
    if not signals_df.empty:
        predict.save_signals_to_azure(signals_df, engine)
        
    print("\n==========================================")
    print("PIPELINE EXECUTED SUCCESSFULLY")
    print("==========================================")

if __name__ == "__main__":
    run_monthly_pipeline()