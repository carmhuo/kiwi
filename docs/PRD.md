# Kiwi企业级DataAgent项目PRD文档

---

## 文档基本信息

- **文档编号**：PRD001
- **产品名称**：Kiwi
- **版本号**：1.2
- **编写人**：kiwi团队
- **编写日期**：2025-07-04
- **审核人**：kiwi团队
- **审核日期**：2025-07-04

## 文档修订记录

| 版本  | 日期         | 修改人    | 修改内容        |
|-----|------------|--------|-------------|
| 1.0 | 2025-07-04 | Kiwi团队 | 初始版本        |
| 1.1 | 2025-07-04 | Kiwi团队 | 增加Agent版本管理 |
| 1.2 | 2025-07-04 | Kiwi团队 | 补充非功能性需求    |

---

## 1. 项目概述

### 1.1 背景与目的

传统的BI应用构建流程复杂且耗时，Kiwi项目旨在通过DataAgent技术解决以下问题：

- 简化数据探索流程
- 赋能业务人员和数据分析师
- 加速数据洞察与决策支持

Kiwi借助GenAI技术简化数据访问与分析流程。 其数据分析代理（Data Analysis
Agent）支持用户以自然语言提问，系统会自动将这些提问转化为针对数据域(Domain)的精准查询。

**核心目标**： 实现自然语言到数据分析的智能转换，提供端到端的数据洞察解决方案。

### 1.2 功能概览

| 模块      | 功能点             | 描述                       |
|---------|-----------------|--------------------------|
| 用户管理    | 登录/登出           | JWT认证的用户管理系统             |
| 项目管理    | 项目空间            | 创建和管理数据项目                |
| 数据管理    | 数据源管理           | 支持多种数据库连接配置              |
|         | 数据集管理           | 定义和组织数据源中的表/字段           |
| Agent管理 | TEXT2SQL        | 自然语言转SQL的智能Agent         |
|         | RETRIEVAL       | 知识检索智能Agent              |
|         | DATA_ENRICHMENT | 网页信息提取Agent，将非结构化信息转为结构化 |
| 对话系统    | 交互式对话           | 支持历史查询的对话界面              |
|         | 结果反馈            | 用户对结果的喜欢/不喜欢反馈           |
| 权限控制    | RBAC模型          | 系统管理员/项目管理员/数据分析师/普通用户   |

## 2. 详细功能需求

### 2.1 用户认证管理

- **登录功能**：用户名+密码认证; SSO认证
- **登出功能**：安全终止会话
- **用户信息**：获取当前用户信息及角色

### 2.2 项目管理

```mermaid
graph TD
    A[创建项目] --> B[添加成员]
    B --> C[设置角色]
    C --> D[管理项目资源]
```

### 2.3 数据源管理

支持的数据源类型：

- 关系数据库
    - SQLite
    - MySQL
    - PostgreSQL
- 数据仓库
    - Impala
    - Hive
- OLAP引擎
    - DuckDB
    - StarRocks
- 文件服务
    - S3
    - SFTP

连接配置：

```json
{
  "host": "db.example.com",
  "port": 5432,
  "database": "sales",
  "username": "admin",
  "password": "******"
}
```

### 2.4 数据集管理

数据集配置要素：

* 关联数据源
* 表映射关系
* 字段定义
* 数据关系描述
* 敏感字段标记,并在查询结果中自动应用脱敏模板

### 2.5 Agent管理系统

| Agent类型         | 功能描述                         | 配置参数                           |
|-----------------|------------------------------|--------------------------------|
| TEXT2SQL        | 自然语言转SQL                     | 模型类型、温度值、最大token数              |
| RETRIEVAL       | 数据检索                         | 检索策略、返回结果数                     |
| DATA_ENRICHMENT | 从各种网络资源中收集信息，将获取的非结构化信息转为结构化 | 设置rearch_topic、定义输出数据的结构、返回结果数 |
| (可扩展)           | 	未来扩展类型                      | 	自定义配置                         |

### 2.6 对话系统

**流程图**

```mermaid
flowchart TD
    A[开始] --> B[用户发送查询]
    B --> C[Backend请求Agent生成SQL]
    C --> D{生成SQL成功}
    D -->|是| E[Backend执行SQL查询]
    D -->|否| F[Backend返回重构提示]
    F --> M[结束]
    E --> G{执行成功}
    G -->|是| H[Backend请求生成图表]
    G -->|否| I[Backend返回错误提示]
    I --> M
    H --> J[Agent生成图表配置]
    J --> K[Backend返回结果]
    K --> M
```

**错误类型分类处理**

| 错误类型    | 错误代码              | 处理策略      | 用户提示           |
|---------|-------------------|-----------|----------------|
| SQL生成失败 | AGENT_FAILURE     | 重试3次      | 智能解析失败，请尝试简化问题 |
| 查询超时    | QUERY_TIMEOUT     | 触发熔断+降级查询 | 查询超时，已返回简化结果   |
| 数据库连接失败 | DB_CONN_FAIL      | 切换备用数据源   | 系统维护中，已切换备用数据  |
| 权限不足    | PERMISSION_DENIED | 终止查询      | 您无权访问此数据       |
| 语法错误    | SQL_SYNTAX_ERROR  | 日志记录+终止   | 内部错误，已通知管理员    |

