"""Deterministic normalized lexical units; original quoted bytes never rewritten."""
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from urllib.parse import urlsplit

from app.research_method_evidence import build_index, passages, STOPWORDS

UNIT_POLICY = "normalized-units-v1"


def search_terms(text):
    """Keep identifiers and components, preserving ordinary word frequencies."""
    result=[]
    for token in re.findall(r"\w+",text,re.UNICODE):
        separated=re.sub(r"([A-Z]+)([A-Z][a-z])",r"\1 \2",token)
        separated=re.sub(r"([a-z0-9])([A-Z])",r"\1 \2",separated)
        parts=re.findall(r"[^\W_]+",separated.lower(),re.UNICODE)
        words=list(dict.fromkeys([token.lower()]+parts))
        result.extend(word for word in words if word not in STOPWORDS)
    return result


def product_anchor(metadata):
    """Use the version's first product token only when corroborated by its URL."""
    match = re.match(r"\s*@?([A-Za-z][A-Za-z0-9_-]*)",metadata["version"])
    if not match:return None
    name=match.group(1).lower()
    url=urlsplit(metadata["source_url"])
    urlwords=re.findall(r"[a-z0-9]+",url.hostname.lower()+url.path.lower())
    if name not in urlwords:return None
    version=re.search(r"(?<!\d)(\d+\.\d+(?:\.\d+)?)(?!\d)",metadata["version"])
    return name,version.group(1) if version else None


def anchored_sources(sources,query):
    words=set(re.findall(r"[a-z0-9_-]+",query.lower()))
    annotated=[(ident,metadata,product_anchor(metadata)) for ident,metadata in sources]
    matched={anchor[0] for _,_,anchor in annotated if anchor and anchor[0] in words}
    info={"status":"unanchored","product":None,"version":None,
          "basis":"explicit_query_token_and_approved_version_prefix_corroborated_by_source_url"}
    if len(matched)!=1:
        if matched:info["status"]="multiple_explicit_products"
        return None,info
    name=next(iter(matched));pool=[(ident,anchor) for ident,_,anchor in annotated if anchor and anchor[0]==name]
    versions=re.findall(r"(?<!\d)(\d+\.\d+(?:\.\d+)?)(?!\d)",query)
    def compatible(left,right):return left==right or left.startswith(right+".") or right.startswith(left+".")
    matched_versions=[version for version in versions if any(anchor[1] and compatible(version,anchor[1]) for _,anchor in pool)]
    info.update(status="product",product=name)
    if len(set(matched_versions))==1:
        version=matched_versions[0];info.update(status="product_and_version",version=version)
        pool=[(ident,anchor) for ident,anchor in pool if not anchor[1] or compatible(version,anchor[1])]
    elif versions and not matched_versions:info["status"]="product_requested_version_not_pinned"
    return [ident for ident,_ in pool],info


def markdown_sections(body):
    fences=markdown_fences(body)
    headings=[match for match in re.finditer(r"(?m)^ {0,3}#{1,6}\s+[^\r\n]+",body)
              if not any(left<=match.start()<right for left,right,_,_ in fences)]
    return [(m.start(),headings[i+1].start() if i+1<len(headings) else len(body),m.group().strip())
            for i,m in enumerate(headings)]


def markdown_fences(body):
    result=[];opened=None
    for match in re.finditer(r"(?m)^ {0,3}(`{3,}|~{3,})[^\r\n]*(?:\r?\n|$)",body):
        delimiter=match.group(1)
        if opened is None:opened=(match.start(),match.end(),delimiter)
        elif delimiter[0]==opened[2][0] and len(delimiter)>=len(opened[2]):
            result.append((opened[0],match.end(),opened[1],match.start()))
            opened=None
    return result


def is_markdown(metadata,body):
    suffix=Path(urlsplit(metadata["source_url"]).path).suffix.lower()
    if suffix in {".py",".ts",".tsx",".js",".jsx",".java",".c",".cpp",".h",".rs",".go"}:
        return False
    return suffix in {".md",".mdx",".rst"} or bool(markdown_sections(body))


def structural_frames(metadata,body):
    # Never infer code function boundaries from Markdown prose/link syntax.
    from app.research_evidence_refs import function_frames
    if is_markdown(metadata,body):
        return [(left,right) for left,right,_,_ in markdown_fences(body)]
    frames=function_frames(body)
    expanded=[]
    for start,end in frames:
        prefix=body[:start];close=prefix.rfind("*/")
        if close>=0 and not prefix[close+2:].strip() and prefix[close+2:].count("\n")<=2:
            opening=prefix.rfind("/*",0,close)
            if opening>=0:start=opening
        expanded.append((start,end))
    return expanded


def safe_span(start,end,frames):
    changed=True
    while changed:
        changed=False
        for left,right in frames:
            if left<end and right>start and (left<start or right>end):
                start,end=min(start,left),max(end,right);changed=True
    return start,end


def source_units(metadata,body):
    frames=structural_frames(metadata,body);sections=markdown_sections(body) if is_markdown(metadata,body) else []
    seen=set()
    for start,end,text in passages(body):
        left,right=safe_span(start,end,frames)
        if (left,right) in seen:continue
        seen.add((left,right))
        heading=next((title for a,b,title in sections if a<=left<b),"")
        yield left,right,"frame" if (left,right)!=(start,end) else "paragraph",heading,body[left:right]


def build_reference_index(manifest_path,output):
    """Keep legacy FTS intact; atomically add an independent normalized unit FTS."""
    output=Path(output).resolve()
    if output.is_relative_to(Path(__file__).resolve().parents[2]):
        raise ValueError("evidence indexes must live outside the repository")
    output.parent.mkdir(parents=True,exist_ok=True)
    descriptor,temp=tempfile.mkstemp(prefix=".ref-units-",dir=output.parent);os.close(descriptor)
    try:
        result=build_index(manifest_path,temp)
        with sqlite3.connect(temp) as db:
            db.executescript("""
                CREATE TABLE reference_search_metadata(policy TEXT NOT NULL);
                CREATE VIRTUAL TABLE reference_units USING fts5(
                    text, heading, source_id UNINDEXED, start UNINDEXED, end UNINDEXED,
                    kind UNINDEXED, tokenize='porter unicode61');
            """)
            db.execute("INSERT INTO reference_search_metadata VALUES (?)",(UNIT_POLICY,))
            count=0
            for ident,raw,body in db.execute("SELECT id,metadata,body FROM sources ORDER BY id").fetchall():
                for start,end,kind,heading,text in source_units(json.loads(raw),body):
                    db.execute("INSERT INTO reference_units(text,heading,source_id,start,end,kind) VALUES (?,?,?,?,?,?)",
                               (" ".join(search_terms(text))," ".join(search_terms(heading)),ident,start,end,kind))
                    count+=1
        os.replace(temp,output)
        return {**result,"reference_search_policy":UNIT_POLICY,"units":count}
    finally:
        if os.path.exists(temp):os.unlink(temp)
