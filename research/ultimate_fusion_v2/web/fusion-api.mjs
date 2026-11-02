// Call ONLY after existing BOAT LAB authorize() and DATA_READY checks.
// No change to current production worker or bindings is made here.
export async function fusionQuery(request,env){
 const u=new URL(request.url);if(u.pathname!=='/api/fusion')return undefined;
 if(!['GET','HEAD'].includes(request.method))return new Response(null,{status:405});
 const id=u.searchParams.get('id');if(!/^\d{8}_(0[1-9]|1\d|2[0-4])_(0[1-9]|1[0-2])$/.test(id||''))return Response.json({error:'invalid id'},{status:400});
 if(!env.ARCHIVE)return Response.json({error:'未接続'},{status:503});
 const obj=await env.ARCHIVE.get(`research/ultimate_fusion_v2/replay/${id}.json`);
 return obj?new Response(request.method==='HEAD'?null:obj.body,{headers:{'Content-Type':'application/json; charset=utf-8','Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'}}):Response.json({error:'未取得'},{status:404});
}
