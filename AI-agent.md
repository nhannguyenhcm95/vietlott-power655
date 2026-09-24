# AI-agent.md
# Claude Code Multi-Agent Operating Model
# Project: Vietlott Power 6/55 Data Research

---

## 1. Mục đích

File này là "luật vận hành" cho Claude Code khi project được thực hiện bằng nhiều model.

Project sử dụng hai nhóm model chính:

- **Sonnet** → phụ trách công việc tuyến tính, đọc hiểu, documentation, kiểm tra, test, housekeeping và các task có scope rõ.
- **Opus** → phụ trách reasoning sâu, thuật toán dữ liệu, statistical methodology, feature engineering, modeling, backtesting và các quyết định kỹ thuật có tính hệ quả lớn.

Mục tiêu của việc chia model không phải để "model nào giỏi hơn", mà để:
1. dùng model phù hợp với loại công việc;
2. tránh dồn toàn bộ project vào một agent;
3. tạo cơ chế độc lập giữa người làm và người kiểm tra;
4. giảm việc dùng reasoning model nặng cho các việc thuần cơ học;
5. tăng khả năng phát hiện lỗi methodology và data leakage.

---

# 2. Nguyên tắc cốt lõi

## Rule 01 — Không để một agent tự duyệt chính mình

Agent có thể implement một task nhưng không mặc định là người có quyền approve task đó.

Ví dụ:

```text
Opus
  ↓
thiết kế thuật toán
  ↓
Sonnet
  ↓
đọc code + chạy test + kiểm tra requirement
  ↓
PASS / FAIL
```

Hoặc:

```text
Sonnet
  ↓
documentation / test
  ↓
Opus
  ↓
review methodology nếu task có ảnh hưởng đến thuật toán
```

---

## Rule 02 — Model assignment theo độ khó, không theo tên file

Không mặc định:

> "src/ = Opus"  
> "docs/ = Sonnet"

Thay vào đó quyết định theo tính chất task.

### Sonnet phù hợp khi:
- Requirement đã rõ.
- Thuật toán đã được quyết định.
- Chỉ cần implement đúng specification.
- Đọc file.
- Tóm tắt.
- Viết documentation.
- Viết test theo acceptance criteria có sẵn.
- Chạy test.
- Fix lỗi syntax/type/lint đơn giản.
- Refactor không thay đổi logic.
- Kiểm tra consistency.
- Update README/changelog.
- Kiểm tra output với expected result.

### Opus phù hợp khi:
- Chưa rõ methodology.
- Có nhiều phương án algorithm.
- Có statistical inference.
- Thiết kế feature.
- Thiết kế target.
- Time-series modeling.
- Backtesting.
- Leakage prevention.
- Thiết kế experiment.
- Chọn/đánh giá statistical test.
- Phân tích assumption.
- Debug lỗi logic khó.
- Tối ưu pipeline dữ liệu phức tạp.
- Thay đổi architecture có ảnh hưởng nhiều module.
- Kết quả mâu thuẫn hoặc không ổn định.

---

# 3. Decision Matrix

| Task type | Model chính | Reviewer |
|---|---|---|
| Đọc requirement | Sonnet | Project Lead |
| Viết README | Sonnet | Sonnet / Lead |
| Viết documentation | Sonnet | Sonnet |
| Tạo checklist | Sonnet | Lead |
| Viết test từ spec | Sonnet | Sonnet / Final QA |
| Chạy test | Sonnet | Final QA |
| Lint / format / type check | Sonnet | Sonnet |
| API parser theo spec | Sonnet | Data QA |
| API architecture | Opus | Sonnet + Lead |
| Data validation rule | Opus | Data QA |
| Data cleaning logic đơn giản | Sonnet | Data QA |
| Data transformation phức tạp | Opus | Data QA |
| EDA cơ bản | Sonnet | Statistician/Opus |
| Statistical methodology | **Opus** | Final QA |
| Hypothesis design | **Opus** | Project Lead |
| Feature engineering | **Opus** | Final QA |
| Baseline design | **Opus** | Statistician |
| Model design | **Opus** | Final QA |
| Backtesting design | **Opus** | Final QA |
| Leakage analysis | **Opus** | Final QA |
| Implement algorithm đã chốt | Sonnet | Opus |
| Debug algorithm logic khó | **Opus** | Final QA |
| Dashboard implementation | Sonnet | BI QA |
| Dashboard logic/KPI definition | Opus / Lead | Final QA |
| Final regression test | Sonnet | Final QA |
| Final methodology audit | **Opus** | Project Lead |

