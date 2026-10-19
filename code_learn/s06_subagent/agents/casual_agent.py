"""通用闲聊子代理：处理问候、天气、心情、日常对话等非专业问题。"""
import os
from langchain.agents import create_agent
from qwen_llm import llm


SYSTEM_PROMPT = (
    "你是友好的闲聊伙伴。回答轻松、简短、有温度。"
    "如果用户的问题明显属于产品咨询或健康医疗，请礼貌说明并建议转接对应专家。"
)

agent = create_agent(
    model=llm,
    tools=[],
    system_prompt=SYSTEM_PROMPT,
)

if __name__ == "__main__":
    result = agent.invoke({
        "messages": [{"role": "user", "content": "今天心情不太好，陪我聊两句吧。"}]
    })
    print(result["messages"][-1].content)
