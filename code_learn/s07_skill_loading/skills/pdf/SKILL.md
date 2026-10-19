---
name: pdf
description: 处理PDF文件——提取文本、创建PDF、合并文档。在用户要求读取PDF、创建PDF或处理PDF文件时使用。
---

# PDF处理技能（PDF Processing Skill）

你现在具备PDF操作的专业能力。遵循以下工作流：

## 读取PDF（Reading PDFs）

**选项1：快速文本提取（首选）**
```bash
# Using pdftotext (poppler-utils)
pdftotext input.pdf -  # Output to stdout
pdftotext input.pdf output.txt  # Output to file

# If pdftotext not available, try:
python3 -c "
import fitz  # PyMuPDF
doc = fitz.open('input.pdf')
for page in doc:
    print(page.get_text())
"
```

**选项2：逐页读取并附带元数据**
```python
import fitz  # pip install pymupdf

doc = fitz.open("input.pdf")
print(f"Pages: {len(doc)}")
print(f"Metadata: {doc.metadata}")

for i, page in enumerate(doc):
    text = page.get_text()
    print(f"--- Page {i+1} ---")
    print(text)
```

## 创建PDF（Creating PDFs）

**选项1：从Markdown创建（推荐）**
```bash
# Using pandoc
pandoc input.md -o output.pdf

# With custom styling
pandoc input.md -o output.pdf --pdf-engine=xelatex -V geometry:margin=1in
```

**选项2：以编程方式创建**
```python
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

c = canvas.Canvas("output.pdf", pagesize=letter)
c.drawString(100, 750, "Hello, PDF!")
c.save()
```

**选项3：从HTML创建**
```bash
# Using wkhtmltopdf
wkhtmltopdf input.html output.pdf

# Or with Python
python3 -c "
import pdfkit
pdfkit.from_file('input.html', 'output.pdf')
"
```

## 合并PDF（Merging PDFs）

```python
import fitz

result = fitz.open()
for pdf_path in ["file1.pdf", "file2.pdf", "file3.pdf"]:
    doc = fitz.open(pdf_path)
    result.insert_pdf(doc)
result.save("merged.pdf")
```

## 拆分PDF（Splitting PDFs）

```python
import fitz

doc = fitz.open("input.pdf")
for i in range(len(doc)):
    single = fitz.open()
    single.insert_pdf(doc, from_page=i, to_page=i)
    single.save(f"page_{i+1}.pdf")
```

## 关键库（Key Libraries）

| 任务 | 库 | 安装 |
|------|---------|---------|
| 读取/写入/合并 | PyMuPDF | `pip install pymupdf` |
| 从零创建 | ReportLab | `pip install reportlab` |
| HTML转PDF | pdfkit | `pip install pdfkit` + wkhtmltopdf |
| 文本提取 | pdftotext | `brew install poppler` / `apt install poppler-utils` |

## 最佳实践（Best Practices）

1. **使用工具前始终检查是否已安装**
2. **处理编码问题**——PDF可能包含各种字符编码
3. **大型PDF**：逐页处理以避免内存问题
4. **扫描版PDF的OCR**：如果文本提取返回为空，使用 `pytesseract`
