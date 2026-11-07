// Narrow FYERS history contract fixture. No real credentials, no request-header logging.
const http=require('http'); let mode='ok',calls=0;
http.createServer((req,res)=>{
 const u=new URL(req.url,'http://fixture');
 const send=(n,b)=>{res.writeHead(n,{'content-type':'application/json'});res.end(JSON.stringify(b));};
 if(u.pathname==='/fixture/mode'){mode=u.searchParams.get('value');calls=0;return send(200,{mode});}
 if(u.pathname==='/fixture/state')return send(200,{mode,calls});
 if(u.pathname!=='/history')return send(501,{s:'error'});
 calls++;
 console.log(JSON.stringify({method:req.method,path:u.pathname,mode,calls}));
 if(req.method!=='GET'||u.searchParams.get('resolution')!=='1'||u.searchParams.get('date_format')!=='0')return send(400,{s:'error'});
 if(mode==='auth')return send(401,{s:'error',code:-16});
 if(mode==='rate')return send(429,{s:'error',code:429});
 if(mode==='body-rate')return send(200,{s:'error',code:-360});
 if(mode==='unavailable')return send(503,{s:'error'});
 if(mode==='html'){res.writeHead(200,{'content-type':'text/html'});return res.end('unavailable');}
 const ts=Number(u.searchParams.get('range_from'));
 if(mode==='malformed')return send(200,{s:'ok',candles:[[ts,100,90,110,100,10]]});
 if(mode==='outside')return send(200,{s:'ok',candles:[[ts-60,100,105,98,104,10]]});
 return send(200,{s:'ok',candles:[[ts,100,105,98,104,1200]]});
}).listen(process.env.PORT||4922,'127.0.0.1');
