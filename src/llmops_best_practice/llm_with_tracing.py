import time
from dotenv import load_dotenv
import anthropic
from langfuse import Langfuse

#正式开始前的1个独立的脚本，偶然发现的
# 运行该代码前，配置依赖：uv add langfuse openai anthropic python-dotenv
# 并且需要注册Langfuse账号，获取公钥和私钥。注册地址：https://langfuse.com/。
#该代码的作用：
#每个调用在 Langfuse 中创建一个两层结构：一个表示完整用户交互的轨迹，以及其内部的生成跨度，代表特定的模型调用。
#这种分离很重要，因为复杂应用最终会在每个用户交互中包含多个模型调用——跟踪将它们分组，而单个生成则涵盖每次通话成本和令牌计数。
#generation.end（） 调用以 Langfuse 期望自动填充成本仪表盘的格式发布令牌使用情况。
#finald块中的langfuse_client.flush（）是脚本必不可少的——没有它，缓冲事件在Python退出前永远不会离开进程。
#运行完后，打开你的Langfuse仪表盘。你会看到两个通话都记录了完整的输入、输出、令牌数量和每次通话成本。每次通话的费用数值就是你后续所有操作的基线。

load_dotenv()
# 初始化 Langfuse 客户端。它会自动去环境变量里找你的公钥、私钥和服务器地址，准备把数据发到 Langfuse 后台。
langfuse_client = Langfuse()
anthropic_client = anthropic.Anthropic()

# 定义系统提示词。这是给 AI 设定的“人设”
SYSTEM_PROMPT = """你是一位乐于助人的客服助手。  
请清晰、简洁地回答问题。  
如果不知道某事，请直接说明，不要猜测。"""

# 【修改点 1】模型名字！千问的接口，填千问支持的，
MODEL = "qwen3.8-flash" 

# 目前API ,是千问包月Token Plan，不按单次扣费，所以这里设成 0，防止 Langfuse 后台计算出虚假的巨额花费。
#COST_PER_INPUT_TOKEN  = 3.00 / 1_000_000
#COST_PER_OUTPUT_TOKEN = 15.00 / 1_000_000
COST_PER_INPUT_TOKEN  = 0
COST_PER_OUTPUT_TOKEN = 0

# 三个参数：用户的提问（user_message）、会话 ID（session_id，默认叫 default-session）和用户 ID（user_id，默认叫 anonymous）。
# 函数最终会返回一段字符串（AI 的回答）。
def call_llm_with_tracing(
    user_message: str,
    session_id: str = "default-session",
    user_id: str = "anonymous"
) -> str:

    # 开启一个 Langfuse 的 Observation（根节点）
    with langfuse_client.start_as_current_observation(
        as_type="span",
        name="customer-support-call",
        input={"user_message": user_message, "system_prompt": SYSTEM_PROMPT}
    ) as span:
        
        # 【修复】v5 中 LangfuseSpan 没有 update_trace()。这里改用 span.update() 来写入 metadata
        # session_id 和 user_id 在 v5 中由 SDK 自动在上下文传递，不需要手动绑定
        span.update(
            metadata={
                "session_id": session_id,
                "user_id": user_id
            }
        )

        # 嵌套一个 Observation 作为 Generation（生成节点）
        with span.start_as_current_observation(
            as_type="generation",
            name="qwen-completion",
            model=MODEL,
            input={
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_message}]
            }
        ) as generation:
            start_time = time.time() #用来计算请求花了多少毫秒
            try:
                response = anthropic_client.messages.create(
                    model=MODEL,
                    max_tokens=1024,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_message}]
                )
                latency_ms = int((time.time() - start_time) * 1000) # 请求的延迟
                #把纯文本的回答抠出来
                response_text = next(
                    (block.text for block in response.content if getattr(block, "type", None) == "text"), 
                    ""
                )
                input_tokens  = response.usage.input_tokens
                output_tokens = response.usage.output_tokens
                total_tokens  = input_tokens + output_tokens
# 总的token花费
                cost_usd = (
                    input_tokens  * COST_PER_INPUT_TOKEN +
                    output_tokens * COST_PER_OUTPUT_TOKEN
                )

                # 把刚才拿到的结果，更新到 Generation 节点上
                generation.update(
                    output=response_text,
                    usage_details={
                        "input": input_tokens,
                        "output": output_tokens,
                        "total": total_tokens,
                    },
                    metadata={
                        "latency_ms": latency_ms,
                        "cost_usd":   round(cost_usd, 6),
                        "model":      MODEL
                    }
                )

                # 【修复】同样改用 span.update() 把 AI 的回答作为 output 更新到根 Span 上
                # 这样你在后台看最外层节点时，直接就能看到回答是什么。
                span.update(
                    output={"response": response_text},
                    metadata={"total_cost_usd": round(cost_usd, 6)}
                )

                print(f"\n{'─' * 60}")
                print(f"User:    {user_message}")
                print(f"Claude:  {response_text}")
                print(f"Tokens:  {input_tokens} in / {output_tokens} out / {total_tokens} total")
                print(f"Cost:    ${cost_usd:.6f}")
                print(f"Latency: {latency_ms}ms")
                # 注意：v5 获取 trace url 的用法变了，稳妥起见先注释
                # print(f"Trace:   {langfuse_client.base_url}/trace/{span.trace_id}")
                print(f"{'─' * 60}\n")

                return response_text

            except Exception as e:
                generation.update(
                    output=None,
                    metadata={"error": str(e), "latency_ms": int((time.time() - start_time) * 1000)}
                )
                # 【修复】报错时同样使用 span.update()
                span.update(output={"error": str(e)})
                raise

            finally:#强制把内存里缓存的追踪数据发送到 Langfuse 服务器。
                langfuse_client.flush()


# ── Run a demonstration ────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Simulate two turns of a customer support conversation
    test_messages = [
        "AI时代下的智能组织，是如何定义的？",
        "未来让机器人替代低级体力劳动，肯定是趋势？"
    ]

    session = "demo-session-001"

    for i, message in enumerate(test_messages):
        print(f"\nCall {i + 1}/{len(test_messages)}")
        try:
            call_llm_with_tracing(
                user_message=message,
                session_id=session,
                user_id="test-user-42"
            )
        except Exception as e:
            print(f"Error on call {i + 1}: {e}")