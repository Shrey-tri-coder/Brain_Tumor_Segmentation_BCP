import datetime
import time
from typing import Literal

import numpy as np
import pandas as pd
import yfinance as yf
from fastapi import FastAPI, Depends, BackgroundTasks, HTTPException, Query
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from apscheduler.schedulers.background import BackgroundScheduler
from contextlib import asynccontextmanager
from pydantic import BaseModel, ConfigDict

# ==========================================
# 1. DATABASE SETUP (Infrastructure)
# ==========================================
# Using SQLite for local testing. Maps to a local file called quant_data.db
SQLALCHEMY_DATABASE_URL = "sqlite:///./quant_data.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==========================================
# 2. DATABASE MODELS (Schema)
# ==========================================
class PortfolioWeight(Base):
    __tablename__ = "portfolio_weights"
    
    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime, default=datetime.datetime.utcnow)
    ticker = Column(String, index=True)
    weight = Column(Float)
    signal = Column(String) # e.g., BUY, SELL, HOLD


class PortfolioWeightResult(BaseModel):
    """A serialized portfolio allocation result."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    date: datetime.datetime
    ticker: str
    weight: float
    signal: str


class PortfolioWeightResults(BaseModel):
    """Results and the parameters used to produce them."""

    results: list[PortfolioWeightResult]
    total: int
    returned: int
    offset: int
    limit: int | None
    parameters: dict[str, str | int | None]

# Generate the tables in the database immediately upon running
Base.metadata.create_all(bind=engine)

# ==========================================
# 3. ETL PIPELINE LOGIC (Math & Data Science)
# ==========================================
def calculate_inverse_vol_weights(tickers):
    """Fetch prices and calculate inverse-volatility portfolio weights."""
    if not tickers:
        raise ValueError("At least one ticker is required")

    data = pd.DataFrame()
    last_error = None
    for attempt in range(3):
        try:
            downloaded = yf.download(
                tickers,
                period="3mo",
                auto_adjust=False,
                progress=False,
                threads=False,
            )
            if downloaded.empty:
                raise RuntimeError("The market-data provider returned no rows")

            if isinstance(downloaded.columns, pd.MultiIndex):
                if "Adj Close" in downloaded.columns.get_level_values(0):
                    data = downloaded["Adj Close"]
                elif "Close" in downloaded.columns.get_level_values(0):
                    data = downloaded["Close"]
            elif "Adj Close" in downloaded:
                data = downloaded[["Adj Close"]].rename(columns={"Adj Close": tickers[0]})
            elif "Close" in downloaded:
                data = downloaded[["Close"]].rename(columns={"Close": tickers[0]})

            if data.empty:
                raise RuntimeError("The market-data response had no close-price columns")
            break
        except Exception as error:
            last_error = error
            if attempt < 2:
                time.sleep(2**attempt)

    if data.empty:
        raise RuntimeError(
            "Unable to download market data after 3 attempts. "
            "Yahoo Finance may be rate-limiting the request."
        ) from last_error

    requested_tickers = list(tickers)
    available_tickers = [ticker for ticker in requested_tickers if ticker in data.columns]
    data = data[available_tickers].dropna(axis="columns", how="all")
    if not available_tickers or data.shape[1] != len(requested_tickers):
        missing = sorted(set(requested_tickers) - set(data.columns))
        raise RuntimeError(f"Market data is missing ticker(s): {', '.join(missing)}")

    returns = data.pct_change().dropna(how="all")
    if len(returns) < 30:
        raise RuntimeError(
            f"At least 30 daily returns are required; received {len(returns)}"
        )
    
    # Calculate rolling volatility (standard deviation of returns)
    volatility = returns.rolling(window=30).std().iloc[-1]
    volatility = volatility.replace([np.inf, -np.inf], np.nan).dropna()
    if volatility.empty or (volatility <= 0).any():
        raise RuntimeError("Unable to calculate positive volatility for all tickers")
    
    # Inverse volatility weighting: lower risk gets higher allocation
    inv_vol = 1.0 / volatility
    weights = inv_vol / inv_vol.sum()
    return weights.to_dict()

def run_etl_job():
    """Extracts data, runs the transformation, and loads it into the SQL database."""
    print("Starting automated ETL pipeline...")
    tickers = ["BTC-USD", "ETH-USD", "GLD"]
    
    try:
        latest_weights = calculate_inverse_vol_weights(tickers)
    except Exception as e:
        print(f"ETL Failed during calculation: {e}")
        return

    db = SessionLocal()
    try:
        for ticker, weight in latest_weights.items():
            # Basic threshold logic for signals
            signal = "BUY" if weight > 0.35 else "HOLD"
            
            new_entry = PortfolioWeight(
                ticker=ticker, 
                weight=float(weight), 
                signal=signal
            )
            db.add(new_entry)
        
        db.commit()
        print("ETL job completed successfully. Database updated.")
    except Exception as e:
        db.rollback()
        print(f"Database insertion failed: {e}")
    finally:
        db.close()

# ==========================================
# 4. FASTAPI APPLICATION (Server & Deployment)
# ==========================================
# Set up the background task scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(run_etl_job, 'cron', hour=0, minute=1) # Runs automatically at 12:01 AM

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(title="Quant Portfolio API", lifespan=lifespan)

@app.get("/")
def health_check():
    return {"status": "System Online", "message": "FastAPI Quant Engine is running."}

@app.get(
    "/api/v1/weights",
    response_model=PortfolioWeightResults,
    summary="Get portfolio weight results",
)
def get_latest_weights(
    ticker: str | None = Query(None, description="Filter by ticker symbol."),
    signal: str | None = Query(
        None,
        description="Filter by signal, for example BUY, SELL, or HOLD.",
    ),
    start_date: datetime.datetime | None = Query(
        None,
        description="Only include results at or after this ISO-8601 timestamp.",
    ),
    end_date: datetime.datetime | None = Query(
        None,
        description="Only include results at or before this ISO-8601 timestamp.",
    ),
    sort_by: Literal["id", "date", "ticker", "weight", "signal"] = Query(
        "date",
        description="Field used to sort the results.",
    ),
    sort_order: Literal["asc", "desc"] = Query(
        "desc",
        description="Sort direction.",
    ),
    offset: int = Query(0, ge=0, description="Number of matching results to skip."),
    limit: int | None = Query(
        None,
        ge=1,
        le=1000,
        description="Maximum results to return. Omit to return all matches.",
    ),
    db: Session = Depends(get_db),
):
    """Returns portfolio allocations with filtering, sorting, and pagination."""
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="start_date must be before or equal to end_date",
        )

    query = db.query(PortfolioWeight)
    if ticker:
        query = query.filter(PortfolioWeight.ticker == ticker)
    if signal:
        query = query.filter(PortfolioWeight.signal == signal)
    if start_date:
        query = query.filter(PortfolioWeight.date >= start_date)
    if end_date:
        query = query.filter(PortfolioWeight.date <= end_date)

    sort_column = getattr(PortfolioWeight, sort_by)
    query = query.order_by(
        sort_column.asc() if sort_order == "asc" else sort_column.desc()
    )

    total = query.count()
    if limit is not None:
        query = query.offset(offset).limit(limit)
    else:
        query = query.offset(offset)
    records = query.all()

    return {
        "results": records,
        "total": total,
        "returned": len(records),
        "offset": offset,
        "limit": limit,
        "parameters": {
            "ticker": ticker,
            "signal": signal,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "offset": offset,
            "limit": limit,
        },
    }

@app.post("/api/v1/trigger-etl")
def trigger_etl_manually(background_tasks: BackgroundTasks):
    """Allows a user to manually run the ETL pipeline asynchronously."""
    background_tasks.add_task(run_etl_job)
    return {"status": "Processing", "message": "ETL job triggered in the background."}
