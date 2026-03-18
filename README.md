# Legacy Django Refactor Agent 工作流程

整个 Agent 的完整 pipeline 可以理解为：

```text

  Legacy Django Project
          │
          ▼
  ┌──────────────────────┐
  │ 1. Project Scan      │
  │ - 文件扫描             │
  │ - module 识别         │
  │ - settings / urls    │
  └──────────────────────┘
          │
          ▼
  ┌──────────────────────┐
  │ 2. Model Analysis    │
  │ - Model              │
  │ - Fields             │
  │ - FK / M2M           │
  │ - Constants / Choices│
  └──────────────────────┘
          │
          ▼
  ┌──────────────────────┐
  │ 3. Model Mapping     │
  │ - 旧模型 → 新 app     │
  │ - 旧模型 → 新 domain  │
  └──────────────────────┘
          │
          ▼
  ┌──────────────────────┐
  │ 4. LLM Review        │
  │ - 复核 mapping        │
  │ - 修正规则误差         │
  └──────────────────────┘
          │
          ▼
  ┌──────────────────────┐
  │ 5. Final Merge       │
  │ - 合并规则 + LLM      │
  │ - 生成 final mapping │
  └──────────────────────┘
          │
          ├───────────────────────────────┐
          │                               │
          ▼                               ▼
  ┌──────────────────────┐       ┌──────────────────────┐
  │ 6. Semantic Analysis │       │ 9. Project Structure │
  │ - user/customer语义   │       │ - apps               │
  │ - operator/customer  │       │ - models             │
  │ - 字段业务角色         │       │ - serializers        │
  └──────────────────────┘       │ - services / views   │
          │                      └──────────────────────┘
          ▼                               │
  ┌──────────────────────┐                │
  │ 7. Relationship Graph│                │
  │ - 模型关系图           │                │
  │ - 跨模型依赖           │                │
  └──────────────────────┘                │
          │                               │
          ▼                               │
  ┌──────────────────────┐                │
  │ 8. Domain Graph      │                │
  │ - compute            │                │
  │ - asset              │                │
  │ - network            │                │
  │ - core               │                │
  └──────────────────────┘                │
          └───────────────┬───────────────┘
                          ▼
                ┌────────────────────────┐
                │ 10. AI Model Generator │
                │ - Model Context        │
                │ - Reference Selection  │
                │ - Relationship Graph   │
                │ - Field Semantics      │
                │ - Project Rules        │
                └────────────────────────┘
                          │
                          ▼
                New Django 6 Model Draft
```


# CLI 命令表（按执行顺序）
| 顺序 | 命令 | 示例命令 | 作用 | 输出 |
| -- |---- | ---- | --- | --- |
| 1  | scan                              | `python main.py scan -p /Users/xxx/Desktop/Projects/nexus`                                                                                               | 扫描 legacy Django 项目结构，统计 Python 文件、templates、modules、settings.py、urls.py 等信息 | `reports/project_scan.json`                |
| 2  | analyze-models                    | `python main.py analyze-models -p /Users/xxx/Desktop/Projects/nexus --module db`                                                                         | 分析 legacy 项目中指定 module（如 db）里的 Django models，提取字段、关系、Meta 等                  | `reports/db_models_analysis.json`          |
| 3  | map-db-to-target                  | `python main.py map-db-to-target -p /Users/xxx/Desktop/Projects/nexus --target workspace/target_blueprint.json`                                          | 将 legacy models 映射到新项目架构 blueprint                                           | `reports/db_to_target_mapping.json`        |
| 4  | llm-review-db-mapping             | `python main.py llm-review-db-mapping --target workspace/target_blueprint.json`                                                                             | 使用大模型复核第3步生成的模型映射是否合理                                                        | `reports/db_to_target_mapping_review.json` |
| 5  | merge-final-mapping               | `python main.py merge-final-mapping`                                                                                                                        | 合并规则映射和 LLM 复核结果，生成最终模型映射                                                    | `reports/db_to_target_mapping_final.json`  |
| 6  | analyze-semantics                 | `python main.py analyze-semantics`                                                                                                                          | 分析模型字段语义（如 user → customer），解决语义歧义                                           | `reports/field_semantics.json`             |
|7|analyze-enums|`python main.py analyze-enums`|分析model中枚举字段|reports/enum_analysis.json|
| 8  | analyze-relationship-graph        | `python main.py analyze-relationship-graph`                                                                                                                 | 构建 legacy 模型关系图（ForeignKey、ManyToMany 等）                                     | `reports/relationship_graph.json`          |
| 9  | export-relationship-graph-mermaid | `python main.py export-relationship-graph-mermaid`                                                                                                          | 将模型关系图导出为 Mermaid 图                                                          | `reports/relationship_graph.mmd`           |
| 10  | analyze-domain-graph              | `python main.py analyze-domain-graph`                                                                                                                       | 根据关系图生成领域结构图（domain graph）                                                   | `reports/domain_graph.json`                |
| 11 | analyze-project-structure         | `python main.py analyze-project-structure -p /Users/xxx/Desktop/Projects/re-nexus`                                                                          | 分析新项目代码结构（apps / models / serializers / services 等）                          | `reports/project_structure_graph.json`     |
| 12 | export-project-structure-mermaid  | `python main.py export-project-structure-mermaid`                                                                                                           | 将项目结构图导出为 Mermaid 图                                                          | `reports/project_structure_graph.mmd`      |
| 13 | generate-django6-model-draft      | `python main.py generate-django6-model-draft --project /Users/xxx/Desktop/Projects/nexus --model VirtualServer --target workspace/target_blueprint.json` | 根据前面所有分析结果，为指定 legacy 模型生成 Django6 新架构模型草案                                   | `workspace/drafts/apps/.../models/*.py`    |
|14|generate-serializer-draft|`python main.py generate-serializer-draft --model SSHPublicKey`|给新model生成 serializers|`workspace/drafts/apps/.../serializers/*.py`|
|15|generate-view-draft|`python main.py generate-view-draft \     ~/Desktop/Projects/refactoring-agent -m VirtualServer`|给新 serializers生成 view|`workspace/drafts/apps/.../vies/*.py`|

