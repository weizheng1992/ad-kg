"""抽取 prompt 组装（独立成文件：改 prompt 不动抽取逻辑，回归用同一标注集）。"""

def build_prompt(schema: dict, chunk_text: str) -> tuple[str, str]:
    classes = sorted(schema["classes"])
    predicates = sorted(r["predicate"] for r in schema["relations"])
    system = (
        "你是知识图谱抽取器。只输出 JSON："
        '{"entities":[{"class","id","props"}],'
        '"relations":[{"source","predicate","target","confidence"]}。'
        f"class 只能取 {classes}；predicate 只能取 {predicates}；"
        "id 必须是 {class}:{slug} 格式；confidence ∈ [0,1]。不确定就不要编。"
    )
    return system, chunk_text
