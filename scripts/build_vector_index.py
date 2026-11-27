# 切块 → 连 Milvus 建集合（失败立刻炸）→ 才开始算向量
# 算完立刻存盘：向量写进 data/embeddings_cache.pkl，附带内容指纹。
# 下次重跑，只要 Mongo 内容没变（指纹一致），直接读缓存跳过编码，三小时变几秒。
# 以后调切块、换库、入库失败，都不用再算第二遍
# 这是个"幂等、可缓存、基础设施前置校验"的向量入库脚本
import hashlib
import pickle
from pathlib import Path
# Milvus 向量数据库的 Python SDK。MilvusClient：新版统一客户端，支持 Milvus Lite（本地文件模式）。
from pymilvus import DataType, MilvusClient
# 加载本地/远程嵌入模型，把文本编码成向量。
from sentence_transformers import SentenceTransformer

from core.config import settings
from core.db.mongo import connection

COLLECTION = "embedded_repository_files" # Milvus 集合名（相当于表名）
CHUNK_SIZE = 400 # 每个文本块目标最大长度（按字符计）
CHUNK_OVERLAP = 50 # 超长段落切分时，相邻块的重叠字符数，避免语义被切断。
MIN_CHUNK_LEN = 30 # 小于 30 字符的碎片块直接丢弃，（噪点）。
CACHE_PATH = Path(settings.MILVUS_LITE_PATH).parent / "embeddings_cache.pkl"

# 切块函数
def chunk_text(text: str) -> list[str]:
  # 去掉 \x00（NUL 空字符，数据库/编码里常见垃圾），并去掉首尾空白。
    text = text.replace("\x00", "").strip()
    # 用空行（\n\n）切分段落，每段去首尾空白，丢弃空段。
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks = [] # 收集最终块
    buf = "" # 用来把多个小段落合并成一个接近 CHUNK_SIZE 的块
    for p in paragraphs:
        while len(p) > CHUNK_SIZE:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(p[:CHUNK_SIZE])
            p = p[CHUNK_SIZE - CHUNK_OVERLAP:] # 剩余部分从"CHUNK_SIZE - OVERLAP"处开始，形成 50 字符重叠，保证跨块语义连续。
        if len(buf) + len(p) + 2 <= CHUNK_SIZE:
            buf = f"{buf}\n\n{p}" if buf else p
        else:
            if buf:
                chunks.append(buf)
            buf = p
    if buf:
        chunks.append(buf)

    return [c for c in chunks if len(c) >= MIN_CHUNK_LEN]

def main() -> None:
    db = connection.get_database(settings.MONGO_DATABASE_NAME)
    docs = list(db["repository_files"].find({}))
    print(f"Mongo 文档数: {len(docs)}")
# 切块组装 rows
    rows = []
    for doc in docs:
        for chunk in chunk_text(doc.get("content", "")):
            rows.append(
                {
                    "content": chunk,
                    "repo_name": doc.get("repo_name", ""),
                    "file_path": doc.get("file_path", ""),
                    "owner_id": str(doc.get("owner_id", "")),
                }
            )
    print(f"切块后样本数: {len(rows)}")
    if not rows:
        raise SystemExit("没有可向量化的内容")
# 把所有块内容排序后用换行拼接，再 .encode() 成字节，算 MD5，取十六进制字符串。
    fingerprint = hashlib.md5("\n".join(sorted(r["content"] for r in rows)).encode()).hexdigest()
    
    # 先验基础设施：连不上向量库/建不了集合，就报错
    client = MilvusClient(settings.MILVUS_LITE_PATH)
    if client.has_collection(COLLECTION):
        client.drop_collection(COLLECTION)

    schema = client.create_schema(auto_id=True)
    schema.add_field("id", DataType.INT64, is_primary=True)
    schema.add_field("vector", DataType.FLOAT_VECTOR, dim=settings.EMBEDDING_SIZE) #  vector 负责"按意思找"
    schema.add_field("content", DataType.VARCHAR, max_length=65535)
    schema.add_field("repo_name", DataType.VARCHAR, max_length=256)  # 溯源——这话出自哪个仓库哪个文件
    schema.add_field("file_path", DataType.VARCHAR, max_length=1024)
    schema.add_field("owner_id", DataType.VARCHAR, max_length=64)  # 将来如果多用户时，按人过滤（"只搜我的笔记"）
# 对 vector 建索引：度量用余弦相似度，索引类型 FLAT（暴力精确检索，适合小数据，无近似误差）。
    index_params = client.prepare_index_params()
    index_params.add_index(field_name="vector", metric_type="COSINE", index_type="FLAT")
    client.create_collection(COLLECTION, schema=schema, index_params=index_params)
    print("Milvus 集合就绪")
# 加载嵌入模型
    model = SentenceTransformer(settings.EMBEDDING_MODEL_ID, device=settings.EMBEDDING_MODEL_DEVICE)
# embeddings_cache.pkl缓存文件存在则二进制读取并反序列化到 cached（结构应为 {"fingerprint":..., "rows":[...]}）。
    cached = None
    if CACHE_PATH.exists():
        with open(CACHE_PATH, "rb") as f:
            cached = pickle.load(f)
# 从embeddings_cache.pkl缓存 rows 重新算指纹（不信任缓存里存的 fingerprint 字段，重新计算校验，更稳健）。
    cached_fingerprint = None
    if cached:
        cached_fingerprint = hashlib.md5(
            "\n".join(sorted(r["content"] for r in cached["rows"])).encode()
        ).hexdigest()
# embeddings_cache.pkl缓存内容指纹 == 当前 Mongo 内容指纹 → 内容没变。
    if cached_fingerprint == fingerprint:
        rows = cached["rows"]
        print(f"命中向量缓存，跳过编码: {CACHE_PATH}")
    else: # 缓存未命中或内容变了，需要重新编码。
        vectors = model.encode(
            [r["content"] for r in rows],
            batch_size=32,
            normalize_embeddings=True, # 归一化向量（模长=1），配合 COSINE 度量。
            show_progress_bar=True,
        ) 
        for row, vec in zip(rows, vectors):
            row["vector"] = vec.tolist()
        with open(CACHE_PATH, "wb") as f:
            pickle.dump({"fingerprint": fingerprint, "rows": rows}, f)
        print(f"向量已落盘缓存: {CACHE_PATH}")
# 批量入库
    for i in range(0, len(rows), 1000):
        client.insert(COLLECTION, rows[i : i + 1000])
    print(f"入库完成: {len(rows)} 条向量 -> {settings.MILVUS_LITE_PATH}")
# 试搜验证
    query = "怎么防止爬虫抓回垃圾数据"
    query_vec = model.encode(query, normalize_embeddings=True).tolist()
    hits = client.search(
        COLLECTION, data=[query_vec], limit=3, output_fields=["repo_name", "file_path", "content"]
    )
    print(f"\n试搜: {query}")
    for hit in hits[0]:
        entity = hit["entity"]
        snippet = entity["content"][:80].replace("\n", " ")
        print(f"  相似度 {hit['distance']:.3f} | {entity['repo_name']}/{entity['file_path']} | {snippet}")


if __name__ == "__main__":
    main()