**序列图**

```mermaid
sequenceDiagram
    participant User
    participant Frontend
    participant Backend
    participant Agent
    participant DuckDB
    User ->> Frontend: 输入自然语言查询
    Frontend ->> Backend: POST /conversations/{id}/messages
    Backend ->> Agent: 调用TEXT2SQL Agent
    Agent ->> Backend: 生成SQL语句
    Backend ->> DuckDB: 执行SQL查询
    DuckDB ->> Backend: 返回查询结果
    Backend ->> Agent: 生成图表配置
    Agent ->> Frontend: 返回完整响应
    Frontend ->> User: 展示文字+图表结果
    User ->> Frontend: 提交反馈（可选）
```

反馈选项：

- ✅ 结果正确

- ⚠ 部分正确

- ❌ 完全错误

- 💡 建议改进

**故障恢复流程**

```mermaid
flowchart TD
    A[检测到持续失败] --> B{错误类型}
    B -->|SQL生成失败| C[切换备用Agent模型]
    B -->|查询超时| D[启动熔断机制]
    B -->|数据库故障| E[切换只读副本]
    C --> F[通知运维团队]
    D --> F
    E --> F
    F --> G[根本原因分析]
    G --> H[修复方案]
    H --> I[验证修复]
    I --> J[恢复服务]
    J --> K[生成事故报告]
```

### 2.7 权限管理系统

权限功能是系统安全的重要基础保障，Kiwi提供了提供了完善安全的权限系统。

角色权限矩阵：

| 功能       | 系统管理员 | 项目管理员  | 数据源管理员 | 数据分析师  | 普通用户 |
|----------|-------|--------|--------|--------|------|
| 创建项目     | ✓     | ✗      | ✗      | ✗      | ✗    |
| 删除项目     | ✓     | ✗      | ✗      | ✗      | ✗    |
| 添加成员     | ✓     | ✓      | ✗      | ✗      | ✗    |
| 创建数据源    | ✓     | ✓      | ✓      | ✗      | ✗    |
| 查看数据源    | ✓     | △      | ✓      | ✓      | ✗    |
| 编辑数据源    | ✓     | △      | ✓      | ✗      | ✗    |
| 删除数据源    | ✓     | △      | △      | ✗      | ✗    |
| 关联数据源到项目 | ✓     | △      | ✓      | ✗      | ✗    |
| 创建数据集    | ✓     | ✓      | ✗      | ✓      | ✗    |
| 查看数据集    | ✓     | ✓      | ✗      | ✓      | ✓    |
| 查询数据     | ✓     | ✓      | ✗      | ✓      | ✓    |
| 管理Agent  | ✓     | ✓      | ✗      | ✗      | ✗    |
| 查看敏感数据   | ✓     | △(需审批) | ✗      | △(需审批) | ✗    |

✓: 完全权限 △: 仅自己创建的 ✗: 无权限

- 项目管理员： 拥有管理项目及项目内的资源和成员的权限，同时拥有创建数据源和数据集等权限
- 数据源管理员： 拥有创建数据源的权限及编辑所有数据源的权限。
- 数据分析师： 拥有所在项目即席查询的操作权限，同时拥有创建数据集权限
- 普通用户： 拥有所在项目的报表查看权限。

### 2.8 检索功能
设计一个RAG(Retrieval-Augmented Generation)系统，用于增强Kiwi DataAgent的text2sql功能。
该方案将利用ChromaDB向量库实现向量检索功能，支持元数据检索以提升SQL生成准确性。
后期支持扩展集成其他向量库。

**核心目标**

- 实现text2sql元数据的向量化存储与检索

- 支持三类关键信息的检索：

  - 查询语句-SQL对（自然语言查询与对应SQL）

  - 表结构schema信息

  - 业务文档与数据字典

检索流程:
```mermaid
graph TD
    A[用户自然语言查询] --> B[RAG检索模块]
    B --> C[向量数据库 ChromaDB]
    C --> D[相关元数据]
    D --> E[LLM生成SQL]
    E --> F[最终SQL输出]
    
    subgraph 数据准备
        G[历史查询-SQL对] --> H[向量化存储]
        I[表结构schema] --> H
        J[业务文档] --> H
    end
```

数据更新机制:
```mermaid
sequenceDiagram
    participant User
    participant System
    participant ChromaDB
    
    User ->> System: 执行新查询
    System ->> System: 生成SQL并执行
    User ->> System: 提供反馈
    System ->> ChromaDB: 存储查询-SQL对(带反馈评分)
    
    User ->> System: 更新表结构
    System ->> ChromaDB: 更新表schema信息
    
    User ->> System: 上传业务文档
    System ->> ChromaDB: 添加或更新业务文档
```

## 3. 前端界面规范

### 3.1 整体布局

