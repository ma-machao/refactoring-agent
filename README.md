# Legacy Django Refactor Agent 工作流程

整个 Agent 的完整 pipeline 可以理解为：

```
Legacy Project
      │
      ▼
1 Scan Project
      │
2 Analyze Models
      │
3 Map Models → Target Architecture
      │
4 LLM Review Mapping
      │
5 Merge Final Mapping
      │
6 Field Semantic Analysis
      │
7 Relationship Graph
      │
8 Domain Graph
      │
9 Analyze New Project Structure
      │
10 Generate Model Draft
```

---

# CLI 命令表（按执行顺序）
| 顺序 | 命令 | 示例命令 | 作用 | 输出 |
| -- |---- | ---- | --- | --- |
| 1  | scan                              | `python main.py scan -p /Users/machao/Desktop/Projects/nexus`                                                                                               | 扫描 legacy Django 项目结构，统计 Python 文件、templates、modules、settings.py、urls.py 等信息 | `reports/project_scan.json`                |
| 2  | analyze-models                    | `python main.py analyze-models -p /Users/machao/Desktop/Projects/nexus --module db`                                                                         | 分析 legacy 项目中指定 module（如 db）里的 Django models，提取字段、关系、Meta 等                  | `reports/db_models_analysis.json`          |
| 3  | map-db-to-target                  | `python main.py map-db-to-target -p /Users/machao/Desktop/Projects/nexus --target workspace/target_blueprint.json`                                          | 将 legacy models 映射到新项目架构 blueprint                                           | `reports/db_to_target_mapping.json`        |
| 4  | llm-review-db-mapping             | `python main.py llm-review-db-mapping --target workspace/target_blueprint.json`                                                                             | 使用大模型复核第3步生成的模型映射是否合理                                                        | `reports/db_to_target_mapping_review.json` |
| 5  | merge-final-mapping               | `python main.py merge-final-mapping`                                                                                                                        | 合并规则映射和 LLM 复核结果，生成最终模型映射                                                    | `reports/db_to_target_mapping_final.json`  |
| 6  | analyze-semantics                 | `python main.py analyze-semantics`                                                                                                                          | 分析模型字段语义（如 user → customer），解决语义歧义                                           | `reports/field_semantics.json`             |
| 7  | analyze-relationship-graph        | `python main.py analyze-relationship-graph`                                                                                                                 | 构建 legacy 模型关系图（ForeignKey、ManyToMany 等）                                     | `reports/relationship_graph.json`          |
| 8  | export-relationship-graph-mermaid | `python main.py export-relationship-graph-mermaid`                                                                                                          | 将模型关系图导出为 Mermaid 图                                                          | `reports/relationship_graph.mmd`           |
| 9  | analyze-domain-graph              | `python main.py analyze-domain-graph`                                                                                                                       | 根据关系图生成领域结构图（domain graph）                                                   | `reports/domain_graph.json`                |
| 10 | analyze-project-structure         | `python main.py analyze-project-structure -p /Users/machao/Desktop/Projects/re-nexus`                                                                          | 分析新项目代码结构（apps / models / serializers / services 等）                          | `reports/project_structure_graph.json`     |
| 11 | export-project-structure-mermaid  | `python main.py export-project-structure-mermaid`                                                                                                           | 将项目结构图导出为 Mermaid 图                                                          | `reports/project_structure_graph.mmd`      |
| 12 | generate-django6-model-draft      | `python main.py generate-django6-model-draft --project /Users/machao/Desktop/Projects/nexus --model VirtualServer --target workspace/target_blueprint.json` | 根据前面所有分析结果，为指定 legacy 模型生成 Django6 新架构模型草案                                   | `workspace/drafts/apps/.../models/*.py`    |
---

# 详细说明

---

# 1. scan

命令：

```bash
python main.py scan --project OLD_PROJECT
```

作用：

扫描 legacy Django 项目结构。

提取：

```
Python files
templates
modules
settings.py
urls.py
```

输出：

```
reports/project_scan.json
reports/project_scan.md
```

意义：

建立 **项目基本结构认知**。

---

# 2. analyze-models

命令：

```bash
python main.py analyze-models \
  --project OLD_PROJECT \
  --module db
```