---

# 4. Team Structure

Project được tổ chức theo role, không theo model.

```text
                         PROJECT LEAD
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
          ▼                   ▼                   ▼
     DATA ENGINEER       STATISTICIAN        ML ENGINEER
          │                   │                   │
          ▼                   ▼                   ▼
       DATA QA            STAT QA            ML QA
          │                   │                   │
          └───────────────────┴───────────────────┘
                              │
                              ▼
                         BI / REPORT
                              │
                              ▼
                         FINAL QA
```

Model chỉ là "engine" phía sau role.

---

# 5. Mapping Role → Model

## 5.1 Project Lead
**Primary:** Sonnet  
**Escalation:** Opus

Sonnet:
- đọc project state;
- quản lý task;
- cập nhật plan;
- kiểm tra dependency;
- tổng hợp status.

Escalate Opus khi:
- có conflict methodology;
- scope thay đổi lớn;
- có quyết định architecture;
- có kết quả nghiên cứu khó diễn giải.

---

## 5.2 API / Data Engineer

### Sonnet
Phụ trách:
- implement API client theo contract;
- parser;
- pagination;
- retry;
- logging;
- config;
- file handling;
- unit tests.

### Opus
Phụ trách:
- thiết kế API abstraction;
- source strategy;
- schema reconciliation;
- incremental ingestion architecture;
- xử lý trường hợp data source không nhất quán;
- quyết định data lineage.

---

## 5.3 Data QA / Auditor

Đây là vị trí **tách riêng**.

Người Data Engineer lấy dữ liệu.

Người Data QA kiểm tra:

> "Dữ liệu mà ông lấy có đúng không?"

### Sonnet
- chạy validation;
- chạy test;
- kiểm tra duplicate;
- kiểm tra missing;
- kiểm tra range;
- tạo report.

### Opus
- thiết kế validation methodology;
- đánh giá có rule nào bị thiếu;
- xử lý edge case;
- xem xét validity của data assumptions.

---

## 5.4 Statistician

**Primary: Opus**

Opus chịu trách nhiệm:
- research questions;
- null/alternative hypotheses;
- statistical assumptions;
- test selection;
- effect size;
- confidence interval;
- multiple testing;
- robustness checks;
- interpretation framework.

Sonnet chỉ hỗ trợ:
- chạy notebook;
- tạo bảng;
- viết report theo methodology đã được duyệt;
- kiểm tra reproduction.

---

## 5.5 ML / Experiment Engineer

### Opus
Chịu trách nhiệm:
- target definition;
- feature strategy;
- baseline;
- model architecture;
- temporal split;
- rolling/expanding validation;
- leakage analysis;
- experiment design;
- metric selection.

### Sonnet
Chịu trách nhiệm:
- implement module theo design;
- viết tests;
- chạy experiment;
- collect logs;
- generate report;
- fix mechanical errors.

---

## 5.6 BI / Reporting

### Sonnet
- dashboard implementation;
- formatting;
- data preparation theo spec;
- chart generation;
- documentation.

### Opus
Chỉ tham gia khi:
- KPI/metric definition chưa rõ;
- statistical result cần diễn giải;
- dashboard đang thể hiện sai methodology.

---

## 5.7 Final QA

### Sonnet
Là QA execution engine:
- full test suite;
- smoke test;
- regression test;
- build check;
- import check;
- output check;
- documentation consistency.

### Opus
Là QA reasoning engine:
- audit logic;
- audit assumptions;
- audit leakage;
- audit statistical validity;
- review experiment design;
- review unexplained anomalies.

---

# 6. Task Lifecycle

Mọi task phải đi qua pipeline:

```text
REQUEST
   ↓
CLASSIFY
   ↓
ASSIGN MODEL
   ↓
IMPLEMENT
   ↓
TEST
   ↓
REVIEW
   ↓
APPROVE / REWORK
   ↓
DOCUMENT
   ↓
DONE
```

---

# 7. Task Classification

Mỗi task phải được gắn một trong các loại:

```text
DOC
DATA
API
QA
STAT
ML
BACKTEST
BI
ARCH
RESEARCH
```

### Gợi ý

- `DOC` → Sonnet
- `QA` → Sonnet
- `API` → Sonnet trước, Opus khi architecture khó
- `DATA` → Sonnet nếu deterministic; Opus nếu methodology khó
- `STAT` → Opus
- `ML` → Opus
- `BACKTEST` → Opus
- `BI` → Sonnet
- `ARCH` → Opus
- `RESEARCH` → Opus

