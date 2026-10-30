const http=require('http'),crypto=require('crypto');let publicKey='',mode='okay',saved={};
http.createServer(async(req,res)=>{let raw='';for await(const c of req)raw+=c;const u=new URL(req.url,'http://fixture');const send=(code,b)=>{res.writeHead(code,{'content-type':'application/json'});res.end(JSON.stringify(b));};
if(u.pathname==='/fixture/config'){const body=JSON.parse(raw||'{}');publicKey=body.publicKey||publicKey;mode=body.mode||'okay';return send(200,{});}
if(u.pathname==='/fixture/state')return send(200,saved);
if(u.pathname!=='/api/comparisons'||req.method!=='POST')return send(501,{error:'Outside fixture contract'});
if(!publicKey||!crypto.verify('RSA-SHA256',Buffer.from(raw),publicKey,Buffer.from(req.headers['x-comparison-signature']||'','base64')))return send(401,{error:'Signature rejected'});
const body=JSON.parse(raw);if(body.version!=='comparison-v1'||Date.now()-Date.parse(body.sentAt)>300000)return send(422,{error:'Schema or timestamp'});
if(mode==='failure')return send(503,{error:'Synthetic storage failure'});
if(!['month','index'].includes(body.kind))return send(422,{error:'Schema'});
saved[body.kind==='index'?'index':body.month]=body;return send(200,{ok:true});
}).listen(process.env.PORT||4900,'127.0.0.1');