作用：

分析某个 module 里的 Django models。

提取：

```
Model
Fields
ForeignKey
Meta
constants
default values
```

输出：

```
reports/db_models_analysis.json
reports/db_models_analysis.md
```

意义：

建立 **旧数据库 schema 的结构化表示**。

---

# 3. map-db-to-target

命令：

```bash
python main.py map-db-to-target \
  --project OLD_PROJECT \
  --target workspace/target_blueprint.json
```

作用：

把 legacy models 映射到 **新项目架构**。

输入：

```
db_models_analysis.json
target_blueprint.json
```

输出：

```
db_to_target_mapping.json
```

示例：

```
VirtualServer → compute.virtual_server
IPAddress → network.ipaddress
Region → asset.region
```

意义：

建立 **旧模型 → 新架构位置**。

---

# 4. llm-review-db-mapping

命令：

```bash
python main.py llm-review-db-mapping \
  --target workspace/target_blueprint.json
```

作用：

让 LLM 复核 mapping。

LLM 会判断：

```
mapping 是否合理
domain 是否正确
app 是否合理
```

输出：

```
db_to_target_mapping_review.json
```

意义：

避免规则 mapping 错误。

---

# 5. merge-final-mapping

命令：

```
python main.py merge-final-mapping
```

作用：

合并：

```
规则 mapping
LLM review
```

输出：

```
db_to_target_mapping_final.json
```

意义：

得到 **最终 mapping 决策**。

这是 **后续所有步骤的核心输入**。

---

# 6. analyze-semantics

命令：

```
python main.py analyze-semantics
```

作用：

分析字段语义。

例如：

```
VirtualServer.user → customer
LoadBalancer.user → customer
Charge.customer → customer
```

输出：

```
field_semantics.json
```

意义：

解决：

```
user / admin / customer
这种语义混乱
```

---

# 7. analyze-relationship-graph

命令：

```
python main.py analyze-relationship-graph
```

作用：

构建 **模型关系图**。

输入：

```
db_models_analysis.json
db_to_target_mapping_final.json
field_semantics.json
```

输出：

```
relationship_graph.json
```

示例：

```
VirtualServer
 ├── Image
 ├── Customer
 ├── PhysicalServer
 └── IPAddress
```

意义：

让 Agent 理解 **数据模型结构**。

---

# 8. export-relationship-graph-mermaid

命令：

```
python main.py export-relationship-graph-mermaid
```

作用：

把 relationship graph 导出为：

```
Mermaid ER 图
```

意义：

可视化模型关系。

---

# 9. analyze-domain-graph

命令：

```
python main.py analyze-domain-graph
```

作用：

把 **模型关系图提升为领域图**。

示例：

```
compute
 └── VirtualServer

network
 └── IPAddress

asset
 └── PhysicalServer
```

输出：

```
domain_graph.json
```

意义：

理解 **业务领域结构**。

---

# 10. analyze-project-structure

命令：

```
python main.py analyze-project-structure \
  --project NEW_PROJECT
```

作用：

分析新项目代码结构。

提取：

```
apps
models
services
serializers
views
```

输出：

```
project_structure_graph.json
```

意义：

让 Agent **学习新项目架构风格**。

---

# 11. export-project-structure-mermaid

命令：

```
python main.py export-project-structure-mermaid
```

作用：

生成：

```
project_structure.mmd
```

用于画：

```
Architecture diagram
```

---

# 12. generate-django6-model-draft

命令：

```bash
python main.py generate-django6-model-draft \
  --project OLD_PROJECT \
  --model VirtualServer \
  --target workspace/target_blueprint.json
```

作用：

生成 **Django6 model 草案**。

输入：

```
db_models_analysis
final_mapping
field_semantics
relationship_graph
project_structure_graph
reference models
```

输出：

```
workspace/drafts/apps/.../models/xxx.py
```

意义：

AI 自动生成 **新架构模型代码**。

---

# 实际推荐执行流程

真正开发时建议这样跑：

```bash
scan

analyze-models

map-db-to-target

llm-review-db-mapping

merge-final-mapping

analyze-semantics

analyze-relationship-graph

analyze-domain-graph

analyze-project-structure

generate-django6-model-draft
```