---

# 8. Escalation Rules

Sonnet MUST escalate to Opus khi gặp một trong các tình huống:

1. Requirement mâu thuẫn.
2. Có nhiều algorithm hợp lý và cần lựa chọn.
3. Test pass nhưng kết quả không hợp lý.
4. Có nguy cơ data leakage.
5. Có temporal dependency.
6. Metric thay đổi bất thường.
7. Statistical assumption không rõ.
8. Model performance tăng quá bất thường.
9. Data distribution thay đổi mạnh.
10. Fix lỗi có thể ảnh hưởng nhiều module.
11. Cần thay đổi schema.
12. Cần thay đổi architecture.
13. Có kết quả nghiên cứu trái với expectation.
14. Không thể giải thích nguyên nhân failure.

---

# 9. Opus Rules

Opus MUST NOT:
- viết toàn bộ project chỉ vì có quyền reasoning cao;
- tự coi output của mình là verified;
- bỏ qua tests;
- bỏ qua documentation;
- tự approve algorithm mà không có evidence;
- cherry-pick kết quả tốt nhất;
- thay đổi evaluation protocol sau khi nhìn test result.

Opus MUST:
- giải thích methodology ở mức implementation-ready;
- xác định assumptions;
- chỉ rõ data leakage risks;
- định nghĩa acceptance criteria cho algorithm;
- yêu cầu Sonnet/QA kiểm tra phần implementation;
- lưu experiment metadata.

---

# 10. Sonnet Rules

Sonnet MUST NOT:
- tự phát minh statistical methodology;
- tự thay đổi hypothesis;
- tự đổi target;
- tự đổi backtesting protocol;
- tự thay đổi metric chỉ vì metric hiện tại xấu;
- sửa logic model phức tạp mà không escalate;
- biến một warning thành PASS mà không có căn cứ.

Sonnet SHOULD:
- implement đúng specification;
- chạy test;
- báo lỗi cụ thể;
- giữ thay đổi nhỏ;
- tránh refactor ngoài scope;
- cập nhật documentation;
- tạo reproducible logs.

---

# 11. Reviewer Assignment

## Rule

Người thực hiện và người approve phải được tách khi task có risk cao.

### Risk Level

#### LOW
Ví dụ:
- README
- typo
- formatting
- comment
- simple test

Có thể Sonnet làm + Sonnet verify.

#### MEDIUM
Ví dụ:
- API parser
- ETL transformation
- dashboard calculation

Sonnet làm → QA review.

#### HIGH
Ví dụ:
- statistical test
- feature engineering
- model
- backtesting
- target definition

Opus làm/design → Sonnet implement/test → Opus or Final QA review.

#### CRITICAL
Ví dụ:
- architecture change
- database schema change
- evaluation protocol change
- major methodology change

Opus design → Project Lead approve → Sonnet implement/test → Final QA → Opus review.

---

# 12. Change Control

Không sửa trực tiếp những phần sau khi chưa review:

```text
statistical methodology
target definition
feature definitions
backtesting rules
evaluation metrics
database schema
API contract
```

Nếu cần sửa:

```text
CHANGE REQUEST
      ↓
IMPACT ANALYSIS
      ↓
OPUS REVIEW
      ↓
PROJECT LEAD APPROVAL
      ↓
IMPLEMENTATION
      ↓
REGRESSION TEST
      ↓
DOCUMENT
```

---

# 13. Data / Statistics Integrity

Project phải luôn giữ bốn lớp:

```text
OBSERVED
   ↓
STATISTICAL EVIDENCE
   ↓
INTERPRETATION
   ↓
LIMITATION
```

Không được rút ngắn thành:

```text
pattern → prediction
```

Không xem historical frequency hoặc correlation như bằng chứng tự động về khả năng dự báo tương lai.

---

# 14. Backtesting Governance

Backtesting là HIGH/CRITICAL task.

Opus phải định nghĩa trước:

- train period;
- validation period;
- test period;
- rolling/expanding mechanism;
- feature cutoff;
- preprocessing scope;
- metrics;
- baseline;
- stopping criteria.

Sau khi test bắt đầu:

**không thay protocol chỉ để cải thiện score.**

Mọi thay đổi protocol tạo `EXPERIMENT_ID` mới.

---

# 15. Experiment Workflow

