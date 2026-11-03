# GeneScope 2.0 API

默认http://127.0.0.1:8000/api/v1，本次验收使用8001；OpenAPI在/docs、/openapi.json。原历史API、/lab/*和仅传file的冻结预测调用仍兼容。

| 方法 | 路由 | 说明 |
|---|---|---|
| GET | /health | API和冻结模型运行状态 |
| GET | /datasets | 四数据集、实际统计、导入状态 |
| GET | /datasets/{id} | 元数据、版本、来源、标签、质量和协议 |
| GET | /datasets/{id}/summary | 类别分布、真实有界热图和元数据 |
| POST | /datasets/import | multipart：dataset_id、download、可选file；202任务 |
| GET | /algorithms | 四模型id/name |
| GET | /features/methods | 四方法与K候选 |
| POST | /experiments | JSON实验配置；202任务 |
| GET | /experiments | search、status、dataset_id、sort_by、descending |
| GET | /experiments/{id} | 完整持久化任务快照 |
| POST | /experiments/{id}/cancel | 停止实际进程并返回状态 |
| GET | /experiments/{id}/results | 完成结果、模型、指标、特征稳定性 |
| GET | /experiments/{id}/events | SSE，事件名snapshot，id为revision |
| GET | /experiments/{id}/logs | 最近200条阶段事件 |
| GET | /experiments/{id}/export | format=csv/json |
| GET | /models | dataset_id筛选，仅可信完成模型 |
| GET | /models/{id} | 完整输入特征、运行版本、预处理、评价 |
| POST | /predict | multipart：file、dataset_id、model_id；model_id=frozen_m1使用原M1 |
| GET | /comparison | task_ids逗号分隔，最多12个 |
| GET | /features/analysis | task_id、可选dataset_id |

训练JSON示例：

```json
{"dataset_id":"gse44076","algorithms":["linear_svc","logistic_regression","random_forest","rbf_svm"],"selection":"anova","k":50,"folds":3,"seed":42,"repeats":1,"c":1.0,"gamma":"scale","n_estimators":100,"max_depth":10}
```

模型id如上；选择方法为none/anova/variance/coefficient。K为20/50/100/300/500/1000；训练折再次核验有效特征。folds=2–10、repeats=1–5、总模型折拟合≤100、C=0.001–100、RF树数10–300、深度1–30或null。额外JSON字段拒绝。

```powershell
$base='http://127.0.0.1:8001/api/v1'
$body=@{dataset_id='gse4290';algorithms=@('linear_svc','random_forest');selection='anova';k=50;folds=3;seed=42;repeats=1}|ConvertTo-Json
$task=Invoke-RestMethod -Method Post -Uri "$base/experiments" -ContentType 'application/json' -Body $body
Invoke-RestMethod "$base/experiments/$($task.task_id)"
curl.exe -N "$base/experiments/$($task.task_id)/events"
Invoke-RestMethod "$base/experiments/$($task.task_id)/results"
curl.exe -F 'dataset_id=gse4290' -F 'download=false' "$base/datasets/import"
curl.exe -F 'dataset_id=gse4290' -F 'file=@GSE4290_series_matrix.txt.gz' "$base/datasets/import"
curl.exe -F 'dataset_id=pancan' -F 'model_id=frozen_m1' -F 'file=@sample.csv' "$base/predict"
```

任务包含task_id、dataset_id、experiment_config、created_at、started_at、finished_at、current_stage、completed_folds、total_folds、progress、elapsed_seconds、metrics、errors、artifact_paths、folds。SSE是持久化完整快照，支持重连；不虚构epoch/loss。

错误统一含status:error和error.code/message；HTTPException兼容保留detail。422参数/输入无效，409未就绪/未完成/已有任务，403非本机或不允许来源，404记录不存在。写操作限定本机及明确来源，未实现公网多用户鉴权。
