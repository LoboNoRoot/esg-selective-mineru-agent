# ESG Selective MinerU Agent

独立测试项目：验证企业场景下的分层解析与 A 股 ESG 60 字段抽取路线。

路线：

1. PyMuPDF 快速全 PDF 扫描。
2. 识别重点页：绩效表、指标表、环境/员工/治理数据页、扫描页、图文混排页。
3. 对重点页命中较多的报告调用 MinerU，并缓存解析结果。
4. 基于 PyMuPDF + MinerU 文本构建 RAG chunks。
5. 复用原项目 `core_esg_v5_a_share_60` schema，通过 DashScope/OpenAI-compatible 文本模型输出 JSON/CSV。

## 配置

复制配置：

```powershell
Copy-Item configs\.env.example .env
```

在 `.env` 中配置：

- `MINERU_COMMAND`: MinerU 命令。
- `DASHSCOPE_API_KEY`: 模型调用 key。
- `TEXT_MODEL`: 字段抽取模型。
- `LLM_MAX_CALLS_PER_REPORT`: 每份报告最大模型调用数，默认 12。
- `LLM_FIELD_BATCH_SIZE`: 每次模型调用处理字段数，默认 6。
- `RAG_TOP_K`: 每个字段召回的证据块数量，默认 3。
- `RETRIEVER_MODE`: 召回模式，`simple` 使用原 BM25 召回，`hybrid` 启用 BM25 + 本地向量召回测试版，默认 `simple`。
- `RETRIEVER_VECTOR_BACKEND`: hybrid 模式下的向量后端，`local` 使用无外部依赖原型，`embedding` 调用 OpenAI-compatible embeddings API，默认 `local`。
- `EMBEDDING_MODEL`: embedding 后端模型名，默认 `text-embedding-v4`。
- `EMBEDDING_BATCH_SIZE`: 文档 chunk embedding 批大小，默认 10。
- `RAG_BM25_TOP_K`: hybrid 模式下 BM25 分支候选数量，默认 30。
- `RAG_VECTOR_TOP_K`: hybrid 模式下本地向量分支候选数量，默认 30。
- `RAG_RRF_K`: hybrid 模式下 RRF 融合参数，默认 60。
- `SELECTIVE_MINERU_MAX_PAGES`: 重点页上限，默认 12。
- `TARGET_REPORT_YEAR`: 当前抽取和质量校验的目标报告年度，默认 2024。现阶段只接受 2024 年数据；报告中出现的 2025 或历史年份会被标记为年份异常并提高复核优先级。
- `MINERU_LLM_REVIEW_ENABLED`: 是否启用 MinerU 灰区页 LLM 复判，默认 false。
- `MINERU_LLM_REVIEW_LOW_THRESHOLD`: 低于该分数直接跳过，默认 25。
- `MINERU_LLM_REVIEW_HIGH_THRESHOLD`: 高于或等于该分数直接选择 MinerU，默认 45。
- `MINERU_LLM_REVIEW_MAX_PAGES`: 每份报告最多交给 LLM 复判的灰区页数，默认 20。

## 命令

采集不少于 100 份 A 股 ESG PDF 报告：

```powershell
$env:PYTHONPATH='C:\Users\18130\PycharmProjects\爬虫\esg-selective-mineru-agent\src'
& 'C:\Users\18130\.conda\envs\pachong\python.exe' scripts\collect_a_share_esg_reports.py `
  --output data\a_share_esg_reports `
  --limit 100 `
  --se-date '2023-01-01~2026-12-31'
```

采集脚本会生成：

- `data\a_share_esg_reports\raw\`: 原始 PDF。
- `data\a_share_esg_reports\a_share_esg_reports_manifest.csv`: 报告清单、证券代码、公司名、公告标题、PDF URL、本地路径。

对采集 PDF 做统一预处理：

```powershell
$env:PYTHONPATH='C:\Users\18130\PycharmProjects\爬虫\esg-selective-mineru-agent\src'
& 'C:\Users\18130\.conda\envs\pachong\python.exe' scripts\preprocess_esg_pdfs.py `
  --manifest data\a_share_esg_reports\a_share_esg_reports_manifest.csv `
  --output data\a_share_esg_reports