```text
+-----------------------------------+
| Logo | 平台名称 | 帮助 | 用户信息 |
+-----------------+-----------------+
| 左侧菜单        |                 |
| - 对话         |  内容显示区      |
|   - 历史对话    |                 |
| - 配置         |                 |
|   - 成员管理    |                 |
|   - 权限管理    |                 |
|   - 项目管理  |                 |
|   - 数据源管理  |                 |
|   - 数据集管理  |                 |
|   - Agent管理   |                 |
+-----------------+-----------------+
```

### 3.2 关键页面设计

#### 3.2.1 对话界面

```markdown
[对话标题：Q3销售分析]
-----------------------------------
[用户] 2023-07-04 14:30
显示2023年Q3各产品销量

[系统] 2023-07-04 14:31

### 分析结果

2023年第三季度各产品销售情况如下：

[柱状图]
产品A: ￥1,200,000
产品B: ￥980,000
产品C: ￥1,500,000

### 使用的SQL

```sql
SELECT product, SUM(sales) 
FROM sales_data 
WHERE quarter = 'Q3' AND year = 2023 
GROUP BY product
```

[反馈按钮] ✅ 结果正确 ⚠ 部分正确 ❌ 完全错误 💡 建议改进

#### 3.2.2 数据源管理界面

- 数据源列表视图
- 新建数据源表单
- 连接测试功能
- 数据预览功能

### 3.2.3 数据集配置页面

```markdown
[数据集配置向导]
步骤1：选择数据源
☑ MySQL (生产库) [别名: mysql_prod]
☑ PostgreSQL (客户库) [别名: pg_customers]
☐ SQLite (本地缓存)

步骤2：表映射配置
| 源数据源 | 源表名 | 目标表名 | 字段筛选 |
|----------------|----------|-------------|---------------|
| mysql_prod | orders | sales_orders| id,amount,date|
| pg_customers | users | customers | id,name,email |

步骤3：关系配置
[图形化关系编辑区]
orders.cust_id → customers.id
```

## 4. 后端系统设计

### 4.1 系统架构

Kiwi数据智能体架构具备以下特点：

- 运用多个智能体（GenAI 智能体）和嵌入技术（embeddings）来理解用户以自然语言提出的查询。
- 借助领域嵌入、指标与维度元数据嵌入、**维度数据嵌入**，以及关于这些元素的定义信息和所使用术语的分类体系。
- 通过示例和反馈循环不断优化其对查询的理解能力和准确性。
- 将自然语言查询转化为可针对领域（Domain）执行的查询，并利用执行层来获取查询结果。

#### 4.1.1 系统上下文

```mermaid
graph TD
%% 用户角色
    biz_customer["业务用户"] -->|决策支持| Kiwi
    ba_customer["业务分析师"] -->|数据洞察| Kiwi
    admin["数据工程师"] -->|数据源接入/创建数据集| Kiwi
%% 外部系统
    Kiwi["Kiwi数据智能分析平台"] -->|data ingest| DataWarehouse["数据仓库<br>(提供主题数据)"]
    Kiwi -->|data ingest| FilePlatform["对象存储<br>(支持parquet/json/...)"]
    Kiwi -->|data ingest| DatAPI["数据集市<br>OLAP/sqlite/mysql/..."]
```

#### 4.1.2 逻辑架构

```mermaid
graph TD
    subgraph user["最终用户"]
        direction TB
        biz_user[业务用户]
        ba["业务分析师"]
        de["数据工程师"]
    end

    subgraph interface_layer["用户接入层"]
        web_ui["WEB_UI"]
    end

    subgraph app_layer["应用逻辑层"]
        conversation("对话管理")
        data_source("数据源管理")
        dataset("数据集管理")
        report("报表展示")
        agent("Agent管理")
    end
    subgraph service_layer["服务逻辑层"]
        file_service("文件服务")
        email_service["邮件服务"]
    end

    subgraph source_layer["数据源"]
        data_warehouse["数据仓库"]
        data_market["数据集市"]
        olap_engine["OLAP引擎"]
        rdbms["关系数据库"]
        os["对象存储"]
    end

    user --> interface_layer
    interface_layer --> app_layer
    app_layer --> service_layer
    service_layer --> source_layer


```

#### 4.1.3 技术架构

```mermaid
graph TD
%% ========== 用户角色 ==========
    biz_customer["业务用户"] -->|AI对话/获取洞察| Frontend
    ba_customer["业务分析师"] -->|AI对话/获取洞察| Frontend
    admin["数据工程师"] -->|数据源接入/创建数据集| Frontend
%% ========== 前端系统 ==========
    Frontend["Web前端<br>Vue + H5 + Nginx [+ DuckDB-Wasm]"]
%% ========= 网关 ===========
    Gateway["API网关"]
%% ========== 核心服务容器 ==========
    subgraph Kiwi_Core["Kiwi 核心服务"]
        Backend["后端服务<br>Guicorn + ASGI Uvicorn + FastAPI"]
        Database[("业务数据库<br>Sqlite/PostgreSQL")]
        LangchainService["Agent服务<br>LLM + LangChain"]
        DuckDB["DuckDB 分析引擎<br>（嵌入式联邦查询）"]
        VectorDB[("向量数据库<br>Chroma/Milvus")]
    end
