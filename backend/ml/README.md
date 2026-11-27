# 交易风控模型

## 数据

Kaggle: https://www.kaggle.com/datasets/jatinkhandelwal112/indian-financial-fraud-dataset

下载 zip 放到 backend/data/kaggle_indian_fraud.zip，解压到 backend/data/indian_fraud/，应包含：

- Transaction_Data_250k.csv
- Cards_Data.csv
- Cusmtomer_data.csv
- merchant_table.csv

## 训练

python backend/ml/train_transaction_model.py --data-dir backend/data/indian_fraud

输出：

- backend/models/transaction_pipeline.joblib
- backend/models/transaction_metadata.json
- backend/models/transaction_rules.json
- SQL Server 表 transaction_rules / transaction_models

## 指标

- AUC-ROC: 0.9814
- AUC-PR: 0.8667
- 阈值: 0.8878
- Precision: 0.8882
- Recall: 0.6724
- F1: 0.7654

## 说明

该数据集是表格交易数据，不包含聊天话术。它用于 LightGBM 交易风控模型与规则提炼，不用于微调 DeepSeek。

## 接口

- POST /api/transaction/risk
- GET /api/transaction/model-info
- GET /api/transaction/rules
