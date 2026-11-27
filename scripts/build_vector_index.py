# 切块 → 连 Milvus 建集合（失败立刻炸）→ 才开始算向量
# 算完立刻存盘：向量写进 data/embeddings_cache.pkl，附带内容指纹。
# 下次重跑，只要 Mongo 内容没变（指纹一致），直接读缓存跳过编码，三小时变几秒。
# 以后调切块、换库、入库失败，都不用再算第二遍
import hashlib
import pickle
from pathlib import Path

from pymilvus import DataType, MilvusClient
from sentence_transformers import SentenceTransformer

from core.config import settings
from core.db.mongo import connection

COLLECTION = "embedded_repository_files"
CHUNK_SIZE = 400
CHUNK_OVERLAP = 50
MIN_CHUNK_LEN = 30
CACHE_PATH = Path(settings.MILVUS_LITE_PATH).parent / "embeddings_cache.pkl"

CACHE_PATH = Path(settings.MILVUS_LITE_PATH).parent / "embeddings_cache.pkl"


def chunk_text(text: str) -> list[str]:
    text = text.replace("\x00", "").strip()
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks = []
    buf = ""
    for p in paragraphs:
        while len(p) > CHUNK_SIZE:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(p[:CHUNK_SIZE])
            p = p[CHUNK_SIZE - CHUNK_OVERLAP:]
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

    fingerprint = hashlib.md5("\n".join(sorted(r["content"] for r in rows)).encode()).hexdigest()
    
    # 先验基础设施：连不上/建不了集合，一秒就炸，绝不白算三小时
    client = MilvusClient(settings.MILVUS_LITE_PATH)
    if client.has_collection(COLLECTION):
        client.drop_collection(COLLECTION)

    schema = client.create_schema(auto_id=True)
    schema.add_field("id", DataType.INT64, is_primary=True)
    schema.add_field("vector", DataType.FLOAT_VECTOR, dim=settings.EMBEDDING_SIZE)
    schema.add_field("content", DataType.VARCHAR, max_length=65535)
    schema.add_field("repo_name", DataType.VARCHAR, max_length=256)
    schema.add_field("file_path", DataType.VARCHAR, max_length=1024)
    schema.add_field("owner_id", DataType.VARCHAR, max_length=64)

    index_params = client.prepare_index_params()
    index_params.add_index(field_name="vector", metric_type="COSINE", index_type="FLAT")
    client.create_collection(COLLECTION, schema=schema, index_params=index_params)
    print("Milvus 集合就绪")

    model = SentenceTransformer(settings.EMBEDDING_MODEL_ID, device=settings.EMBEDDING_MODEL_DEVICE)

    cached = None
    if CACHE_PATH.exists():
        with open(CACHE_PATH, "rb") as f:
            cached = pickle.load(f)

    cached_fingerprint = None
    if cached:
        cached_fingerprint = hashlib.md5(
            "\n".join(sorted(r["content"] for r in cached["rows"])).encode()
        ).hexdigest()

    if cached_fingerprint == fingerprint:
        rows = cached["rows"]
        print(f"命中向量缓存，跳过编码: {CACHE_PATH}")
    else:
        vectors = model.encode(
            [r["content"] for r in rows],
            batch_size=32,
            normalize_embeddings=True,
            show_progress_bar=True,
        )
        for row, vec in zip(rows, vectors):
            row["vector"] = vec.tolist()
        with open(CACHE_PATH, "wb") as f:
            pickle.dump({"fingerprint": fingerprint, "rows": rows}, f)
        print(f"向量已落盘缓存: {CACHE_PATH}")

    for i in range(0, len(rows), 1000):
        client.insert(COLLECTION, rows[i : i + 1000])
    print(f"入库完成: {len(rows)} 条向量 -> {settings.MILVUS_LITE_PATH}")

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