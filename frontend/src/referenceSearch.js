export function searchReferences(references,query='',groupId='all'){
  const normalize=text=>text.normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
  const terms=normalize(query.trim()).split(/\s+/).filter(Boolean);
  return references.filter(ref=>(groupId==='all'||ref.groupId===groupId)&&terms.every(term=>normalize(`${ref.title} ${ref.citation} ${ref.url||''}`).includes(term)));
}
