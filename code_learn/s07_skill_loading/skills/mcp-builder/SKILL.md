---
name: mcp-builder
description: 构建为Claude提供新能力的MCP（Model Context Protocol）服务器。在用户想要创建MCP服务器、向Claude添加工具或集成外部服务时使用。
---

# MCP服务器构建技能（MCP Server Building Skill）

你现在具备构建MCP（Model Context Protocol）服务器的专业能力。MCP使Claude能够通过标准化协议与外部服务交互。

## 什么是MCP？

MCP服务器暴露：
- **工具（Tools）**：Claude可以调用的函数（类似API端点）
- **资源（Resources）**：Claude可以读取的数据（类似文件或数据库记录）
- **提示（Prompts）**：预构建的提示模板

## 快速开始：Python MCP服务器

### 1. 项目设置（Project Setup）

```bash
# Create project
mkdir my-mcp-server && cd my-mcp-server
python3 -m venv venv && source venv/bin/activate

# Install MCP SDK
pip install mcp
```

### 2. 基础服务器模板（Basic Server Template）

```python
#!/usr/bin/env python3
"""my_server.py - A simple MCP server"""

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Create server instance
server = Server("my-server")

# Define a tool
@server.tool()
async def hello(name: str) -> str:
    """Say hello to someone.

    Args:
        name: The name to greet
    """
    return f"Hello, {name}!"

@server.tool()
async def add_numbers(a: int, b: int) -> str:
    """Add two numbers together.

    Args:
        a: First number
        b: Second number
    """
    return str(a + b)

# Run server
async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

### 3. 向Claude注册（Register with Claude）

添加到 `~/.claude/mcp.json`：
```json
{
  "mcpServers": {
    "my-server": {
      "command": "python3",
      "args": ["/path/to/my_server.py"]
    }
  }
}
```

## TypeScript MCP服务器

### 1. 设置（Setup）

```bash
mkdir my-mcp-server && cd my-mcp-server
npm init -y
npm install @modelcontextprotocol/sdk
```

### 2. 模板（Template）

```typescript
// src/index.ts
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

const server = new Server({
  name: "my-server",
  version: "1.0.0",
});

// Define tools
server.setRequestHandler("tools/list", async () => ({
  tools: [
    {
      name: "hello",
      description: "Say hello to someone",
      inputSchema: {
        type: "object",
        properties: {
          name: { type: "string", description: "Name to greet" },
        },
        required: ["name"],
      },
    },
  ],
}));

server.setRequestHandler("tools/call", async (request) => {
  if (request.params.name === "hello") {
    const name = request.params.arguments.name;
    return { content: [{ type: "text", text: `Hello, ${name}!` }] };
  }
  throw new Error("Unknown tool");
});

// Start server
const transport = new StdioServerTransport();
server.connect(transport);
```

## 高级模式（Advanced Patterns）

### 外部API集成（External API Integration）

```python
import httpx
from mcp.server import Server

server = Server("weather-server")

@server.tool()
async def get_weather(city: str) -> str:
    """Get current weather for a city."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.weatherapi.com/v1/current.json",
            params={"key": "YOUR_API_KEY", "q": city}
        )
        data = resp.json()
        return f"{city}: {data['current']['temp_c']}C, {data['current']['condition']['text']}"
```

### 数据库访问（Database Access）

```python
import sqlite3
from mcp.server import Server

server = Server("db-server")

@server.tool()
async def query_db(sql: str) -> str:
    """Execute a read-only SQL query."""
    if not sql.strip().upper().startswith("SELECT"):
        return "Error: Only SELECT queries allowed"

    conn = sqlite3.connect("data.db")
    cursor = conn.execute(sql)
    rows = cursor.fetchall()
    conn.close()
    return str(rows)
```

### 资源（Resources，只读数据）

```python
@server.resource("config://settings")
async def get_settings() -> str:
    """Application settings."""
    return open("settings.json").read()

@server.resource("file://{path}")
async def read_file(path: str) -> str:
    """Read a file from the workspace."""
    return open(path).read()
```

## 测试（Testing）

```bash
# Test with MCP Inspector
npx @anthropics/mcp-inspector python3 my_server.py

# Or send test messages directly
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python3 my_server.py
```

## 最佳实践（Best Practices）

1. **清晰的工具描述（Clear tool descriptions）**：Claude使用这些描述来决定何时调用工具
2. **输入验证（Input validation）**：始终验证并净化输入
3. **错误处理（Error handling）**：返回有意义的错误消息
4. **默认异步（Async by default）**：对I/O操作使用async/await
5. **安全性（Security）**：未经身份验证绝不要暴露敏感操作
6. **幂等性（Idempotency）**：工具应可安全重试
