const http=require('http');let reads=0,writes=0,appends=0;
http.createServer(async(req,res)=>{for await(const c of req){};let status=200,body={};
if(req.url==='/reads'){reads++;status=reads===1?429:reads===2?503:200;}
else if(req.url==='/values:batchUpdate'){writes++;status=writes===1?429:200;}
else if(req.url==='/values:append'){appends++;status=429;}
else if(req.url==='/fixture/state')body={reads,writes,appends};
else status=501;
if(status!==200)body={error:{code:status,message:'Synthetic quota failure',status:'RESOURCE_EXHAUSTED'}};
res.writeHead(status,{'content-type':'application/json'});res.end(JSON.stringify(body));
}).listen(process.env.PORT||4910,'127.0.0.1');

