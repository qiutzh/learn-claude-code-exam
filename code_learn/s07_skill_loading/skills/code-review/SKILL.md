---
name: code-review
description: 执行全面的代码审查，包含安全性、性能和可维护性分析。在用户要求审查代码、检查缺陷或审计代码库时使用。
---

# 代码审查技能（Code Review Skill）

你现在具备进行全面代码审查的专业能力。遵循以下结构化方法：

## 审查清单（Review Checklist）

### 1. 安全性（Security，关键）

检查：
- [ ] **注入漏洞（Injection vulnerabilities）**：SQL、命令、XSS、模板注入
- [ ] **身份验证问题（Authentication issues）**：硬编码凭据、弱身份验证
- [ ] **授权缺陷（Authorization flaws）**：缺少访问控制、IDOR
- [ ] **数据暴露（Data exposure）**：日志、错误消息中的敏感数据
- [ ] **密码学（Cryptography）**：弱算法、不当的密钥管理
- [ ] **依赖项（Dependencies）**：已知漏洞（使用 `npm audit`、`pip-audit` 检查）

```bash
# Quick security scans
npm audit                    # Node.js
pip-audit                    # Python
cargo audit                  # Rust
grep -r "password\|secret\|api_key" --include="*.py" --include="*.js"
```

### 2. 正确性（Correctness）

检查：
- [ ] **逻辑错误（Logic errors）**：差一错误、空值处理、边界情况
- [ ] **竞态条件（Race conditions）**：无同步的并发访问
- [ ] **资源泄漏（Resource leaks）**：未关闭的文件、连接、内存
- [ ] **错误处理（Error handling）**：被吞掉的异常、缺失的错误路径
- [ ] **类型安全（Type safety）**：隐式转换、any 类型

### 3. 性能（Performance）

检查：
- [ ] **N+1 查询（N+1 queries）**：循环中的数据库调用
- [ ] **内存问题（Memory issues）**：大分配、被保留的引用
- [ ] **阻塞操作（Blocking operations）**：异步代码中的同步 I/O
- [ ] **低效算法（Inefficient algorithms）**：本可 O(n) 却为 O(n^2)
- [ ] **缺少缓存（Missing caching）**：重复的昂贵计算

### 4. 可维护性（Maintainability）

检查：
- [ ] **命名（Naming）**：清晰、一致、描述性强
- [ ] **复杂度（Complexity）**：函数 > 50 行，嵌套深度 > 3 层
- [ ] **重复（Duplication）**：复制粘贴的代码块
- [ ] **死代码（Dead code）**：未使用的导入、不可达的分支
- [ ] **注释（Comments）**：过时、冗余或在需要处缺失

### 5. 测试（Testing）

检查：
- [ ] **覆盖率（Coverage）**：关键路径已测试
- [ ] **边界情况（Edge cases）**：空值、空、边界值
- [ ] **模拟（Mocking）**：外部依赖已隔离
- [ ] **断言（Assertions）**：有意义、具体的检查

## 审查输出格式（Review Output Format）

```markdown
## Code Review: [file/component name]

### Summary
[1-2 sentence overview]

### Critical Issues
1. **[Issue]** (line X): [Description]
   - Impact: [What could go wrong]
   - Fix: [Suggested solution]

### Improvements
1. **[Suggestion]** (line X): [Description]

### Positive Notes
- [What was done well]

### Verdict
[ ] Ready to merge
[ ] Needs minor changes
[ ] Needs major revision
```

## 需标记的常见模式（Common Patterns to Flag）

### Python
```python
# Bad: SQL injection
cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
# Good:
cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))

# Bad: Command injection
os.system(f"ls {user_input}")
# Good:
subprocess.run(["ls", user_input], check=True)

# Bad: Mutable default argument
def append(item, lst=[]):  # Bug: shared mutable default
# Good:
def append(item, lst=None):
    lst = lst or []
```

### JavaScript/TypeScript
```javascript
// Bad: Prototype pollution
Object.assign(target, userInput)
// Good:
Object.assign(target, sanitize(userInput))

// Bad: eval usage
eval(userCode)
// Good: Never use eval with user input

// Bad: Callback hell
getData(x => process(x, y => save(y, z => done(z))))
// Good:
const data = await getData();
const processed = await process(data);
await save(processed);
```

## 审查命令（Review Commands）

```bash
# Show recent changes
git diff HEAD~5 --stat
git log --oneline -10

# Find potential issues
grep -rn "TODO\|FIXME\|HACK\|XXX" .
grep -rn "password\|secret\|token" . --include="*.py"

# Check complexity (Python)
pip install radon && radon cc . -a

# Check dependencies
npm outdated  # Node
pip list --outdated  # Python
```

## 审查工作流（Review Workflow）

1. **理解上下文（Understand context）**：阅读 PR 描述、关联的 issue
2. **运行代码（Run the code）**：尽可能在本地构建、测试、运行
3. **自上而下阅读（Read top-down）**：从主要入口点开始
4. **检查测试（Check tests）**：变更是否有测试？测试是否通过？
5. **安全扫描（Security scan）**：运行自动化工具
6. **人工审查（Manual review）**：使用上方清单
7. **撰写反馈（Write feedback）**：具体、建议修复方案、保持友善
