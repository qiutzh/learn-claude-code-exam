"""医药健康产品咨询子代理：处理健康器械、保健品、防护用品等产品咨询。"""
import os
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from qwen_llm import llm


def search_health_product(query: str) -> str:
    """根据关键词搜索医药健康产品信息（Demo 模拟数据库）。"""
    catalog = {
        "血压计": "Omron HEM-7124 上臂式电子血压计，售价 299 元，"
                  "支持心律不齐提示，2 年质保，现货。",
        "维生素": "NatureCare 复合维生素 B 族，60 片装，售价 89 元，"
                  "适合日常营养补充，非处方，现货。",
        "口罩": "MedGuard N95 医用防护口罩，20 只装，售价 59 元，"
                "符合 GB19083 标准，现货。",
        "血糖仪": "AccuCheck Guide 血糖仪套装，售价 399 元，"
                  "含 50 条试纸，需配合试纸使用，现货。",
        "布洛芬": "布洛芬缓释胶囊属非处方药（OTC），售价 25 元/盒，"
                  "请按说明书使用；如症状持续请就医，现货。",
    }
    for key, info in catalog.items():
        if key in query:
            return info
    return ("未找到匹配的医药健康产品，请提供更具体的产品名称或关键词"
            "（如血压计、维生素、口罩、血糖仪）。")


SYSTEM_PROMPT = (
    "你是医药健康领域的产品咨询专家。使用 search_health_product 查询产品"
    "信息，只回答健康器械、保健品、防护用品、OTC 药品等产品相关问题。\n"
    "合规边界：\n"
    "1. 不提供个体化用药建议、剂量调整或诊断结论；\n"
    "2. 处方药必须提示凭处方购买，OTC 药品提示按说明书使用；\n"
    "3. 涉及症状、疾病治疗的问题，引导用户咨询医生或药师；\n"
    "4. 非医药健康产品的问题，礼貌说明并引导用户询问相关产品。"
)

agent = create_agent(
    model=llm,
    tools=[search_health_product],
    system_prompt=SYSTEM_PROMPT,
)

if __name__ == "__main__":
    result = agent.invoke({
        "messages": [{"role": "user", "content": "你们的血压计多少钱？"}]
    })
    print(result["messages"][-1].content)