# 目文件说明

| 路径         | 说明                |
|:---------- |:----------------- |
| `analyzers/domain_graph_analyzer.py`         | 根据模型关系图进一步归纳业务领域结构，输出 domain graph。|
| `analyzers/domain_mapper.py`                 | 负责把 legacy 模型映射到新项目的 app / domain / file。 |
| `analyzers/domain_semantic_analyzer.py`      | 分析字段和模型的业务语义，例如 `user` 更像 `customer` 还是 `operator`。   |
| `analyzers/model_analyzer.py`                | 解析 legacy Django model，提取字段、关系、常量、默认值、choices 等结构化信息。 |
| `analyzers/model_context_enricher.py`        | 为单个模型生成完整上下文包，整合模型分析结果、映射结果、使用线索、字段提示等信息。 |
| `analyzers/project_scanner.py`               | 扫描 legacy 项目目录结构，统计文件、模块、settings、urls 等基础信息。|
| `analyzers/project_structure_analyzer.py`    | 扫描新项目 `apps/` 目录，分析真实工程结构，用于后续参考代码选择。 |
| `analyzers/reference_selector.py`            | 为当前要生成的模型自动挑选最相关的新项目参考代码。 |
| `analyzers/relationship_graph_analyzer.py`   | 基于模型字段关系构建模型关系图，输出关系边和节点。   |
|`analyzers/action_flow_analyzer.py`|分析业务行为|
| `tasks/analyze_domain_graph.py`              | 调用 `domain_graph_analyzer`，生成 domain graph 报告。|
| `tasks/analyze_models.py`                    | 调用 `model_analyzer`，生成模型分析报告。|
| `tasks/analyze_project_structure.py`         | 调用 `project_structure_analyzer`，生成新项目结构报告。|
| `tasks/analyze_relationship_graph.py`        | 调用 `relationship_graph_analyzer`，生成模型关系图报告。 |
| `tasks/analyze_semantics.py`                 | 调用 `domain_semantic_analyzer`，生成字段语义分析结果。  |
| `tasks/export_project_structure_mermaid.py`  | 将项目结构图导出为 Mermaid 格式，方便可视化。 |
| `tasks/export_relationship_graph_mermaid.py` | 将模型关系图导出为 Mermaid 格式。   |
| `tasks/generate_django6_model_draft.py`      | 核心代码生成任务，基于上下文、参考代码和规则生成 Django6 model 草稿。  |
| `tasks/llm_review_mapping.py`                | 调用大模型复核 legacy model → target 架构映射结果。、|
| `tasks/map_db_to_target.py`                  | 执行规则映射，把 legacy `db` 模型映射到新架构。|
| `tasks/merge_final_mapping.py`               | 合并规则映射和 LLM 复核结果，生成最终映射文件。|
| `tasks/scan_project.py`                      | 调用 `project_scanner`，生成项目扫描报告。 |
|`tasks/generate_view_draft.py`|生成views|
|`tasks/generate_serializer_draft.py`|生成 serializers|
|`tasks/analyze_action_flows.py`|生成业务流数据|
| `llm/client.py`                              | 大模型客户端封装，负责调用 OpenAI / Claude 等接口并返回结果。|
| `tools/fs_tools.py`                          | 文件系统工具函数，如读写文本、路径处理等。   |
| `tools/json_tools.py`                        | JSON 读写工具函数。 |
| `tools/project_tools.py`                     | 项目级辅助函数，如查找 module、发现 model 文件等。|
| `tools/report_tools.py`                      | 报告输出工具，负责写 JSON / Markdown 报告。    |
| `workspace/project_rules.json`               | 项目级规则配置，定义身份模型、字段语义、迁移规则等。|
| `workspace/reference_models.json`            | 参考模型白名单，指定哪些已完成的新项目文件应优先作为参考。    |
| `workspace/target_blueprint.json`            | 新项目目标架构蓝图，定义 app / domain / file 的目标结构。 |
| `config.py`                                  | 全局配置文件，通常放编码、默认参数、路径等公共配置。     |
| `main.py`                                    | CLI 入口文件，统一注册并调度所有命令。     |
| `README.md`                                  | 项目说明文档，介绍用途、命令、流程和使用方法。|
| `requirements.txt`                           | Python 依赖列表。         |





python main.py analyze-models \
  -p /Users/machao/Desktop/Projects/nexus

python main.py map-db-to-target \
  -p /Users/machao/Desktop/Projects/nexus \
  --target workspace/target_blueprint.json

python main.py merge-final-mapping

python main.py analyze-semantics

python main.py analyze-relationship-graph