%% ========== 外部数据源 ==========
    subgraph data_source["数据源"]
        DataWarehouse[("数据仓库<br>Hive/OLAP")]
        FilePlatform[("对象存储<br>S3/OSS")]
        OLAP[("OLAP引擎<br>StarRocks/Doris/Clickhouse")]
        OtherDBs[("RDBMS")]
    end
%% ========== 数据流 ==========    
    Frontend --> Gateway
    Gateway --> Backend
    Backend --> Database
    Backend --> VectorDB
    Backend --> LangchainService
    LangchainService --> DuckDB
    DuckDB -.->|联邦查询| data_source
%% ========== 图例说明 ==========
%%    classDef external fill: #f9f, stroke: #333, stroke-dasharray: 5 5
%%    classDef core fill: #e6f7ff, stroke: #1890ff
%%    classDef db fill: #f6ffed, stroke: #52c41a
%%    class Kiwi_Core core
%%    class DataWarehouse, FilePlatform, rdbms, ExternalDB external
%%    class Database, VectorDB db
```

- FastAPI + Uvicorn 提供高性能异步 API
- Gunicorn 负责多进程管理，提高并发
- Nginx 反向代理，支持负载均衡 & HTTPS

#### 4.1.4 集成架构

#### 4.1.5 部署架构

### 4.2 核心API概览

#### 认证管理

| 端点           | 方法   | 功能       |
|--------------|------|----------|
| /auth/login  | POST | 用户登录     |
| /auth/logout | POST | 用户登出     |
| /auth/me     | GET  | 获取当前用户信息 |

#### 项目管理

| 端点                     | 方法   | 功能     |
|------------------------|------|--------|
| /projects              | POST | 创建新项目  |
| /projects              | GET  | 获取项目列表 |
| /projects/{project_id} | GET  | 获取项目详情 |

#### 权限管理

| 端点                                       | 方法     | 功能     |
|------------------------------------------|--------|--------|
| /projects/{project_id}/members           | POST   | 添加成员   |
| /projects/{project_id}/members           | GET    | 获取成员信息 |
| /projects/{project_id}/members/{user_id} | DELETE | 删除成员   |

#### 数据管理

| 端点                          | 方法   | 功能           |
|-----------------------------|------|--------------|
| /data-sources               | POST | 创建全局数据源      |
| /projects/{id}/data-sources | POST | 关联数据源到项目     | 
| /projects/{id}/data-sources | GET  | 获取项目关联的数据源列表 |

| 端点                                  | 方法   | 功能           |
|-------------------------------------|------|--------------|
| /data-sources                       | POST | 创建全局数据源      |
| /projects/{project_id}/data-sources | POST | 关联数据源到项目     |
| /projects/{project_id}/data-sources | GET  | 获取项目关联的数据源列表 |
| /projects/{project_id}/datasets     | POST | 创建数据集        |
| /datasets/{dataset_id}              | GET  | 获取数据集详情      |

#### Agent管理

| 端点                            | 方法   | 功能      |
|-------------------------------|------|---------|
| /projects/{project_id}/agents | POST | 创建Agent |
| /agents/{agent_id}/rollback   | POST | 创建Agent |

#### 对话系统

| 端点                                        | 方法   | 功能     |
|-------------------------------------------|------|--------|
| /projects/{project_id}/conversations      | POST | 创建新对话  |
| /conversations/{conversation_id}/messages | POST | 发送消息   |
| /conversations/{conversation_id}/messages | GET  | 获取历史消息 |
| /messages/{conversation_id}/feedback      | POST | 提交反馈   |

### 4.3 数据库设计

#### 4.3.1 E-R图

```mermaid
erDiagram
    USER ||--o{ USER_ROLE: "分配"
    ROLE ||--o{ USER_ROLE: "属于"
    USER ||--o{ PROJECT: "创建"
    PROJECT ||--o{ PROJECT_MEMBER: "拥有成员"
    USER ||--o{ PROJECT_MEMBER: "属于"
    ROLE ||--o{ PROJECT_MEMBER: "具有角色"
%% 项目与数据源关系（多对多）
    PROJECT ||--o{ PROJECT_DATA_SOURCE: "包含"
    DATA_SOURCE ||--o{ PROJECT_DATA_SOURCE: "引用"
%% 数据集与项目数据源关系（多对多）
    DATASET ||--o{ DATASET_PROJECT_SOURCE: "使用"
    PROJECT_DATA_SOURCE ||--o{ DATASET_PROJECT_SOURCE: "被引用"
    PROJECT ||--o{ DATASET: "包含"
    PROJECT ||--o{ AGENT: "包含"
    PROJECT ||--o{ CONVERSATION: "包含"
    USER ||--o{ CONVERSATION: "发起"
    CONVERSATION ||--o{ MESSAGE: "包含"
    USER ||--o{ MESSAGE: "创建"
    AGENT ||--o{ MESSAGE: "生成"
    AGENT ||--o{ AGENT_VERSION: "保存"
    AGENT_VERSION ||--o{ AGENT_METRIC: "记录"
    USER ||--o{ AUDIT_LOG: "操作"
```

##### 4.3.2 表关系说明

**用户与角色关系：**

- 多对多关系（USER ⇄ ROLE）

- 通过USER_ROLE关联表实现

**项目结构：**

```mermaid
graph TD
    PROJECT --> DATA_SOURCE
    PROJECT --> DATASET
    PROJECT --> AGENT
    PROJECT --> CONVERSATION
```

**项目成员关系：**

- 项目与用户多对多关系
- 通过PROJECT_MEMBER表管理
- 每个成员在项目中有一个角色

**数据源与项目关系：**

```mermaid
graph TD
    A[全局数据源池] -->|关联| B(项目A)
    A -->|关联| C(项目B)
    A -->|关联| D(项目C)

    subgraph 全局层
        A
    end

    subgraph 项目层
        B
        C
        D
    end
```

同一项目内别名必须唯一，否则会导致：

- 数据集配置无法明确引用数据源（PRD 3.2.3节）

- SQL生成时表前缀冲突（prod_db.orders 指向不明）

- 联邦查询执行混乱

```mermaid
graph TD
    P1[项目A] --> A1[数据源X 别名=prod_db]
    P1 --> A2[数据源Y 别名=prod_db] --> 冲突!
    P2[项目B] --> B1[数据源X 别名=prod_db] --> 允许
```

**数据集与数据源关系：**

- 多对多关系
- 通过DATASET_DATA_SOURCE表管理

**对话系统关系：**

```mermaid
graph LR
    CONVERSATION --> MESSAGE1[Message 1]
    CONVERSATION --> MESSAGE2[Message 2]
    CONVERSATION --> MESSAGE3[Message 3]
    AGENT --> MESSAGE2
```

#### 关键表结构

##### 用户表 (user)

| 字段              | 类型           | 描述     | 约束                        |
|:----------------|:-------------|:-------|:--------------------------|
| id              | VARCHAR(36)  | 主键UUID | PK, AI                    |
| username        | VARCHAR(50)  | 用户名    | UNIQUE, NOT NULL          |
| hashed_password | VARCHAR(128) | 密码哈希   | NOT NULL                  |
| email           | VARCHAR(100) | 邮箱     | NOT NULL                  |
| is_active       | BOOLEAN      | 是否激活   | DEFAULT 1                 |
| created_at      | TIMESTAMP    | 创建时间   | DEFAULT CURRENT_TIMESTAMP |
| updated_at      | TIMESTAMP    | 更新时间   | DEFAULT CURRENT_TIMESTAMP |

##### 角色表 (role)

| 字段          | 类型          | 描述                                             | 约束                        |
|:------------|:------------|:-----------------------------------------------|:--------------------------|
| code        | INTEGER     | 角色代码, 0=系统管理员,1=项目管理员,2=数据源管理员,3=数据分析师,99=普通用户 | PK, NOT NULL              |
| name        | VARCHAR(50) | 角色名称                                           | UNIQUE, NOT NULL          |
| description | TEXT        | 角色描述                                           |                           |
| created_at  | TIMESTAMP   | 创建时间                                           | DEFAULT CURRENT_TIMESTAMP |
| updated_at  | TIMESTAMP   | 更新时间                                           | DEFAULT CURRENT_TIMESTAMP |

##### 用户角色关联表 (user_role)

| 字段        | 类型          | 描述   | 约束                        |
|:----------|:------------|:-----|:--------------------------|
| user_id   | VARCHAR(36) | 用户ID | FK → user(id), NOT NULL   |
| role_code | INTEGER     | 角色ID | FK → role(code), NOT NULL |
|           |             |      | PK (user_id, role_code)   |

##### 项目表 (project)

| 字段          | 类型           | 描述     | 约束                        |
|:------------|:-------------|:-------|:--------------------------|
| id          | VARCHAR(36)  | 主键UUID | PK, AI                    |
| name        | VARCHAR(100) | 项目名称   | NOT NULL                  |
| description | TEXT         | 项目描述   |                           |
| owner_id    | VARCHAR(36)  | 所有者ID  | FK → user(id)             |
| created_at  | TIMESTAMP    | 创建时间   | DEFAULT CURRENT_TIMESTAMP |
| updated_at  | TIMESTAMP    | 更新时间   | DEFAULT CURRENT_TIMESTAMP |

##### 数据源表 (data_source)

| 字段                | 类型           | 描述         | 约束                        |
|:------------------|:-------------|:-----------|:--------------------------|
| id                | VARCHAR(36)  | 主键UUID     | PK, AI                    |
| name              | VARCHAR(100) | 数据源名称      | NOT NULL                  |
| type              | VARCHAR(20)  | 数据库类型      | NOT NULL                  |
| description       | TEXT         | 项目描述       |                           |
| connection_config | TEXT         | 连接配置(JSON) | NOT NULL                  |
| owner_id          | VARCHAR(36)  | 所有者ID      | FK → user(id)             |
| created_by        | VARCHAR(36)  | 创建者ID      | FK → user(id)             |
| created_at        | TIMESTAMP    | 创建时间       | DEFAULT CURRENT_TIMESTAMP |
| updated_at        | TIMESTAMP    | 更新时间       | DEFAULT CURRENT_TIMESTAMP |

##### 项目-数据源关联表(project_data_source)

| 字段             | 类型           | 描述       | 约束                                                                |
|:---------------|:-------------|:---------|:------------------------------------------------------------------|
| project_id     | VARCHAR(36)  | 项目ID     | FK → project(id), NOT NULL                                        |
| data_source_id | VARCHAR(36)  | 数据源ID    | FK → data_source(id), NOT NULL                                    |
| alias          | VARCHAR(100) | 项目内数据源别名 | NOT NULL                                                          |
| is_active      | BOOLEAN      | 是否启用     | DEFAULT 1                                                         |                    |
|                |              |          | PK (project_id, data_source_id),  <br/>UNIQUE (project_id, alias) |

**别名管理规则**

1. **唯一性约束**： 同一项目内数据源别名必须唯一,UNIQUE (project_id, alias)
2. **默认别名生成**：

- 创建时自动生成（若未提供）：

   ```text
   def generate_alias(data_source_name):
    return f"ds_{sanitize_name(data_source_name)}_{short_uuid()}"
   ```

3. **修改限制**
    - 别名创建后不允许修改（避免影响已配置的数据集）
    - 如需变更，需先解除所有数据集的关联

##### 数据集表 (dataset)

| 字段            | 类型           | 描述          | 约束                        |
|:--------------|:-------------|:------------|:--------------------------|
| id            | VARCHAR(36)  | 主键UUID      | PK, AI                    |
| project_id    | INTEGER      | 所属项目ID      | FK → project(id)          |
| name          | VARCHAR(100) | 数据集名称       | NOT NULL                  |
| description   | TEXT         | 数据描述        |                           |
| configuration | TEXT         | 数据集配置(JSON) | NOT NULL                  |
| created_by    | INTEGER      | 创建者ID       | FK → user(id)             |
| created_at    | TIMESTAMP    | 创建时间        | DEFAULT CURRENT_TIMESTAMP |
| updated_at    | TIMESTAMP    | 更新时间        | DEFAULT CURRENT_TIMESTAMP |

configuration样例

```json
{
  "tables": [
    {
      "source_alias": "mysql_prod",
      "table_name": "orders",
      "columns": [
        "id",
        "user_id",
        "amount"
      ]
    },
    {
      "source_alias": "pg_prod",
      "table_name": "users",
      "columns": [
        "id",
        "name",
        "email"
      ]
    }
  ],
  "table_mappings": [
    {
      "source_alias": "mysql_prod",
      "source_table": "orders",
      "target_name": "sales_orders"
    },
    {
      "source_alias": "pg_prod",
      "source_table": "users",
      "target_name": "customers"
    }
  ],
  "relationships": [
    {
      "left_table": "sales_orders",
      "left_column": "user_id",
      "right_table": "customers",
      "right_column": "id",
      "type": "one-to-many"
    }
  ]
}
```

- source_alias: 应项目内数据源别名（project_data_source.alias）;
- target_name: 表名，数据集内唯一；

##### 数据集项目数据源表(dataset_project_source)

| 字段                | 类型           | 描述    | 约束                                 |
|:------------------|:-------------|:------|:-----------------------------------|
| dataset_id        | VARCHAR(36)  | 数据集ID | FK → dataset(id)                   |
| data_source_alias | VARCHAR(100) | 数据源别名 | FK → project_data_source(alias)    |
|                   |              |       | PK (dataset_id, data_source_alias) |

##### Agent表 (agent)

| 字段         | 类型           | 描述         | 约束                        |
|:-----------|:-------------|:-----------|:--------------------------|
| id         | VARCHAR(36)  | 主键UUID     | PK, AI                    |
| project_id | VARCHAR(36)  | 所属项目ID     | FK → project(id)          |
| name       | VARCHAR(100) | Agent名称    | NOT NULL                  |
| type       | VARCHAR(20)  | Agent类型    | NOT NULL                  |
| config     | TEXT         | 配置参数(JSON) | NOT NULL                  |
| created_by | VARCHAR(36)  | 创建者ID      | FK → user(id)             |
| created_at | TIMESTAMP    | 创建时间       | DEFAULT CURRENT_TIMESTAMP |
| updated_at | TIMESTAMP    | 更新时间       | DEFAULT CURRENT_TIMESTAMP |

##### Agent 版本表 (agent_version)

| 字段         | 类型          | 描述           | 约束             |
|:-----------|:------------|:-------------|:---------------|
| id         | VARCHAR(36) | 主键 UUID      | PK             |
| agent_id   | VARCHAR(36) | Agent ID     | FK → agent(id) |
| version    | VARCHAR(20) | 语义化版本 v1.2.3 | NOT NULL       |
| config     | TEXT        | Agent配置信息    | NOT NULL       |
| checksum   | CHAR(64)    | 配置SHA256校验和  | NOT NULL       |
| created_by | VARCHAR(36) | 创建者ID        | FK → user(id)  |
| created_at | TIMESTAMP   | 创建时间         |                |
| is_current | BOOLEAN     | 是否为当前版本      | 默认False        |

##### Agent 指标表 (agent_metric)

| 字段                 | 类型          | 描述       | 约束                     |
|:-------------------|:------------|:---------|:-----------------------|
| id                 | VARCHAR(36) | 主键UUID   | PK                     |
| agent_version_id   | VARCHAR(36) | Agent ID | FK → agent_version(id) |
| sql_gen_latency    | FLOAT       | sql生成延时  | NOT NULL               |
| query_success_rate | FLOAT       | 查询成功率    | NOT NULL               |
| created_at         | TIMESTAMP   | 创建时间     |                        |

##### 对话表 (conversation)

| 字段         | 类型           | 描述     | 约束                        |
|:-----------|:-------------|:-------|:--------------------------|
| id         | VARCHAR(36)  | 主键UUID | PK, AI                    |
| project_id | VARCHAR(36)  | 所属项目ID | FK → project(id)          |
| user_id    | VARCHAR(36)  | 用户ID   | FK → user(id)             |
| title      | VARCHAR(200) | 对话标题   | NOT NULL                  |
| created_at | TIMESTAMP    | 创建时间   | DEFAULT CURRENT_TIMESTAMP |
| updated_at | TIMESTAMP    | 更新时间   | DEFAULT CURRENT_TIMESTAMP |

##### 消息表 (message)

| 字段              | 类型          | 描述         | 约束                             |
|:----------------|:------------|:-----------|:-------------------------------|
| id              | VARCHAR(36) | 主键UUID     | PK, AI                         |
| conversation_id | VARCHAR(36) | 对话ID       | FK → conversation(id)          |
| content         | TEXT        | 消息内容       | NOT NULL                       |
| role            | VARCHAR(10) | 角色         | user/assistant                 |
| sql_query       | TEXT        | 执行的SQL     |                                |
| report_data     | TEXT        | 图表数据(JSON) |                                |
| feedback_type   | INTEGER     | 用户反馈       | 1=结果正确, 0=完全错误, 2=部分正确, 3=建议改进 |
| feedback_text   | TEXT        | 改进建议       | CHECK(feedback_type=3)         |
| created_at      | TIMESTAMP   | 创建时间       | DEFAULT CURRENT_TIMESTAMP      |
| updated_at      | TIMESTAMP   | 更新时间       | DEFAULT CURRENT_TIMESTAMP      |

##### 项目成员表 (project_member)

| 字段         | 类型          | 描述   | 约束                        |
|:-----------|:------------|:-----|:--------------------------|
| project_id | VARCHAR(36) | 项目ID | FK → project(id)          |
| user_id    | VARCHAR(36) | 用户ID | FK → user(id)             |
| role_code  | INTEGER     | 角色ID | FK → role(code)           |
| created_at | TIMESTAMP   | 创建时间 | DEFAULT CURRENT_TIMESTAMP |
| updated_at | TIMESTAMP   | 更新时间 | DEFAULT CURRENT_TIMESTAMP |
|            |             |      | PK (project_id, user_id)  |

##### 审计表 (audit_log)

| 字段          | 类型          | 描述                         | 约束                        |
|-------------|-------------|----------------------------|---------------------------|
| id          | VARCHAR(36) | 主键UUID                     | PK                        |
| operator_id | VARCHAR(36) | 操作人 ID                     | FK → user(id)             |
| action      | VARCHAR(20) | 操作类型（CREATE/UPDATE/DELETE） |                           |
| target_type | VARCHAR(30) | 操作对象类型（DATASOURCE/AGENT）   |                           |
| target_id   | VARCHAR(36) | 操作对象类型（DATASOURCE/AGENT）   |                           |
| old_value   | JSONB       | 操作前的值（JSON 格式）             |                           |
| new_value   | JSONB       | 操作后的值（JSON 格式）             |                           |
| ip_address  | INET        | 操作来源 IP 地址                 |                           |
| created_at  | TIMESTAMP   | 创建时间                       | DEFAULT CURRENT_TIMESTAMP |

#### 数据流

```mermaid
graph TD
    U[用户] -->|发起查询| C(对话会话)
    C -->|包含| M1(用户消息)
    M1 -->|触发| A(Text2SQL Agent)
    A -->|生成| M2(系统消息)
    M2 -->|包含| S[SQL查询]
    S -->|执行| D[(数据源)]
    D -->|返回| R[查询结果]
    R -->|生成| V[可视化图表]
    V -->|保存| M2
```

#### 表索引设计

##### 高频查询字段

```sql
CREATE INDEX idx_message_conversation ON message(conversation_id);
CREATE INDEX idx_message_feedback ON message(feedback);
CREATE INDEX idx_project_owner ON project(owner_id);
CREATE INDEX idx_dataset_project ON dataset(project_id);
CREATE INDEX idx_conversation_user ON conversation(user_id);
CREATE INDEX idx_agent_version ON agent_version(agent_id, version);
CREATE UNIQUE INDEX idx_project_data_source_alias ON project_data_source(project_id, alias);
```

##### 外键索引

```sql
CREATE INDEX fk_data_source_project ON data_source(project_id);
CREATE INDEX fk_conversation_project ON conversation(project_id);
```

#### 数据生命周期

- 数据保留策略：对话历史自动归档机制（如6个月后转冷存储）
- 数据销毁协议：项目删除时的级联数据清除流程

```mermaid
gantt
    title 数据生命周期管理
    dateFormat YYYY-MM-DD
    section 项目数据
        创建项目: active, proj1, 2025-07-01, 1d
        活跃使用: proj2, after proj1, 30d
        归档: proj3, after proj2, 1d

    section 对话数据
        新对话: active, conv1, 2025-07-05, 1d
        活跃对话: conv2, after conv1, 7d
        历史对话: conv3, after conv2, 90d
        自动清理: conv4, after conv3, 1d
```

### 4.4 监控指标

#### Agent监控指标

- SQL生成耗时

- 查询成功率

- 结果准确率

## 5. 非功能性需求

### 5.1 性能指标

| 指标      | 目标值  | 测量方式  |
|---------|------|-------|
| SQL生成延迟 | < 3s | 95百分位 |
| 查询执行时间  | < 5s | 平均响应  |
| 并发用户支持  | 100+ | 压力测试  |

### 5.2 安全要求

#### 方案

```mermaid
graph TD
    A[用户请求] --> B[JWT认证]
    B --> C[RBAC权限校验]
    C --> D[SQL安全过滤器]
    D -->|安全| E[执行查询]
    D -->|危险| F[阻断并告警]
    E --> G[数据脱敏处理]
    G --> H[返回结果]
```

#### 数据加密：

- **传输层**：HTTPS
- **存储层**：敏感字段加密
    - 用户登录密码使用密码哈希函数bcrypt加密存储（单向不可逆）
    - 数据源配置中的密码明文显示在JSON示例中，需使用AES-256加密存储，可通过密钥解密
    - 将密钥存储在环境变量/配置文件中（并确保配置文件的安全）

#### 数据脱敏：

- 定义敏感字段, 身份证/银行卡/手机号
- 确定敏感字段脱敏规则
- 确保敏感字段经过脱敏后输出

```sqlite
CREATE TABLE data_masking_rules (
    id INTEGER PRIMARY KEY,
    field_pattern VARCHAR(100) PRIMARY KEY,
    mask_type TEXT CHECK (status IN ('partial', 'hash', 'full')),
    template VARCHAR(200)  -- 如 "****-****-####-{{last4}}"
);
```

敏感字段审批流程

```mermaid
sequenceDiagram
    User ->>+ ApprovalService: 敏感数据访问申请
    ApprovalService ->> Admin: 发送审批通知
    Admin ->> ApprovalService: 审批决定
    ApprovalService ->> RBAC: 添加临时权限
    Note over RBAC: 有效期2小时
```

#### 访问控制：

- JWT令牌有效期：30分钟
- RBAC权限验证

#### SQL安全：

Pseudo Code:

```text 
BLACKLIST = ["DROP", "DELETE", "TRUNCATE", "ALTER", "GRANT"]
WHITELIST = ["SELECT", "WITH", "SHOW"]


def validate_sql(sql: str):
    if any(cmd in sql.upper() for cmd in BLACKLIST):
        raise SecurityException("危险操作被拒绝")
```

> SQL注入防护不足，后期增加AST解析校验

#### 审计日志：

- 添加操作审计表，记录关键操作(如数据源配置修改、权限变更)

```sql
CREATE TABLE audit_log (
    operator_id BIGINT,
    action VARCHAR(20),  -- CREATE/UPDATE/DELETE
    target_type VARCHAR(30),  -- DATASOURCE/AGENT
    old_value JSONB,
    new_value JSONB,
    ip_address INET
);
```

### 5.3 可靠性

基于高可用原则，单点故障不影响服务正常提供

#### 关键操作事务处理：

Pseudo Code：

```text
with db.transaction():
    create_message()
    update_conversation()
    log_activity()
```

#### 错误处理机制：

- **SQL执行失败重试** 指数退避算法,重试3次

- **Agent故障转移**

### 5.4 可扩展

负载过高时，支持节点横向扩展，服务能力随着节点数量增加而增强

### 6. 附录

#### 6.1 术语表

| 术语        | 定义               |
|-----------|------------------|
| DataAgent | 数据智能代理，核心处理引擎    |
| TEXT2SQL  | 自然语言转SQL的Agent类型 |
| DuckDB    | 嵌入式分析数据库引擎       |
| RBAC      | 基于角色的访问控制        |

#### 6.2 参考资料

- OpenAPI 3.0规范文档
- FastAPI官方文档
- Langchain框架文档

#### 6.3 版本历史

| 版本  | 日期         | 作者     | 备注   |
|-----|------------|--------|------|
| 1.0 | 2025-07-04 | Kiwi团队 | 初始版本 |