```

预处理会为每份报告生成：

- 统一命名 PDF：`data\a_share_esg_reports\pdf\`。
- `page_texts.jsonl`: PyMuPDF 页级文本。
- `page_scan.json`: 页级 ESG 关键词、数值密度、表格线索和扫描页识别。
- `parse_plan.json`: MinerU 重点页选择计划。
- `table_candidates.json`: 表格候选页和表格样本文本行。
- `pymupdf_chunks.json`: 后续 RAG/抽取可直接使用的文本块。
- `preprocess_manifest.csv`: 全部报告的 sha256、页数、低文本页数、表格候选页数等质量概览。

异常输入处理：

- 传统 `社会责任报告` / `企业社会责任报告` 若标题层面缺少 `ESG`、`环境、社会和公司治理`、`可持续发展` 等 ESG 披露框架信号，会被标记为 `legacy_social_responsibility_report` 并跳过。
- 鉴证声明、审验报告、摘要等非完整正文报告会被标记为 `supporting_or_summary_document` 并跳过。
- 跳过任务不会进入 MinerU/LLM 抽取，API 状态为 `skipped`，并输出 `skip_report.json`。
- 异常输入测试说明见 `docs/abnormal_input_test_report.md`。

只做快扫和解析计划：

```powershell
$env:PYTHONPATH='C:\Users\18130\PycharmProjects\爬虫\esg-selective-mineru-agent\src'
& 'C:\Users\18130\.conda\envs\pachong\python.exe' -m esg_selective_mineru.cli scan '<PDF>' --output 'output\report_scan'
```

跑 MinerU，并直接抽取 60 字段：

```powershell
$env:PYTHONPATH='C:\Users\18130\PycharmProjects\爬虫\esg-selective-mineru-agent\src'
& 'C:\Users\18130\.conda\envs\pachong\python.exe' -m esg_selective_mineru.cli run '<PDF>' --output 'output\report_run' --extract
```

不调用大模型，只生成 chunks 和字段证据：

```powershell
$env:PYTHONPATH='C:\Users\18130\PycharmProjects\爬虫\esg-selective-mineru-agent\src'
& 'C:\Users\18130\.conda\envs\pachong\python.exe' -m esg_selective_mineru.cli extract '<PDF>' --output 'output\report_extract' --no-llm
```

测试 BM25 + 向量混合召回：

```powershell
$env:PYTHONPATH='C:\Users\18130\PycharmProjects\爬虫\esg-selective-mineru-agent\src'
$env:RETRIEVER_MODE='hybrid'
& 'C:\Users\18130\.conda\envs\pachong\python.exe' -m esg_selective_mineru.cli extract '<PDF>' --output 'output\report_extract_hybrid' --no-llm
```

hybrid 测试版会在 `field_contexts.json` 中为候选块增加 `retrieval_source`、`bm25_rank`、`vector_rank`、`bm25_score`、`vector_score`、`hybrid_rank` 等字段，便于和原 `simple` 模式对比证据召回效果。当前向量分支是无外部依赖的本地字符 n-gram TF-IDF cosine 原型，用于低成本验证融合策略；后续可替换为真实 embedding/FAISS。

使用真实 embedding 向量召回：

```powershell
$env:PYTHONPATH='C:\Users\18130\PycharmProjects\爬虫\esg-selective-mineru-agent\src'
$env:RETRIEVER_MODE='hybrid'
$env:RETRIEVER_VECTOR_BACKEND='embedding'
$env:EMBEDDING_MODEL='text-embedding-v4'
& 'C:\Users\18130\.conda\envs\pachong\python.exe' -m esg_selective_mineru.cli extract '<PDF>' --output 'output\report_extract_hybrid_embedding' --no-llm
```

embedding 模式会复用 `DASHSCOPE_API_KEY` 和 `OPENAI_BASE_URL`，会产生 embedding API 调用成本；如果缺少 key 或调用失败，会自动回退到本地向量原型，并在 `field_contexts.json` 中写入 `vector_backend: local_fallback` 和简短 `vector_error`。

生成 simple / local hybrid / embedding hybrid 三方召回人工评估表：

```powershell
$env:PYTHONPATH='C:\Users\18130\PycharmProjects\爬虫\esg-selective-mineru-agent\src'
& 'C:\Users\18130\.conda\envs\pachong\python.exe' -m esg_selective_mineru.cli retrieval-eval `
  --simple-dir output\compare_retrieval\000537_simple `
  --local-hybrid-dir output\compare_retrieval\000537_hybrid `
  --embedding-hybrid-dir output\compare_retrieval\000537_embedding `
  --output output\retrieval_evaluation
