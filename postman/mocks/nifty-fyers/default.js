// Contract fixture only, no real tokens or market data. Never log request headers.
const http=require('http'); let mode='ok',calls=0;
http.createServer(async(req,res)=>{
 const u=new URL(req.url,'http://fixture'); const send=(n,b)=>{res.writeHead(n,{'content-type':'application/json'});res.end(JSON.stringify(b));};
 if(u.pathname==='/fixture/mode'){mode=u.searchParams.get('value');calls=0;return send(200,{mode});}
 if(u.pathname==='/fixture/state')return send(200,{mode,calls});
 if(u.pathname!=='/history')return send(501,{s:'error'});
 calls++;
 if(mode==='auth')return send(401,{s:'error',code:-16});
 if(mode==='rate'&&calls<3)return send(429,{s:'error'});
 if(mode==='unavailable')return send(503,{s:'error'});
 if(mode==='malformed')return send(200,{s:'ok',candles:[[1,100,90,110,100,0]]});
 return send(200,{s:'ok',candles:[[Date.parse(u.searchParams.get('range_to')+'T00:00:00+05:30')/1000,100,105,98,104,1200]]});
}).listen(process.env.PORT||4911,'127.0.0.1');
