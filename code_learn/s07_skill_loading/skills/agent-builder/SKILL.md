---
name: agent-builder
description: |
  为任何领域设计和构建AI智能体。在用户出现以下情况时使用：
  （1）要求“创建智能体（create an agent）”、“构建助手（build an assistant）”或“设计AI系统（design an AI system）”
  （2）想了解智能体架构（agent architecture）、智能体模式（agentic patterns）或自主AI（autonomous AI）
  （3）需要关于能力（capabilities）、子智能体（subagents）、规划（planning）或技能机制（skill mechanisms）的帮助
  （4）询问Claude Code、Cursor或类似智能体内部机制
  （5）想为业务、研究、创意或运营任务构建智能体
  关键词：agent、assistant、autonomous、workflow、tool use、multi-step、orchestration
---

# 智能体构建器（Agent Builder）

为任何领域构建AI智能体——客户服务、研究、运营、创意工作或专业业务流程。

## 核心理念

> **模型已经知道如何成为智能体。你的工作是不要挡路。**

智能体不是复杂的工程。它只是一个邀请模型行动的简单循环：

```
LOOP:
  Model sees: context + available capabilities
  Model decides: act or respond
  If act: execute capability, add result, continue
  If respond: return to user
```

**就是这样。** 魔力不在代码中——而在模型中。你的代码只是提供机会。

## 三大要素

### 1. 能力（Capabilities，它能做什么？）

智能体可以执行的原子动作：搜索、读取、创建、发送、查询、修改。

**设计原则**：从3-5个能力开始。只有当智能体因缺少某项能力而持续失败时，才添加更多。

### 2. 知识（Knowledge，它知道什么？）

按需注入的领域专业知识：策略、工作流、最佳实践、模式。

**设计原则**：让知识可用，而非强制。在相关时加载，而非预先加载。

### 3. 上下文（Context，发生了什么？）

对话历史——将行动连接为连贯行为的线索。

**设计原则**：上下文很宝贵。隔离嘈杂的子任务。截断冗长的输出。保护清晰性。

## 智能体设计思维

在构建之前，理解：

- **目的（Purpose）**：这个智能体应该完成什么？
- **领域（Domain）**：它在什么世界中运作？（客户服务、研究、运营、创意……）
- **能力（Capabilities）**：哪3-5个动作是必不可少的？
- **知识（Knowledge）**：它需要访问什么专业知识？
- **信任（Trust）**：哪些决策可以委托给模型？

**关键**：信任模型。不要过度工程化。不要预先指定工作流。给它能力，让它推理。

## 渐进式复杂度

从简单开始。只有当真实使用揭示需要时才添加复杂度：

| 层级 | 添加什么 | 何时添加 |
|-------|-------------|----------------|
| 基础（Basic） | 3-5个能力 | 始终从这里开始 |
| 规划（Planning） | 进度跟踪 | 多步骤任务失去连贯性时 |
| 子智能体（Subagents） | 隔离的子智能体 | 探索污染上下文时 |
| 技能（Skills） | 按需知识 | 需要领域专业知识时 |

**大多数智能体永远不需要超过第2层。**

## 领域示例

**业务（Business）**：CRM查询、电子邮件、日历、审批
**研究（Research）**：数据库搜索、文档分析、引用
**运营（Operations）**：监控、工单、通知、升级
**创意（Creative）**：资产生成、编辑、协作、审查

模式是通用的。只有能力会变化。

## 关键原则

1. **模型就是智能体（The model IS the agent）**——代码只是运行循环
2. **能力赋能（Capabilities enable）**——它能做什么
3. **知识告知（Knowledge informs）**——它知道如何做什么
4. **约束聚焦（Constraints focus）**——限制创造清晰
5. **信任解放（Trust liberates）**——让模型推理
6. **迭代揭示（Iteration reveals）**——从最小开始，从使用中演进

## 反模式（Anti-Patterns）

| 模式 | 问题 | 解决方案 |
|---------|---------|----------|
| 过度工程化（Over-engineering） | 在需要之前就引入复杂度 | 从简单开始 |
| 能力过多（Too many capabilities） | 模型困惑 | 从3-5个开始 |
| 僵化工作流（Rigid workflows） | 无法适应 | 让模型决定 |
| 前置知识（Front-loaded knowledge） | 上下文膨胀 | 按需加载 |
| 微观管理（Micromanagement） | 削弱智能 | 信任模型 |

## 资源

**理念与理论**：
- `references/agent-philosophy.md`——深入探讨智能体为何有效

**实现**：
- `references/minimal-agent.py`——完整可运行的智能体（约80行）
- `references/tool-templates.py`——能力定义
- `references/subagent-pattern.py`——上下文隔离

**脚手架**：
- `scripts/init_agent.py`——生成新的智能体项目

## 智能体思维模式

**从**：“我如何让系统做X？”
**到**：“我如何让模型能够做X？”

**从**：“这项任务的工作流是什么？”
**到**：“哪些能力有助于完成这项任务？”

最好的智能体代码几乎是乏味的。简单的循环。清晰的能力。干净的上下文。魔力不在代码中。

**给模型能力和知识。信任它去弄清楚其余的一切。**