```

多份报告时重复传入三组目录，并保持 simple、local hybrid、embedding hybrid 的报告顺序一致。命令会生成 `retrieval_manual_comparison.csv` 和 `retrieval_comparison_summary.json`；人工在 CSV 中填写 `best_mode`、`simple_score`、`local_hybrid_score`、`embedding_hybrid_score` 和 `retrieval_note`。

已有 MinerU 缓存时，只重跑抽取：

```powershell
$env:PYTHONPATH='C:\Users\18130\PycharmProjects\爬虫\esg-selective-mineru-agent\src'
& 'C:\Users\18130\.conda\envs\pachong\python.exe' -m esg_selective_mineru.cli extract '<PDF>' --output 'output\report_extract'
```

## 后端 API

本项目也提供 FastAPI 后端入口，便于把赛题要求中的“批量报告处理、结果查询、CSV 展示”接成系统。

本地启动：

```powershell
$env:PYTHONPATH='C:\Users\18130\PycharmProjects\爬虫\esg-selective-mineru-agent\src'
& 'C:\Users\18130\.conda\envs\pachong\python.exe' -m uvicorn esg_selective_mineru.api:app --host 127.0.0.1 --port 8000 --reload
```

Docker Compose 启动：

```powershell
docker compose up --build
```

主要接口：

- `GET /health`: 健康检查。
- `POST /reports`: 上传 PDF 并创建任务，参数 `mode=scan|extract|run`，`use_llm=true|false`。
- `POST /reports/batch`: 一次上传多份 PDF 并批量创建任务，表单字段为 `files`。
- `GET /jobs`: 查询历史任务列表，按更新时间倒序返回。
- `GET /jobs/{job_id}`: 查询任务状态。
- `POST /jobs/{job_id}/retry`: 复用原 PDF 和任务配置重跑任务。
- `GET /jobs/{job_id}/summary`: 查询抽取摘要。
- `GET /jobs/{job_id}/results`: 查询 JSON 结果，并合并字段复核状态、`review_priority` 复核优先级、年份/单位/证据质量评分。
- `GET /jobs/{job_id}/quality`: 查询 job 质量摘要，包括低置信度、年份异常、单位异常、弱证据、待复核数量。
- `GET /jobs/{job_id}/reviews`: 查询字段复核记录。
- `PUT /jobs/{job_id}/reviews/{field_key}`: 保存字段复核状态、修正值、证据和备注。
- `GET /jobs/{job_id}/export.csv`: 下载合并复核状态、修正值和备注后的 CSV 结果。

上传接口目前限制 PDF 文件，单文件大小上限为 80 MB，用于避免误传大文件或非 PDF 文件拖垮本地 MVP 服务。

Docker 环境默认关闭 MinerU 自动运行，避免容器内缺少本机 MinerU 可执行文件。需要容器内跑 MinerU 时，请把 MinerU 安装进镜像，并覆盖 `MINERU_AUTO_RUN_ENABLED=true` 与 `MINERU_COMMAND`。

## 产物

- `page_scan.json`: PyMuPDF 页级快扫特征。
- `parse_plan.json`: 每页解析策略。
- `mineru_jobs.json`: MinerU 任务结果。
- `rag_chunks.json`: RAG-ready 文本块。
- `field_contexts.json`: 每个字段召回的证据。
- `extraction_results.json`: 60 字段抽取结果。
- `extraction_results.csv`: 人工复核表。
- `extraction_summary.json`: 抽取摘要。
- `visual_fallback_queue.json`: VLM 兜底候选页。

## 小样本评估与复核页

从 4 份完整运行结果中每份抽 10 个字段，生成人工标注表和指标汇总：

```powershell
$env:PYTHONPATH='C:\Users\18130\PycharmProjects\爬虫\esg-selective-mineru-agent\src'
& 'C:\Users\18130\.conda\envs\pachong\python.exe' -m esg_selective_mineru.cli eval `
  --run-dir output\000537_full_run `
  --run-dir output\002973_full_run `
  --run-dir output\600587_full_run `
  --run-dir output\600713_full_run `
  --output output\evaluation `
  --sample-size 10
```

人工在 `output\evaluation\manual_evaluation_sample.csv` 中填写：

- `field_hit_correct`: 字段命中判断是否正确，填 `1/0`。
- `value_correct`: value、unit、year 或定性摘要是否正确，填 `1/0`。
- `evidence_usable`: 证据原文和页码是否可支撑结论，填 `1/0`。

复核证据时优先看 `source_text_short`、`source_text_short_page` 和 `source_text_short_chunk_id`。`pred_evidence` 是模型返回的证据表述，可能存在改写或概括；`retrieved_context` 是完整召回上下文，信息较多，主要用于追溯。

再次运行同一条 `eval` 命令会保留人工标注，并更新 `output\evaluation\evaluation_metrics.json`：

- 字段命中率。
- value 准确率。
- evidence 可用率。
- 平均处理时间。
- MinerU 页面调用比例。

生成单份报告的静态 HTML 复核页：

```powershell
$env:PYTHONPATH='C:\Users\18130\PycharmProjects\爬虫\esg-selective-mineru-agent\src'
& 'C:\Users\18130\.conda\envs\pachong\python.exe' -m esg_selective_mineru.cli review `
  --run-dir output\000537_full_run `
  --output output\review\000537_review.html
```

复核页包含左侧字段列表、中间抽取值、右侧原文短证据、模型证据和可折叠的完整召回上下文，并支持导出 CSV。

## 赛题落地说明

赛题要求“不少于 100 份 A 股或港股 ESG 报告、50+ 指标、定量与定性抽取、表格/图表识别、JSON/CSV 输出”。当前实现对应关系：

- 数据预处理：`page_scan.py` 使用 PyMuPDF 快速扫描 PDF 文本层、数值密度、表格线索和 ESG 关键词。
- 表格增强：`parse_plan.py` 选择重点页触发 MinerU，降低全量解析成本。
- 指标体系：`schema_loader.py` 复用原项目 A 股 v5 60 字段 schema，满足 50+ 指标要求。
- RAG 证据：`chunks.py` 与 `retriever.py` 生成字段级候选证据。
- 结构化输出：`extractor.py` 输出 `extraction_results.json` 和 `extraction_results.csv`。
- 系统展示：`api.py` 提供任务化后端接口，`frontend/index.html` 可继续接入真实 API 做结果复核界面。