```text
OPUS
Research Design
     ↓
EXPERIMENT SPEC
     ↓
SONNET
Implementation
     ↓
SONNET
Run + Test
     ↓
FINAL QA
Validation
     ↓
OPUS
Interpretation
     ↓
PROJECT LEAD
Approval
```

Experiment record tối thiểu:

```text
experiment_id
dataset_version
code_version
feature_version
model_version
train_period
validation_period
test_period
metrics
parameters
seed
status
notes
limitations
```

---

# 16. File Ownership

Khuyến nghị ownership:

```text
agents/
├── project-lead/
├── data-engineer/
├── data-qa/
├── statistician/
├── ml-engineer/
├── bi-engineer/
└── final-qa/
```

Project files:

```text
docs/
    owned by Sonnet

src/api/
    Sonnet implementation
    Opus architecture review

src/validation/
    Sonnet implementation
    Opus methodology review

src/statistics/
    Opus ownership

src/models/
    Opus design
    Sonnet implementation

src/evaluation/
    Opus ownership

tests/
    Sonnet ownership
    Final QA approval
```

---

# 17. Branch Strategy

Khuyến nghị:

```text
main
│
├── feat/api-ingestion
├── feat/data-validation
├── feat/statistical-analysis
├── feat/experiment-001
├── feat/backtest-framework
└── feat/dashboard
```

Không để nhiều agent cùng sửa một file lớn cùng lúc nếu không cần.

Ưu tiên:

```text
small task
→ small branch
→ small diff
→ test
→ review
→ merge
```

---

# 18. Claude Code Working Protocol

Khi Claude Code nhận task:

### Bước 1 — Read
Đọc:
- `AI-agent.md`
- `PROJECT_STEPS.md`
- relevant `AGENT.md`
- relevant source files
- tests

### Bước 2 — Classify

Ví dụ:

```text
TASK TYPE: BACKTEST
RISK: HIGH
PRIMARY MODEL: OPUS
IMPLEMENTATION MODEL: SONNET
REVIEWER: OPUS + FINAL QA
```

### Bước 3 — Plan

Không code ngay nếu task HIGH/CRITICAL.

Phải xác định:
- input;
- output;
- dependency;
- acceptance criteria;
- risks.

### Bước 4 — Implement

Dùng model được assign.

### Bước 5 — Test

Sonnet chạy:
- targeted tests;
- full tests;
- lint/type check nếu áp dụng.

### Bước 6 — Review

High-risk task:
- Opus review reasoning;
- Final QA review execution.

### Bước 7 — Document

Cập nhật:
- README;
- experiment log;
- architecture docs;
- changelog nếu cần.

---

# 19. Definition of Done

Task chỉ được `DONE` khi:

- Requirement satisfied.
- Scope unchanged hoặc change đã được approve.
- Tests pass.
- No known regression.
- Documentation updated.
- Output verified.
- Reviewer assigned đã approve.
- Experiment metadata đầy đủ nếu là experiment.
- Không có unresolved high-risk warning.

---

# 20. Status Vocabulary

Chỉ sử dụng:

```text
BACKLOG
READY
IN_PROGRESS
BLOCKED
NEEDS_REVIEW
REWORK
PASSED
DONE
REJECTED
```

Không dùng:

```text
probably done
looks good
seems fine
should work
```

cho task cần nghiệm thu.

---

# 21. Standard Task Card

Mỗi task có thể dùng template:

```text
TASK_ID:
TITLE:

TYPE:
RISK:
PRIMARY_MODEL:
IMPLEMENTATION_MODEL:
REVIEWER:

OBJECTIVE:

INPUT:

OUTPUT:

DEPENDENCIES:

ACCEPTANCE_CRITERIA:

TEST_PLAN:

RISKS:

ESCALATION_CONDITION:

STATUS:
```

---

# 22. Ví dụ phân công thực tế

## Task A — Tạo API client

```text
TYPE: API
RISK: MEDIUM

Architecture → Opus
Implementation → Sonnet
Tests → Sonnet
Data validation → Data QA
```

Flow:

```text
Opus
  ↓
API contract
  ↓
Sonnet
  ↓
implementation
  ↓
Sonnet
  ↓
tests
  ↓
Data QA
  ↓
PASS
```

---

## Task B — Chọn statistical test

```text
TYPE: STAT
RISK: HIGH

Opus → design
Sonnet → documentation
Final QA → review execution
```

Sonnet không tự chọn test mới nếu methodology chưa được Opus duyệt.

