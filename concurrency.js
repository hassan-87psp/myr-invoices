/* MYR Invoices: safe three-way merge for concurrent cloud edits.
   Distinct records merge by stable ID. Changes to the same record (or setting)
   fail closed and require human review. No invoice is silently overwritten. */
(function (root) {
  'use strict';
  const lists = new Set(['invoices','customers','products','requests','imports','audit']);
  const own = (obj,key) => Object.prototype.hasOwnProperty.call(obj||{},key);
  const clone = x => x === undefined ? undefined : JSON.parse(JSON.stringify(x));
  function canonical(x) {
    if (x === undefined) return 'undefined';
    if (x === null || typeof x !== 'object') return JSON.stringify(x);
    if (Array.isArray(x)) return '['+x.map(canonical).join(',')+']';
    return '{'+Object.keys(x).sort().map(k=>JSON.stringify(k)+':'+canonical(x[k])).join(',')+'}';
  }
  const eq = (a,b) => canonical(a) === canonical(b);
  function mergeRows(key, base, mine, theirs) {
    if (![base,mine,theirs].every(x=>x===undefined||Array.isArray(x))) {
      return {ok:false,conflicts:[key+': expected ID-based records']};
    }
    const baseRows=base||[],localRows=mine||[],remoteRows=theirs||[];
    const good=items=>items.every(r=>r&&typeof r==='object'&&typeof r.id==='string'&&r.id.length>0)
      &&new Set(items.map(r=>r.id)).size===items.length;
    if(![baseRows,localRows,remoteRows].every(good))
      return {ok:false,conflicts:[key+': missing or duplicate record IDs']};
    const b=new Map(baseRows.map(r=>[r.id,r]));
    const l=new Map(localRows.map(r=>[r.id,r]));
    const r=new Map(remoteRows.map(r=>[r.id,r]));
    const order=[...localRows,...remoteRows,...baseRows].map(row=>row.id);
    const seen=new Set(), merged=[], conflicts=[];
    for(const id of order){
      if(seen.has(id))continue;seen.add(id);
      const bv=b.get(id),lv=l.get(id),rv=r.get(id);
      const lc=!eq(lv,bv),rc=!eq(rv,bv);
      if(lc&&rc&&!eq(lv,rv)){conflicts.push(key+' / '+id);continue}
      const selected=lc?lv:rv;
      if(selected!==undefined)merged.push(clone(selected));
    }
    return conflicts.length?{ok:false,conflicts}:{ok:true,data:merged};
  }
  function mergeCompany(base, mine, theirs) {
    if(![base,mine,theirs].every(v=>v&&typeof v==='object'&&!Array.isArray(v)))
      return {ok:false,conflicts:['Invalid company snapshot']};
    const out={},conflicts=[];
    const keys=new Set([...Object.keys(base),...Object.keys(mine),...Object.keys(theirs)]);
    for(const key of keys){
      const b=own(base,key)?base[key]:undefined;
      const l=own(mine,key)?mine[key]:undefined;
      const r=own(theirs,key)?theirs[key]:undefined;
      if(key==='nextNo'&&[b,l,r].every(v=>v===undefined||(Number.isSafeInteger(Number(v))&&Number(v)>0))){
        out[key]=Math.max(Number(b)||1001,Number(l)||1001,Number(r)||1001);
      }else if(lists.has(key)){
        const result=mergeRows(key,b,l,r);
        if(!result.ok){conflicts.push(...result.conflicts);continue}
        if(result.data!==undefined)out[key]=result.data;
      }else{
        const lc=!eq(l,b),rc=!eq(r,b);
        if(lc&&rc&&!eq(l,r)){conflicts.push(key);continue}
        const chosen=lc?l:r;
        if(chosen!==undefined)out[key]=clone(chosen);
      }
    }
    if(conflicts.length)return {ok:false,conflicts};
    // The default invoice number shown to two concurrent editors can be the
    // same. Keep all server-established numbers and advance ONLY a newly
    // created, auto-numbered local draft. Manually chosen numbers fail closed.
    const prefix=String(base.prefix||'INV-');
    const starting=Number(base.nextNo)||1001;
    let next=Math.max(starting,Number(mine.nextNo)||starting,Number(theirs.nextNo)||starting);
    const baseIds=new Set((base.invoices||[]).map(i=>i.id));
    const remoteIds=new Set((theirs.invoices||[]).map(i=>i.id));
    const localIds=new Set((mine.invoices||[]).map(i=>i.id));
    const remoteNums=new Set((theirs.invoices||[]).map(i=>String(i.number||'').trim().toLowerCase()));
    const occupied=new Set((out.invoices||[]).map(i=>String(i.number||'').trim().toLowerCase()));
    for(const inv of out.invoices||[]){
      const number=String(inv.number||'').trim();
      const localOnly=localIds.has(inv.id)&&!baseIds.has(inv.id)&&!remoteIds.has(inv.id);
      const n=number.startsWith(prefix)?Number(number.slice(prefix.length)):NaN;
      const auto=Number.isSafeInteger(n)&&n>=starting&&(Number(mine.nextNo)||0)>n;
      if(localOnly&&auto&&remoteNums.has(number.toLowerCase())){
        occupied.delete(number.toLowerCase());
        while(occupied.has((prefix+next).toLowerCase())||remoteNums.has((prefix+next).toLowerCase()))next++;
        inv.number=prefix+next++;
        occupied.add(inv.number.toLowerCase());
      }
    }
    out.nextNo=Math.max(Number(out.nextNo)||starting,next);
    const numbers=new Set();
    for(const inv of out.invoices||[]){
      const num=String(inv.number||'').trim().toLowerCase();
      if(!num)continue;
      if(numbers.has(num))return {ok:false,conflicts:['Duplicate invoice number: '+num]};
      numbers.add(num);
    }
    return {ok:true,data:out,conflicts:[]};
  }
  root.MYR_CONCURRENCY={mergeCompany,canonical,eq};
  if(typeof module!=='undefined'&&module.exports)module.exports=root.MYR_CONCURRENCY;
})(typeof window!=='undefined'?window:globalThis);
