"""健康问答子代理：提供通用健康科普与生活建议，不替代医生诊断。"""
import os
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from qwen_llm import llm


SYSTEM_PROMPT = (
    "你是健康问答助手。回答通用健康科普、生活方式、营养运动等常识问题。"
    "严禁给出具体诊断或处方；涉及急症、用药、个体化治疗时，"
    "必须建议用户立即就医或咨询专业医生。回答应简洁、安全、有依据。"
)

# 健康问答不需要外部工具，纯知识回答即可
agent = create_agent(
    model=llm,
    tools=[],
    system_prompt=SYSTEM_PROMPT,
)

if __name__ == "__main__":
    result = agent.invoke({
        "messages": [{"role": "user", "content": "最近总是失眠，有什么生活上的建议？"}]
    })
    print(result["messages"][-1].content)
