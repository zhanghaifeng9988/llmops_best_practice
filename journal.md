uv init --python 3.11
uv sync
# 0、安装前置条件：
去https://langfuse.com/ 这个链接，创建一个免费的Langfuse账户（或自托管实例）
——从'项目设置'中获取你的 LANGFUSE_PUBLIC_KEY 和LANGFUSE_SECRET_KEY。
--去申请了千问大模型的token api，付费申请

安装依赖，完成项目开始之前的测试工作
uv add langfuse openai anthropic python-dotenv 
然后项目根目录下执行： uv run python src/llmops_best_practice/llm_with_tracing.py
测试一下大模型API的效果 


装库 
aws_lambda_powertools
pymongo
structlog
qdrant_client 
opik 
comet_ml
langchain-community 
html2text