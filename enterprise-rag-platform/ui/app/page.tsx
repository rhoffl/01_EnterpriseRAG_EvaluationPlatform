"use client";
import {FormEvent, useState} from "react";

type Result={answer:string;abstained:boolean;abstention_reason?:string;citations:{evidence_id:string;title:string;page_start?:number;quote:string}[];latency_ms:Record<string,number>};
const tenant="00000000-0000-0000-0000-000000000001";

export default function Home(){
  const [question,setQuestion]=useState(""); const [result,setResult]=useState<Result|null>(null); const [busy,setBusy]=useState(false); const [error,setError]=useState<string|null>(null);
  async function ask(event:FormEvent){event.preventDefault();setBusy(true);setResult(null);setError(null);
    const apiUrl=process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    try {
      const response=await fetch(`${apiUrl}/v1/query`,{method:"POST",headers:{"content-type":"application/json","x-user-id":"demo-user","x-tenant-id":tenant,"x-roles":"reader"},body:JSON.stringify({question,retrieval_mode:"hybrid",top_k:8})});
      if(!response.ok){const detail=await response.text();throw new Error(`API ${response.status}: ${detail || response.statusText}`);}
      setResult(await response.json());
    } catch (cause) {
      setError(cause instanceof Error?cause.message:"Unable to reach the serving API.");
    } finally {setBusy(false);}
  }
  return <main><header><p>Enterprise RAG</p><h1>Answers you can verify</h1><span>Hybrid retrieval · role-aware evidence · calibrated abstention</span></header>
    <form onSubmit={ask}><label htmlFor="question">Ask the authorized document collection</label><textarea id="question" value={question} onChange={e=>setQuestion(e.target.value)} required minLength={2}/><button disabled={busy}>{busy?"Searching…":"Ask"}</button></form>
    {error&&<section aria-live="assertive"><h2>Request failed</h2><p>{error}</p><small>Confirm the serving API is available at {process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/health.</small></section>}
    {result&&<section aria-live="polite"><h2>{result.abstained?"No supported answer":"Answer"}</h2><p>{result.answer}</p>{result.abstention_reason&&<small>Reason: {result.abstention_reason}</small>}
      {!result.abstained&&<><h2>Evidence</h2>{result.citations.map(c=><article key={c.evidence_id}><strong>{c.evidence_id} · {c.title}{c.page_start?` · page ${c.page_start}`:""}</strong><p>{c.quote}</p></article>)}</>}
      <small>Total latency: {result.latency_ms.total?.toFixed(0)} ms</small></section>}
  </main>;
}
