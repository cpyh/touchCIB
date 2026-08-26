"""训练/预测/调参脚本子包。

这些是离线批处理入口，在线服务（predictor 等）不依赖它们；
保留在同一包内是为了让 partA1serving 具备"训练 -> 落盘 -> 服务"的完整闭环。

命令行入口统一用 `python -m` 形式（需将 submission/src 加入 sys.path）：

    python -m partA1serving.training.train_and_save --profile full --model lgbm_onehot
    python -m partA1serving.training.predict --model lgbm_onehot
    python -m partA1serving.training.tune --model lgbm_onehot
"""
