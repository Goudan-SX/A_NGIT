"""交易风控特征工程：训练与推理共用。"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

NUMERIC_FEATURES = [
    "Amount",
    "LogAmount",
    "CreditLimit",
    "AmountToLimit",
    "AmountOverLimit",
    "CustomerAge",
    "AnnualIncome",
    "MerchantRating",
    "TransactionHour",
    "TransactionDayOfWeek",
    "TransactionMonth",
    "IsNight",
    "IsInternational",
    "StateMismatch",
    "CityMismatch",
    "CardExpired",
    "CustomerTenureYears",
    "MerchantRiskNum",
]

CATEGORICAL_FEATURES = [
    "CardType",
    "CardNetwork",
    "CardStatus",
    "Contactless",
    "CardMode",
    "CustomerSegment",
    "AccountType",
    "PaymentMethod",
    "TransactionChannel",
    "DeviceType",
    "TransactionStatus",
    "MerchantRiskLevel",
    "MerchantCategory",
    "MerchantStatus",
]

FEATURE_COLUMNS = NUMERIC_FEATURES + CATEGORICAL_FEATURES

_MERCHANT_RISK_MAP = {"Low": 0, "Medium": 1, "High": 2}


def _to_number(series: pd.Series, default: float = 0.0) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(default)


def engineer_frame(frame: pd.DataFrame) -> pd.DataFrame:
    df = frame.copy()

    amount = _to_number(df.get("Transaction_Amount", pd.Series(index=df.index, dtype=float)))
    credit = _to_number(df.get("Credit_Limit", pd.Series(index=df.index, dtype=float)))
    credit = credit.clip(lower=1)
    txn_date = pd.to_datetime(df.get("Transaction_Date"), errors="coerce")
    txn_time = pd.to_datetime(df.get("Transaction_Time"), format="%H:%M:%S", errors="coerce")
    hour = txn_time.dt.hour.fillna(0).astype(int)
    expiry = pd.to_datetime(df.get("Expiry_Date"), errors="coerce")
    customer_since = pd.to_datetime(df.get("Customer_Since"), errors="coerce")

    result = pd.DataFrame(index=df.index)
    result["Amount"] = amount
    result["LogAmount"] = np.log1p(amount.clip(lower=0))
    result["CreditLimit"] = credit
    result["AmountToLimit"] = (amount / credit).replace([np.inf, -np.inf], 0).fillna(0)
    result["AmountOverLimit"] = (amount > credit).astype(int)
    age_series = df.get("Customer_Age", df.get("Age", pd.Series(0, index=df.index)))
    result["CustomerAge"] = _to_number(age_series)
    result["AnnualIncome"] = _to_number(df.get("Annual_Income"))
    result["MerchantRating"] = _to_number(df.get("Merchant_Rating"))
    result["TransactionHour"] = hour
    result["TransactionDayOfWeek"] = txn_date.dt.dayofweek.fillna(0).astype(int)
    result["TransactionMonth"] = txn_date.dt.month.fillna(0).astype(int)
    result["IsNight"] = (hour < 6).astype(int)
    result["IsInternational"] = _to_number(df.get("Is_International")).astype(int)
    result["StateMismatch"] = (df.get("Customer_State", "").astype(str) != df.get("Merchant_State", "").astype(str)).astype(int)
    result["CityMismatch"] = (df.get("Customer_City", "").astype(str) != df.get("Merchant_City", "").astype(str)).astype(int)
    result["CardExpired"] = ((expiry < txn_date) & expiry.notna() & txn_date.notna()).astype(int)
    tenure = (txn_date - customer_since).dt.days / 365.0
    result["CustomerTenureYears"] = tenure.clip(lower=0).fillna(0)
    result["MerchantRiskNum"] = df.get("Merchant_Risk_Level", pd.Series(index=df.index)).map(_MERCHANT_RISK_MAP).fillna(0)

    result["CardType"] = df.get("Card_Type", "Unknown").fillna("Unknown").astype(str)
    result["CardNetwork"] = df.get("Card_Network", "Unknown").fillna("Unknown").astype(str)
    result["CardStatus"] = df.get("Card_Status", "Unknown").fillna("Unknown").astype(str)
    result["Contactless"] = df.get("Contactless", "Unknown").fillna("Unknown").astype(str)
    result["CardMode"] = df.get("Card_Mode", "Unknown").fillna("Unknown").astype(str)
    result["CustomerSegment"] = df.get("Customer_Segment", "Unknown").fillna("Unknown").astype(str)
    result["AccountType"] = df.get("Account_Type", "Unknown").fillna("Unknown").astype(str)
    result["PaymentMethod"] = df.get("Payment_Method", "Unknown").fillna("Unknown").astype(str)
    result["TransactionChannel"] = df.get("Transaction_Channel", "Unknown").fillna("Unknown").astype(str)
    result["DeviceType"] = df.get("Device_Type", "Unknown").fillna("Unknown").astype(str)
    result["TransactionStatus"] = df.get("Transaction_Status", "Unknown").fillna("Unknown").astype(str)
    result["MerchantRiskLevel"] = df.get("Merchant_Risk_Level", "Unknown").fillna("Unknown").astype(str)
    result["MerchantCategory"] = df.get("Merchant_Category", "Unknown").fillna("Unknown").astype(str)
    result["MerchantStatus"] = df.get("Merchant_Status", "Unknown").fillna("Unknown").astype(str)
    return result[FEATURE_COLUMNS]


def load_tables(base_dir: str) -> pd.DataFrame:
    import os

    frame = pd.read_csv(os.path.join(base_dir, "Transaction_Data_250k.csv"))
    cards = pd.read_csv(os.path.join(base_dir, "Cards_Data.csv"))
    customers = pd.read_csv(os.path.join(base_dir, "Cusmtomer_data.csv"))
    merchants = pd.read_csv(os.path.join(base_dir, "merchant_table.csv"))
    frame = frame.merge(cards, on="Card_ID", how="left", suffixes=("", "_card"))
    frame = frame.merge(customers, on="Customer_ID", how="left", suffixes=("", "_customer"))
    frame = frame.merge(merchants, on="Merchant_ID", how="left", suffixes=("", "_merchant"))
    return frame


def raw_input_to_frame(payload: dict[str, Any]) -> pd.DataFrame:
    """把 API 请求转换为训练同结构的单行 DataFrame。"""
    row = {
        "Transaction_Amount": payload.get("Transaction_Amount", payload.get("amount", 0)),
        "Transaction_Date": payload.get("Transaction_Date", payload.get("date")),
        "Transaction_Time": payload.get("Transaction_Time", payload.get("time", "00:00:00")),
        "Payment_Method": payload.get("Payment_Method", payload.get("payment_method", "Unknown")),
        "Transaction_Channel": payload.get("Transaction_Channel", payload.get("channel", "Unknown")),
        "Device_Type": payload.get("Device_Type", payload.get("device_type", "Unknown")),
        "Transaction_Status": payload.get("Transaction_Status", payload.get("status", "Unknown")),
        "Is_International": payload.get("Is_International", payload.get("is_international", 0)),
        "Merchant_Risk_Level": payload.get("Merchant_Risk_Level", payload.get("merchant_risk", "Unknown")),
        "Merchant_Category": payload.get("Merchant_Category", payload.get("merchant_category", "Unknown")),
        "Merchant_Status": payload.get("Merchant_Status", payload.get("merchant_status", "Unknown")),
        "Merchant_Rating": payload.get("Merchant_Rating", payload.get("merchant_rating", 0)),
        "Customer_State": payload.get("Customer_State", payload.get("customer_state", "Unknown")),
        "Merchant_State": payload.get("Merchant_State", payload.get("merchant_state", "Unknown")),
        "Customer_City": payload.get("Customer_City", payload.get("customer_city", "Unknown")),
        "Merchant_City": payload.get("Merchant_City", payload.get("merchant_city", "Unknown")),
        "Card_Type": payload.get("Card_Type", payload.get("card_type", "Unknown")),
        "Card_Network": payload.get("Card_Network", payload.get("card_network", "Unknown")),
        "Credit_Limit": payload.get("Credit_Limit", payload.get("credit_limit", 0)),
        "Card_Status": payload.get("Card_Status", payload.get("card_status", "Unknown")),
        "Contactless": payload.get("Contactless", payload.get("contactless", "Unknown")),
        "Card_Mode": payload.get("Card_Mode", payload.get("card_mode", "Unknown")),
        "Customer_Segment": payload.get("Customer_Segment", payload.get("customer_segment", "Unknown")),
        "Account_Type": payload.get("Account_Type", payload.get("account_type", "Unknown")),
        "Customer_Age": payload.get("Customer_Age", payload.get("customer_age", 0)),
        "Annual_Income": payload.get("Annual_Income", payload.get("annual_income", 0)),
        "Customer_Since": payload.get("Customer_Since", payload.get("customer_since")),
        "Expiry_Date": payload.get("Expiry_Date", payload.get("expiry_date")),
    }
    return pd.DataFrame([row])
