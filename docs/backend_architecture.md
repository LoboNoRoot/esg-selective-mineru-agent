# ESG 报告智能抽取后端设计

## 1. 赛题目标映射

赛题要求围绕 ESG 报告 PDF 完成数据采集、预处理、50+ 指标体系、定量/定性指标抽取、表格图表识别、JSON/CSV 输出，以及可选的可视化分析系统。

当前项目已经具备单份报告的核心算法链路：

- `page_scan.py`: PyMuPDF 快速扫描页级文本层、数值密度、ESG 关键词、表格线索。
- `parse_plan.py`: 选择高价值页面进入 MinerU，避免全量高成本解析。
- `chunks.py`: 构建 PyMuPDF 与 MinerU 混合 RAG chunks。
- `retriever.py`: 按字段定义召回证据。
- `extractor.py`: 调用 OpenAI-compatible LLM 输出 60 字段 JSON/CSV。
- `api.py`: 将 CLI 流水线包装成后端任务接口。

## 2. 推荐架构

第一阶段建议采用“模块化单体 + 异步任务”的架构：

- API 服务：FastAPI，负责上传、任务创建、状态查询、结果下载。
- 抽取 Worker：复用当前 pipeline，先通过 FastAPI BackgroundTasks 本地执行，后续替换为 Celery/RQ。
- 存储：当前用本地 `data/uploads` 和 `output/api_jobs`，比赛演示足够；生产化再接 MinIO/S3。
- 数据库：第一阶段可以文件落盘，第二阶段引入 PostgreSQL 存储报告、任务、字段结果、人工复核状态。
- 缓存：Redis 用于任务队列、限流、热点查询缓存。

不建议现在直接拆微服务。当前算法链路仍在快速迭代，拆太早会增加接口和部署成本。

## 3. API 设计

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 健康检查 |
| POST | `/reports` | 上传 PDF 并创建任务 |
| GET | `/jobs/{job_id}` | 查询任务状态 |
| GET | `/jobs/{job_id}/summary` | 查询抽取摘要 |
| GET | `/jobs/{job_id}/results` | 查询 JSON 抽取结果 |
| GET | `/jobs/{job_id}/export.csv` | 下载 CSV 抽取结果 |

`POST /reports` 参数：

- `file`: PDF 文件。
- `mode`: `scan`、`extract`、`run`，默认 `run`。
- `use_llm`: 是否调用大模型，默认 `true`。

任务状态：

- `queued`: 已入队。
- `running`: 正在处理。
- `succeeded`: 成功。
- `failed`: 失败。

## 4. PostgreSQL Schema 建议

后续从文件存储升级为数据库时，建议使用以下核心表。

```sql
CREATE TABLE reports (
  id UUID PRIMARY KEY,
  stock_code VARCHAR(16),
  company_name VARCHAR(128),
  report_year INT,
  report_type VARCHAR(32) NOT NULL DEFAULT 'ESG',
  original_filename TEXT NOT NULL,
  file_uri TEXT NOT NULL,
  file_sha256 CHAR(64),
  page_count INT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_reports_file_sha256 ON reports(file_sha256) WHERE file_sha256 IS NOT NULL;
CREATE INDEX idx_reports_company_year ON reports(company_name, report_year);

CREATE TABLE extraction_jobs (
  id UUID PRIMARY KEY,
  report_id UUID NOT NULL REFERENCES reports(id),
  mode VARCHAR(16) NOT NULL,
  status VARCHAR(16) NOT NULL,
  use_llm BOOLEAN NOT NULL DEFAULT true,
  output_dir TEXT,
  error TEXT,
  summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_jobs_report_id ON extraction_jobs(report_id);
CREATE INDEX idx_jobs_status_created_at ON extraction_jobs(status, created_at DESC);

CREATE TABLE esg_fields (
  field_key VARCHAR(128) PRIMARY KEY,
  name_cn VARCHAR(128) NOT NULL,
  category CHAR(1) NOT NULL,
  indicator_type VARCHAR(32) NOT NULL,
  expected_units JSONB NOT NULL DEFAULT '[]'::jsonb,
  aliases JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE extraction_results (
  id BIGSERIAL PRIMARY KEY,
  job_id UUID NOT NULL REFERENCES extraction_jobs(id),
  report_id UUID NOT NULL REFERENCES reports(id),
  field_key VARCHAR(128) NOT NULL REFERENCES esg_fields(field_key),
  matched BOOLEAN NOT NULL DEFAULT false,
  value TEXT,
  unit VARCHAR(64),
  year VARCHAR(16),
  summary TEXT,
  evidence TEXT,
  source_chunk_id VARCHAR(128),
  source_page INT,
  confidence NUMERIC(4,3) NOT NULL DEFAULT 0,
  review_status VARCHAR(16) NOT NULL DEFAULT 'pending',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_results_job_field ON extraction_results(job_id, field_key);
CREATE INDEX idx_results_report_field ON extraction_results(report_id, field_key);
CREATE INDEX idx_results_review_status ON extraction_results(review_status);
CREATE INDEX idx_results_confidence ON extraction_results(confidence);
```

## 5. 后续工程路线

1. 批量导入 100+ PDF：增加目录导入接口或 CLI，自动解析股票代码、公司名、年份。
2. 任务队列化：将 FastAPI BackgroundTasks 替换为 Redis + RQ/Celery，避免长任务阻塞 API 进程。
3. 结果入库：将 `extraction_results.json` 同步写入 PostgreSQL，支持按公司、年份、指标查询。
4. 评估闭环：增加人工标注表，计算 precision、recall、field-level accuracy、运行耗时和内存。
5. 前端接 API：把 `frontend/index.html` 的 mock 数据替换为 `/jobs/{job_id}/results`。
6. 对象存储：将 PDF、MinerU 产物、CSV 存入 MinIO/S3，数据库只保存 URI。
