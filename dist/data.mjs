/** Static hosts may return their HTML homepage with HTTP 200 for missing files. */
export async function readJson(response,{optional=false,label='Data'}={}){
  if(optional&&(response.status===404||response.status===204))return null;
  if(!response.ok)throw new Error(`${label} could not be loaded (HTTP ${response.status}).`);
  const body=await response.text();
  const isHtml=(response.headers.get('content-type')||'').includes('text/html')||/^\s*</.test(body);
  if(optional&&(isHtml||!body.trim()))return null;
  if(isHtml)throw new Error(`${label} returned a webpage instead of JSON. Please refresh and try again.`);
  try{return JSON.parse(body);}catch{throw new Error(`${label} contains invalid JSON.`);}
}
