/* CYB3X — umumiy yordamchilar: Telegram, API, Face ID (WebAuthn), toast */
const TG = window.Telegram ? window.Telegram.WebApp : null;
if (TG) { try { TG.ready(); TG.expand(); TG.setHeaderColor && TG.setHeaderColor('#070b0a'); } catch(e){} }

const INIT = TG ? TG.initData : '';

async function api(path, body, extraHeaders) {
  const headers = Object.assign({'Content-Type':'application/json','X-Init-Data':INIT}, extraHeaders||{});
  const res = await fetch(path, {method:'POST', headers, body: JSON.stringify(body||{})});
  let data = {};
  try { data = await res.json(); } catch(e){}
  if (!res.ok && data.ok === undefined) data = {ok:false, error:(data.error||('HTTP '+res.status)), status:res.status};
  data._status = res.status;
  return data;
}

function toast(msg, isErr) {
  let t = document.getElementById('toast');
  if (!t){ t = document.createElement('div'); t.id='toast'; t.className='toast'; document.body.appendChild(t); }
  t.textContent = msg; t.className = 'toast show' + (isErr?' err':'');
  if (TG && TG.HapticFeedback){ try{ TG.HapticFeedback.notificationOccurred(isErr?'error':'success'); }catch(e){} }
  clearTimeout(t._h); t._h = setTimeout(()=>{ t.className='toast'+(isErr?' err':''); }, 3200);
}

/* ---- base64url <-> ArrayBuffer ---- */
function b64uToBuf(s){ s=s.replace(/-/g,'+').replace(/_/g,'/'); const pad='='.repeat((4-s.length%4)%4);
  const bin=atob(s+pad); const b=new Uint8Array(bin.length); for(let i=0;i<bin.length;i++)b[i]=bin.charCodeAt(i); return b.buffer; }
function bufToB64u(buf){ const b=new Uint8Array(buf); let s=''; for(let i=0;i<b.length;i++)s+=String.fromCharCode(b[i]);
  return btoa(s).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,''); }

/* ---- Qurilma barmoq izi (xom) — bitta akkaunt = bitta qurilma ---- */
function deviceRaw(){
  let id = localStorage.getItem('cyb3x_dev');
  if(!id){ id = (crypto.randomUUID?crypto.randomUUID():(Date.now()+'-'+Math.random())); localStorage.setItem('cyb3x_dev', id); }
  const n = navigator;
  return [id, n.userAgent, n.platform, n.language, screen.width+'x'+screen.height, (n.hardwareConcurrency||0)].join('|');
}

function faceSupported(){ return !!(window.PublicKeyCredential && navigator.credentials && navigator.credentials.create); }

/* ---- Face ID: ro'yxatdan o'tish ---- */
async function faceRegister(label){
  const opts = await api('/api/student/register/options');
  if (opts.ok === false) throw new Error(opts.error||'options xato');
  const pk = opts.publicKey || opts; // server options_to_json {publicKey? yoki to'g'ridan}
  const publicKey = pk.publicKey ? pk.publicKey : pk;
  publicKey.challenge = b64uToBuf(publicKey.challenge);
  publicKey.user.id = b64uToBuf(publicKey.user.id);
  if (publicKey.excludeCredentials) publicKey.excludeCredentials.forEach(c=>c.id=b64uToBuf(c.id));
  const cred = await navigator.credentials.create({publicKey});
  const credential = {
    id: cred.id, rawId: bufToB64u(cred.rawId), type: cred.type,
    response: {
      attestationObject: bufToB64u(cred.response.attestationObject),
      clientDataJSON: bufToB64u(cred.response.clientDataJSON),
    },
    clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {},
  };
  const r = await api('/api/student/register/verify', {credential, device:deviceRaw(), label:label||'Qurilma'});
  if (!r.ok) throw new Error(r.error||'tasdiqlanmadi');
  return r;
}

/* ---- Face ID: autentifikatsiya (options server beradi) ---- */
async function faceAssert(optionsFromServer){
  const publicKey = optionsFromServer.publicKey ? optionsFromServer.publicKey : optionsFromServer;
  publicKey.challenge = b64uToBuf(publicKey.challenge);
  if (publicKey.allowCredentials) publicKey.allowCredentials.forEach(c=>c.id=b64uToBuf(c.id));
  const assn = await navigator.credentials.get({publicKey});
  return {
    id: assn.id, rawId: bufToB64u(assn.rawId), type: assn.type,
    response: {
      authenticatorData: bufToB64u(assn.response.authenticatorData),
      clientDataJSON: bufToB64u(assn.response.clientDataJSON),
      signature: bufToB64u(assn.response.signature),
      userHandle: assn.response.userHandle ? bufToB64u(assn.response.userHandle) : null,
    },
    clientExtensionResults: assn.getClientExtensionResults ? assn.getClientExtensionResults() : {},
  };
}

function el(id){ return document.getElementById(id); }
function show(id){ el(id).classList.remove('hide'); }
function hide(id){ el(id).classList.add('hide'); }