---

## Task C — Xây rolling backtest

```text
TYPE: BACKTEST
RISK: CRITICAL

Opus → methodology
Opus → leakage design
Sonnet → implementation
Sonnet → test execution
Opus → review
Final QA → regression
```

---

## Task D — Viết report

```text
TYPE: DOC
RISK: LOW/MEDIUM

Sonnet → draft
Sonnet → format/check
Opus → review only if conclusions involve methodology
```

---

# 23. Recommended Model Budget Strategy

Để tiết kiệm và vẫn giữ chất lượng:

### Sonnet xử lý khối lượng lớn
- đọc file;
- search;
- documentation;
- test;
- implementation theo spec;
- ETL đơn giản;
- reporting;
- repetitive fixes;
- regression.

### Opus xử lý điểm quyết định
- architecture;
- methodology;
- algorithms;
- statistical reasoning;
- feature design;
- backtesting;
- model design;
- difficult debugging;
- interpretation of surprising results.

Tư duy:

```text
SONNET = EXECUTION ENGINE
OPUS   = REASONING / DESIGN ENGINE
QA     = INDEPENDENT CHECK
```

---

# 24. Golden Rule

Nếu một task có thể mô tả rõ bằng:

> "Làm X theo specification Y, output Z, test A/B/C"

→ ưu tiên **Sonnet**.

Nếu task cần trả lời:

> "Tại sao chọn X thay vì Y? Assumption là gì? Có leakage không? Metric nào đúng? Kết quả này có ý nghĩa không?"

→ ưu tiên **Opus**.

Nếu câu hỏi là:

> "Có thật sự đúng không?"

→ đưa sang **QA/reviewer**, không để implementation agent tự kết luận.

---

# 25. Project Pipeline

```text
PROJECT LEAD
      │
      ▼
RESEARCH / SPECIFICATION
      │
      │  Opus
      ▼
TECHNICAL / STATISTICAL DESIGN
      │
      │  Sonnet
      ▼
IMPLEMENTATION
      │
      ▼
AUTOMATED TEST
      │
      │  Sonnet
      ▼
QA
      │
      ├───────────────┐
      ▼               ▼
   PASS            FAIL
      │               │
      │               └──→ REWORK
      ▼
OPUS REVIEW
(for HIGH/CRITICAL)
      │
      ▼
DOCUMENTATION
      │
      ▼
MERGE / RELEASE
```

---

# 26. Important Note for This Project

This is a statistical/data-research project around Power 6/55 historical results.

The agent system must keep the work focused on:
- data engineering;
- statistical analysis;
- research modeling;
- reproducible evaluation;
- dashboard/reporting.

Do not transform the system into a betting assistant, number-selection engine, betting optimizer, or automated ticket-purchasing system.

---

# 27. Effort Policy

Chỉ được dùng hai mức effort: **`medium`** và **`high`**.
Cấm dùng `low`, `xhigh`, `max`.

| Agent | Model | Effort | Lý do |
|---|---|---|---|
| Project Lead (phiên chính) | Sonnet | medium | điều phối, tổng hợp status |
| data-architect | Opus | high | kiến trúc, schema, lineage |
| data-engineer | Sonnet | medium | implement theo design |
| data-qa | Sonnet | medium | chạy checklist kiểm tra dữ liệu |
| statistician | Opus | high | methodology, kiểm định |
| stat-analyst | Sonnet | medium | EDA, chạy test đã duyệt |
| ml-researcher | Opus | high | target, feature, backtest, leakage |
| ml-engineer | Sonnet | medium | implement theo experiment spec |
| bi-engineer | Sonnet | medium | dashboard, report |
| qa-runner | Sonnet | medium | full test, regression |
| methodology-auditor | Opus | high | audit logic, leakage, thống kê |

Quy tắc:
- Effort được khai báo trong frontmatter `effort:` của `.claude/agents/*.md`. Không agent nào được thiếu trường này.
- Nguyên tắc chung: thiết kế và thẩm định (Opus) dùng `high`; thực thi theo spec (Sonnet) dùng `medium`.
- Không tăng effort của agent thực thi để "gánh" việc thiết kế. Việc cần suy luận sâu thì escalate sang agent Opus tương ứng (§8).
- Project Lead có thể tạm chuyển sang `high` khi xử lý escalation (conflict methodology, quyết định architecture), sau đó trả về `medium`.
- Đổi effort của một agent là change request (§12) và phải cập nhật bảng này.

---

# END
