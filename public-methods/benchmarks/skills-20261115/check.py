#!/usr/bin/env python3
"""Frozen task-level correctness groups. Run only inside isolated Docker."""
import argparse,csv,json,math,re,subprocess,sys
from pathlib import Path
from html.parser import HTMLParser
class Plain(HTMLParser):
    def __init__(self):super().__init__();self.parts=[]
    def handle_data(self,data):self.parts.append(data)
def plain(path):
    p=Plain();p.feed(path.read_text());return " ".join(p.parts)
def check(args):
    o=Path(args.output);inp=Path(args.input); groups={}
    def group(name,checks):
        errors=[]
        for ok,msg in checks:
            if not ok:errors.append(msg)
        groups[name]={"ok":not errors,"errors":errors}
    group("delivery_and_selftest_record",[(o.joinpath("QA.md").is_file(),"QA.md absent"),(o.joinpath("README.md").is_file(),"README.md absent")])
    if args.task=="design":
        proc=subprocess.run(["node",str(Path(__file__).with_name("check_design.js")),str(o),str(inp)],capture_output=True,text=True,timeout=50)
        try: result=json.loads(proc.stdout.strip().splitlines()[-1])
        except Exception: result={"ok":False,"errors":[proc.stdout[-1000:],proc.stderr[-1000:]]}
        groups["directory_function_and_readability"]=result
    elif args.task=="documents":
        from pypdf import PdfReader
        pdf=o/"handover.pdf";r=PdfReader(pdf);texts=[p.extract_text() or "" for p in r.pages];t=re.sub(r"\s+"," "," ".join(texts)).lower()
        group("actual_two_page_a4_pdf",[(len(r.pages)==2,"Exactly two pages required"),(all(abs(float(p.mediabox.width)-595.276)<3 and abs(float(p.mediabox.height)-841.89)<3 for p in r.pages),"A4 required"),(all(len(x)>180 for x in texts),"Each page needs selectable useful text"),(any(p.name not in {"QA.md","README.md","handover.pdf"} and p.suffix in {".py",".html",".md",".tex"} for p in o.iterdir()),"Editable source/generator absent")])
        checks=[]
        for token in ["2026-07-18","10:00","82","visit","09:00","18:00","east","step-free","pending","ramp","11:00","water","unknown","unique"]:
            checks.append((token in t,"Missing required factual token: "+token))
        checks.append((bool(re.search(r"(not approved|unapproved|approval.{0,30}pending|pending.{0,30}approval)",t)),"Approval uncertainty absent"))
        group("latest_source_facts_and_uncertainty",checks)
        group("action_handover",[(all(x in t for x in ["mira chen","12:00","owen reed","13:00","leila noor","11:00","sam ortiz","10:30"]),"Four owners/deadlines incomplete"),("escalat" in t,"Escalation condition absent"),(bool(re.search(r"(source|record|notes)",t)),"Evidence source note absent")])
        proc=subprocess.run(["pdftotext","-bbox",str(pdf),"-"],capture_output=True,text=True,check=True)
        words=re.findall(r'<word xMin="([^"]+)" yMin="([^"]+)" xMax="([^"]+)" yMax="([^"]+)">',proc.stdout)
        outside=[v for v in words if float(v[0])<0 or float(v[1])<0 or float(v[2])>596.3 or float(v[3])>842.9]
        group("text_bounds",[(bool(words),"No selectable words"),(not outside,"Text outside A4 boundaries")])
    else:
        expected={("assisted","East"):(14,10,4,8,.8),("assisted","West"):(56,50,6,30,.6),("standard","East"):(51,50,1,36,.72),("standard","West"):(19,10,9,4,.4),("assisted","ALL"):(70,60,10,38,38/60),("standard","ALL"):(70,60,10,40,40/60)}
        with (o/"summary.csv").open(newline="") as f:
            reader=csv.DictReader(f);rows=list(reader);header=reader.fieldnames
        checks=[(header==["service","branch","n_total","n_known","n_missing","n_success","success_rate"],"Wrong CSV columns"),(len(rows)==6,"Exactly six summary rows required")]
        seen=set()
        for row in rows:
            key=(row.get("service"),row.get("branch"));seen.add(key)
            if key not in expected:checks.append((False,"Unexpected row "+str(key)));continue
            try:
                got=tuple(float(row[c]) for c in ["n_total","n_known","n_missing","n_success","success_rate"])
                checks.append((all(abs(a-b)<1e-6 for a,b in zip(got,expected[key])),"Wrong denominator/missingness/estimate "+str(key)))
            except Exception:checks.append((False,"Non-numeric values "+str(key)))
        checks.append((seen==set(expected),"Missing or duplicate strata"))
        group("correct_csv_denominators_and_missingness",checks)
        comp=json.loads((o/"comparison.json").read_text())
        group("pooled_and_standardized_comparison",[(isinstance(comp.get("pooled_difference_pp"),(float,int)) and abs(comp["pooled_difference_pp"]+10/3)<1e-4,"Pooled difference must be -3.333333 pp"),(isinstance(comp.get("equal_branch_difference_pp"),(float,int)) and abs(comp["equal_branch_difference_pp"]-14)<1e-4,"Equal branch difference must be +14 pp")])
        t=plain(o/"report.html").lower()
        group("actual_report_and_reproducible_source",[(o.joinpath("analysis.py").is_file(),"analysis.py absent"),(len(t)>450,"Readable substantive report absent"),(all(x in t for x in ["east","west","assisted","standard"]),"Report omits groups"),(bool(re.search(r"miss|unknown",t)),"Missingness discussion absent"),(bool(re.search(r"caus|random|observational|confound",t)),"Evidence limits absent"),(bool(re.search(r"equal|standardiz",t)),"Equal-branch explanation absent"),(not re.search(r"https?://",o.joinpath("report.html").read_text()),"External URLs are unnecessary offline dependencies")])
    return {"task":args.task,"ok":all(g.get("ok") for g in groups.values()),"groups":groups,"scope":"Artifact checks only; root independently verifies logged self-tests, normal final, source faithfulness and blind quality."}
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--task",choices=["design","documents","analysis"],required=True);p.add_argument("--input",required=True);p.add_argument("--output",required=True);args=p.parse_args()
    try:result=check(args)
    except Exception as e:result={"task":args.task,"ok":False,"error":type(e).__name__+": "+str(e)}
    print(json.dumps(result,indent=2));sys.exit(0 if result["ok"] else 1)
