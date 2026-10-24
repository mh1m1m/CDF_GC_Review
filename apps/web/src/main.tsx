import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
import {diffTokens} from "./diff";

type Observation = { observation_id: string; original_text?: string; reviewed_text?: string;
 observed_change?: string; material_categories?: string[] };
type CaseData = { case_id: string; evidence_hash: string; source_hash: string;
 observations: Observation[]; statistics: Record<string, number | boolean> };
type EventData = { observation_id: string | null; event_type: string; payload_json: string;
 event_hash: string; created_at: string; actor: string };
type CaseSummary = { case_id: string; evidence_hash: string; stats: Record<string, number | boolean> };
const choices = [
 ["KEEP_UNCHANGED","إبقاء دون تعديل"],["KEEP_WITH_REVISIONS","إبقاء مع تعديل"],
 ["STRENGTHEN","تعزيز"],["SOFTEN","تخفيف"],["SHORTEN","اختصار"],["EXPAND","توسيع"],
 ["CONVERT_TO_QUESTION","تحويل إلى سؤال"],["CONVERT_TO_RECOMMENDATION","تحويل إلى توصية"],
 ["NARROW_SCOPE","تضييق النطاق"],["MERGE_WITH_ANOTHER","دمج مع ملاحظة أخرى"],
 ["REQUEST_MORE_EVIDENCE","طلب أدلة"],["ESCALATE","تصعيد"],["WITHDRAW","سحب"]
];
const grounds = [
 ["W01","تعارض"],["W02","عدم الانطباق"],["W03","خارج اختصاص الحوكمة"],
 ["W04","ضوابط كافية"],["W05","أدلة غير كافية"],["W06","تكرار"],
 ["W07","توصية غير متناسبة"],["W08","صلاحية غير صحيحة"],["W09","تفاصيل تشغيلية"],
 ["W10","أهمية محدودة"],["W11","سوء تفسير"],["W12","معالج في بند آخر"],
 ["W13","بيانات قديمة"],["W14","معالجة غير فعالة"],["W15","سبب آخر"]
];
function App() {
 const [token,setToken]=useState(""); const [cases,setCases]=useState<CaseSummary[]>([]);
 const [active,setActive]=useState<CaseData|null>(null); const [events,setEvents]=useState<EventData[]>([]);
 const [focus,setFocus]=useState(0); const [choice,setChoice]=useState("KEEP_WITH_REVISIONS");
 const [reason,setReason]=useState(""); const [ground,setGround]=useState("W12");
 const [evidence,setEvidence]=useState(""); const [view,setView]=useState("compare");
 const [error,setError]=useState(""); const [success,setSuccess]=useState("");
 const [ruleId,setRuleId]=useState("SYN-RULE-001"); const [ruleReason,setRuleReason]=useState("");
 const [ruleAction,setRuleAction]=useState("DEFER");
 const [analyticsData,setAnalyticsData]=useState<Record<string,unknown>|null>(null);
 async function api<T>(url:string,method="GET",body?:object):Promise<T>{
   const resp=await fetch(url,{method,headers:{"Authorization":"Bearer "+token,...(body?{"Content-Type":"application/json"}:{})},...(body?{body:JSON.stringify(body)}:{})});
   if(!resp.ok){let t="";try{t=JSON.stringify(await resp.json())}catch{}throw Error(resp.status+" "+t)}
   return resp.json() as Promise<T>;
 }
 async function load(){setError("");try{setCases(await api<CaseSummary[]>("/api/cases"))}catch(e){setError(String(e))}}
 async function openCase(id:string){setError("");try{const [c,ev]=await Promise.all([api<CaseData>("/api/cases/"+encodeURIComponent(id)),api<EventData[]>("/api/cases/"+encodeURIComponent(id)+"/events")]);setActive(c);setEvents(ev);setFocus(0);setView("compare");}catch(e){setError(String(e))}}
 async function loadAnalytics(){if(!active)return;try{setAnalyticsData(await api<Record<string,unknown>>("/api/cases/"+encodeURIComponent(active.case_id)+"/analytics"))}catch(e){setError(String(e))}}
 async function save(status:"DRAFT"|"SUBMITTED"){
   if(!active)return;const obs=active.observations[focus];setError("");setSuccess("");
   try{await api("/api/cases/"+encodeURIComponent(active.case_id)+"/observations/"+encodeURIComponent(obs.observation_id)+"/decisions","POST",{
     decision:choice,rationale:reason,expected_evidence_hash:active.evidence_hash,status,
     reasons:choice==="WITHDRAW"?[ground]:[],
     evidence_refs:evidence.trim()?[evidence.trim()]:[],
     material_categories:obs.material_categories||[]
   });setSuccess(status==="SUBMITTED"?"حُفظ القرار وأُضيف إلى سجل التدقيق":"حُفظت المسودة");
   await openCase(active.case_id);
   }catch(e){setError(String(e))}
 }
 async function reviewRule(){if(!active)return;setError("");setSuccess("");
   const hashes=events.filter(e=>e.event_type==="OBSERVATION_CALIBRATION"&&JSON.parse(e.payload_json).status==="SUBMITTED").map(e=>e.event_hash);
   try{await api("/api/cases/"+encodeURIComponent(active.case_id)+"/rules/"+encodeURIComponent(ruleId)+"/review","POST",
     {action:ruleAction,rationale:ruleReason,observation_event_hashes:hashes,profile_version:"PROVISIONAL-v1"});
     setSuccess("حُفظت مراجعة القاعدة، ولم تُنشأ صلاحية إصدار أو اعتماد مؤسسي");
     await openCase(active.case_id);setView("rules");
   }catch(e){setError(String(e))}
 }
 const obs=active?.observations[focus]; const comparison=obs?diffTokens(obs.original_text||"",obs.reviewed_text||""):null; const decisionEvents=events.filter(e=>e.event_type==="OBSERVATION_CALIBRATION");
 const latest=obs?decisionEvents.filter(e=>e.observation_id===obs.observation_id).at(-1):null;
 useEffect(()=>{document.title="MAT | معايرة المنهجية المهنية"},[]);
 return <main dir="rtl">
  <header><div><small>الصندوق الثقافي | نموذج تطوير تقني تجريبي</small><h1>MAT — معايرة منهجية المراجعة</h1><p>قرارات بشرية موثقة • أدلة مرتبطة بالمصدر • قواعد تعلم منفصلة</p></div><span className="badge">SYNTHETIC LOCAL DEVELOPMENT ONLY</span></header>
  <section className="login"><label>رمز جلسة التطوير المحلي (لا تستخدم بيانات مؤسسية)<input type="password" value={token} onChange={e=>setToken(e.target.value)} autoComplete="off" placeholder="الصق رمز التطوير المؤقت"/></label><button onClick={load}>الاتصال وعرض القضايا</button></section>
  {error&&<div role="alert" className="error">{error}</div>}{success&&<div role="status" className="success">{success}</div>}
  <nav><button onClick={()=>{setActive(null);setView("cases")}}>لوحة القضايا</button>{active&&<>
    <button onClick={()=>setView("compare")}>مقارنة الملاحظات</button>
    <button onClick={()=>{setView("analytics");void loadAnalytics()}}>المؤشرات</button>
    <button onClick={()=>setView("rules")}>اعتماد قواعد DNA</button>
    <button onClick={()=>setView("history")}>سجل القرارات</button>
  </>}</nav>
  {!active?<section className="panel"><h2>القضايا المتاحة</h2><p>لا تظهر إلا القضايا المصرح بها في بيئة التجربة. لم تُستورد ملفات الصندوق الحقيقية.</p>
   {cases.length===0?<p className="empty">لا توجد قضايا أو لم يتم الاتصال بالخادم.</p>:cases.map(c=><article className="row" key={c.case_id}><strong>{c.case_id}</strong><span>الملاحظات: {String(c.stats.observation_count)} • المعايرة: {String(c.stats.submitted_observations)}</span><button onClick={()=>openCase(c.case_id)}>فتح القضية</button></article>)}
  </section>:<>
    <section className="stats"><div><small>القضية</small><strong>{active.case_id}</strong></div><div><small>الملاحظات</small><strong>{String(active.statistics.observation_count)}</strong></div><div><small>المعاير منها</small><strong>{String(active.statistics.submitted_observations)}</strong></div><div><small>قيد المعايرة</small><strong>{String(active.statistics.pending_observations)}</strong></div><div><small>سلامة التدقيق</small><strong>{active.statistics.audit_chain_valid?"سليمة":"تحقق مطلوب"}</strong></div></section>
    {view==="compare"&&<section className="panel">
      <div className="row"><h2>الملاحظة {focus+1} من {active.observations.length}</h2><div><button disabled={focus<=0} onClick={()=>setFocus(focus-1)}>السابق</button><button disabled={focus>=active.observations.length-1} onClick={()=>setFocus(focus+1)}>التالي</button></div></div>
      {obs&&<><p className="tag">{obs.observation_id} · {obs.observed_change||"غير مصنف"}</p>
      <div className="comparison"><article><h3>الملاحظة الأصلية</h3><p>{comparison?.old.map((x,i)=><span key={i} className={x.op==="removed"?"removed":undefined}>{x.text}</span>)}</p></article><article><h3>النص في النسخة المعادة</h3><p>{obs.reviewed_text ? comparison?.revised.map((x,i)=><span key={i} className={x.op==="added"?"added":undefined}>{x.text}</span>):"غير موجود في هذه النسخة — ليس دليلاً على سحب معتمد"}</p></article></div>
      <p className="notice">تُميز الإضافات باللون الأخضر والمحذوفات باللون الأحمر؛ المقارنة لعرض التحرير فقط ولا تُثبت سبب الحذف. {comparison?.bounded?"(تم تقييد المقارنة لطول النص)":""}</p>
      {latest&&<p className="tag">آخر إجراء: {JSON.parse(latest.payload_json).decision} ({JSON.parse(latest.payload_json).status})</p>}
      <div className="form"><h3>تسجيل القرار المهني</h3><label>الإجراء<select value={choice} onChange={e=>setChoice(e.target.value)}>{choices.map(x=><option value={x[0]} key={x[0]}>{x[1]}</option>)}</select></label>
      {choice==="WITHDRAW"&&<label>سبب السحب<select value={ground} onChange={e=>setGround(e.target.value)}>{grounds.map(x=><option value={x[0]} key={x[0]}>{x[1]}</option>)}</select></label>}
      <label>المبرر المهني<textarea value={reason} onChange={e=>setReason(e.target.value)} placeholder="ما الدليل أو السبب وراء هذا القرار؟"/></label>
      <label>مرجع الدليل / فجوة الإثبات<input value={evidence} onChange={e=>setEvidence(e.target.value)} placeholder="مثال: EVIDENCE_GAP:verification-required"/></label>
      {!!obs.material_categories?.length&&<p className="alert">تصنيف عالي الأهمية: {obs.material_categories.join("، ")}. يتطلب السحب مبرراً ومرجعاً واضحاً.</p>}
      <div className="actions"><button onClick={()=>save("DRAFT")}>حفظ مسودة</button><button className="primary" onClick={()=>save("SUBMITTED")}>إرسال قرار المعايرة</button></div></div></>}
    </section>}
    {view==="analytics"&&<section className="panel"><h2>مؤشرات المعايرة</h2><p>الأرقام أدناه مأخوذة من قاعدة البيانات، وليست أهدافاً ثابتة لأسلوب محمد التميمي.</p>
    {Object.entries(active.statistics).map(([k,v])=><div className="row" key={k}><span>{k}</span><strong>{String(v)}</strong></div>)}
    <h3>توزيع الأسئلة والتوصيات — مستخرج من نصوص القضية</h3>
    {analyticsData?Object.entries(analyticsData).map(([k,v])=><div className="row" key={k}><span>{k}</span><strong>{typeof v==="object"?JSON.stringify(v):String(v)}</strong></div>):<p className="notice">لم يتم تحميل بيانات التصنيف بعد.</p>}</section>}
    {view==="rules"&&<section className="panel"><h2>مراجعة قاعدة DNA منفصلة</h2><p>اعتماد قرار على ملاحظة لا يعتمد تلقائياً قاعدة عامة. هذه واجهة مراجعة تجريبية، وليس اعتماداً مؤسسياً.</p>
     <label>معرف القاعدة<input value={ruleId} onChange={e=>setRuleId(e.target.value)}/></label>
     <label>الإجراء<select value={ruleAction} onChange={e=>setRuleAction(e.target.value)}>{["DEFER","REQUEST_MORE_EVIDENCE","REJECT","APPROVE","APPROVE_WITH_CHANGES"].map(x=><option key={x}>{x}</option>)}</select></label>
     <label>المبرر<textarea value={ruleReason} onChange={e=>setRuleReason(e.target.value)}/></label>
     <p className="notice">سيتم ربط المراجعة بجميع قرارات المعايرة المقدمة في القضية؛ يجب تحسين اختيار أدلة محددة قبل اعتماد بشري فعلي.</p>
     <button className="primary" onClick={reviewRule}>حفظ مراجعة القاعدة</button></section>}
    {view==="history"&&<section className="panel"><h2>سجل القرارات غير القابل للاستبدال المباشر</h2>{events.map((e,i)=><article className="history" key={i}><strong>{e.event_type} · {e.observation_id||"القضية"}</strong><small>{e.created_at} · {e.actor}</small><pre>{JSON.stringify(JSON.parse(e.payload_json),null,2)}</pre></article>)}</section>}
  </>}
  <footer>نموذج هندسي تجريبي • لا توجد هوية مؤسسية معتمدة أو صلاحيات إصدار رسمية • لا ترسل مستندات سرية</footer>
 </main>;
}
createRoot(document.getElementById("root")!).render(<React.StrictMode><App/></React.StrictMode>);
