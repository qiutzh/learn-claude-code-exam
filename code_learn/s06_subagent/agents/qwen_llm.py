import os
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

load_dotenv(override=True)

llm = ChatOpenAI(
    model=os.getenv("MODEL_ID", "gpt-4o-mini"),
    api_key=os.getenv("OPENAI_API_KEY", "dummy"),
    base_url=os.getenv("OPENAI_BASE_URL"),
    temperature=0.8,
)
